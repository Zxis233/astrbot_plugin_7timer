import asyncio
import os
import re
import tempfile
from typing import Any
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, MessageEventResult, filter
from astrbot.api.star import Context, Star, register


PLUGIN_NAME = "astrbot_plugin_7timer"
DEFAULT_BASE_URL = "https://www.7timer.info/bin/astro.php"
COMMAND_NAMES = ("7timer", "7t", "astro")
SET_COMMAND_NAMES = ("7timer_set", "7timer_config")
SCHEDULE_COMMAND_NAMES = ("7timer_schedule", "7timer_timer")
VALID_UNITS = {"metric", "british"}


@register(
    PLUGIN_NAME,
    "Esing",
    "根据经纬度生成 7timer 天文天气图，并支持对话触发和定时推送。",
    "1.0.0",
)
class SevenTimerPlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context, config)
        self.config = config or {}
        self._schedule_task: asyncio.Task | None = None

    async def initialize(self):
        self._restart_schedule_task()

    async def terminate(self):
        await self._stop_schedule_task()

    @filter.command("7timer", alias={"7t", "astro"})
    async def seven_timer(self, event: AstrMessageEvent):
        """发送 7timer 天文天气图。用法：/7timer [经度 纬度]"""
        args = self._extract_args(event.get_message_str(), COMMAND_NAMES)
        try:
            lon, lat = self._location_from_args(args)
        except ValueError as e:
            yield event.plain_result(str(e))
            return

        try:
            yield await self._build_result(event, lon, lat)
        except Exception as e:
            yield event.plain_result(self._failure_text(e))

    @filter.command("7timer_set", alias={"7timer_config"})
    async def seven_timer_set(self, event: AstrMessageEvent):
        """设置默认经纬度。用法：/7timer_set <经度> <纬度>"""
        args = self._extract_args(event.get_message_str(), SET_COMMAND_NAMES)
        try:
            lon, lat = self._location_from_args(args, require_args=True)
        except ValueError as e:
            yield event.plain_result(str(e))
            return

        self.config["default_lon"] = lon
        self.config["default_lat"] = lat
        self._save_config()
        yield event.plain_result(
            f"已设置默认位置：经度 {lon:.3f}，纬度 {lat:.3f}。\n"
            "发送 /7timer 可获取当前默认位置的 7timer 图表。"
        )

    @filter.command("7timer_bind")
    async def seven_timer_bind(self, event: AstrMessageEvent):
        """把当前会话加入定时推送目标。"""
        targets = self._schedule_targets()
        session = event.unified_msg_origin
        if session not in targets:
            targets.append(session)
            self._schedule_config()["targets"] = targets
            self._save_config()
        self._restart_schedule_task()
        yield event.plain_result(
            "已绑定当前会话为 7timer 定时推送目标。\n"
            "如需启用定时推送，请发送 /7timer_schedule on。"
        )

    @filter.command("7timer_unbind")
    async def seven_timer_unbind(self, event: AstrMessageEvent):
        """从定时推送目标中移除当前会话。"""
        targets = self._schedule_targets()
        session = event.unified_msg_origin
        if session in targets:
            targets.remove(session)
            self._schedule_config()["targets"] = targets
            self._save_config()
        self._restart_schedule_task()
        yield event.plain_result("已从 7timer 定时推送目标中移除当前会话。")

    @filter.command("7timer_schedule", alias={"7timer_timer"})
    async def seven_timer_schedule(self, event: AstrMessageEvent):
        """查看或开关定时推送。用法：/7timer_schedule [on|off|status]"""
        args = self._extract_args(event.get_message_str(), SCHEDULE_COMMAND_NAMES)
        action = args.strip().lower() or "status"
        schedule = self._schedule_config()

        if action in {"on", "enable", "enabled", "true", "1", "开启", "启用"}:
            if not self._schedule_targets():
                yield event.plain_result(
                    "还没有定时推送目标。请先在目标会话发送 /7timer_bind。"
                )
                return
            schedule["enabled"] = True
            self._save_config()
            self._restart_schedule_task()
            yield event.plain_result(self._schedule_status_text("已开启定时推送。"))
            return

        if action in {"off", "disable", "disabled", "false", "0", "关闭", "停用"}:
            schedule["enabled"] = False
            self._save_config()
            self._restart_schedule_task()
            yield event.plain_result(self._schedule_status_text("已关闭定时推送。"))
            return

        if action in {"status", "状态"}:
            yield event.plain_result(
                self._schedule_status_text("7timer 定时推送状态：")
            )
            return

        yield event.plain_result("用法：/7timer_schedule [on|off|status]")

    async def _build_result(
        self, event: AstrMessageEvent, lon: float, lat: float
    ) -> MessageEventResult:
        url = self._build_chart_url(lon, lat)
        image_type, image_ref = await self._resolve_image_ref(url)
        result = MessageEventResult()
        self._append_chart_image(
            result,
            title="7timer 天文天气图",
            lon=lon,
            lat=lat,
            url=url,
            image_type=image_type,
            image_ref=image_ref,
        )
        if image_type == "file":
            track_temp_file = getattr(event, "track_temporary_local_file", None)
            if callable(track_temp_file):
                track_temp_file(image_ref)
        return result

    def _build_active_message(
        self,
        lon: float,
        lat: float,
        url: str,
        image_type: str,
        image_ref: str,
    ) -> MessageChain:
        chain = MessageChain()
        self._append_chart_image(
            chain,
            title="7timer 定时天气图",
            lon=lon,
            lat=lat,
            url=url,
            image_type=image_type,
            image_ref=image_ref,
        )
        return chain

    def _append_chart_image(
        self,
        message: MessageChain | MessageEventResult,
        *,
        title: str,
        lon: float,
        lat: float,
        url: str,
        image_type: str,
        image_ref: str,
    ) -> None:
        message.message(f"{title}\n经度 {lon:.3f}，纬度 {lat:.3f}\n")
        if image_type == "file":
            message.file_image(image_ref)
        else:
            message.url_image(image_ref)
        if self._bool_config("reply_with_link", True):
            message.message(f"\n图表链接：{url}")

    def _build_chart_url(self, lon: float, lat: float) -> str:
        params = {
            "lon": f"{lon:.3f}",
            "lat": f"{lat:.3f}",
            "lang": str(self.config.get("lang") or "zh-CN"),
            "ac": self._int_config("ac", 0),
            "unit": self._unit(),
            "tzshift": self._int_config("tzshift", 0),
        }
        output = str(self.config.get("output") or "").strip()
        if output:
            params["output"] = output
        return f"{self._base_url()}?{urlencode(params)}"

    def _location_from_args(
        self, args: str, *, require_args: bool = False
    ) -> tuple[float, float]:
        args = args.strip()
        if args:
            lon, lat = self._parse_lon_lat(args)
        elif require_args:
            raise ValueError("请提供经纬度，例如：/7timer_set 108.648 34.236")
        else:
            lon = self._float_config("default_lon", 108.648)
            lat = self._float_config("default_lat", 34.236)
        self._validate_location(lon, lat)
        return lon, lat

    def _parse_lon_lat(self, raw: str) -> tuple[float, float]:
        keyed = self._parse_keyed_location(raw)
        if keyed is not None:
            return keyed

        parts = [p for p in re.split(r"[\s,，;；]+", raw.strip()) if p]
        if len(parts) != 2:
            raise ValueError(
                "经纬度格式不正确。用法：/7timer 108.648 34.236，"
                "或 /7timer lon=108.648 lat=34.236。"
            )
        try:
            lon = float(parts[0])
            lat = float(parts[1])
        except ValueError as e:
            raise ValueError("经纬度必须是数字，例如：/7timer 108.648 34.236") from e
        return lon, lat

    def _parse_keyed_location(self, raw: str) -> tuple[float, float] | None:
        matches = dict(
            (key.lower(), value)
            for key, value in re.findall(
                r"\b(lon|lng|longitude|经度|lat|latitude|纬度)\s*=\s*(-?\d+(?:\.\d+)?)",
                raw,
                flags=re.IGNORECASE,
            )
        )
        if not matches:
            return None

        lon_value = (
            matches.get("lon")
            or matches.get("lng")
            or matches.get("longitude")
            or matches.get("经度")
        )
        lat_value = matches.get("lat") or matches.get("latitude") or matches.get("纬度")
        if lon_value is None or lat_value is None:
            raise ValueError("请同时提供经度和纬度，例如：lon=108.648 lat=34.236")
        return float(lon_value), float(lat_value)

    def _validate_location(self, lon: float, lat: float) -> None:
        if not -180 <= lon <= 180:
            raise ValueError("经度必须在 -180 到 180 之间。")
        if not -90 <= lat <= 90:
            raise ValueError("纬度必须在 -90 到 90 之间。")

    async def _schedule_loop(self):
        first_run = True
        while True:
            schedule = self._schedule_config()
            if not self._schedule_enabled() or not self._schedule_targets():
                return

            interval_seconds = self._schedule_interval_seconds()
            if first_run and self._bool_value(schedule.get("send_on_start"), False):
                delay = max(0, self._int_value(schedule.get("start_delay_seconds"), 0))
            else:
                delay = interval_seconds

            first_run = False
            await asyncio.sleep(delay)
            await self._send_scheduled_chart()

    async def _send_scheduled_chart(self):
        if not self._schedule_enabled():
            return
        targets = self._schedule_targets()
        if not targets:
            return
        try:
            lon, lat = self._location_from_args("")
        except ValueError as e:
            logger.warning(f"7timer 定时推送跳过：{e}")
            return

        url = self._build_chart_url(lon, lat)
        image_type = "url"
        image_ref = url
        try:
            image_type, image_ref = await self._resolve_image_ref(url)
        except Exception as e:
            logger.warning(f"7timer 定时推送失败：{e}")
            await self._send_failure_to_targets(targets, e)
            return

        try:
            for target in targets:
                try:
                    ok = await self.context.send_message(
                        target,
                        self._build_active_message(
                            lon,
                            lat,
                            url,
                            image_type,
                            image_ref,
                        ),
                    )
                    if not ok:
                        logger.warning(f"7timer 定时推送未找到平台：{target}")
                except Exception as e:
                    logger.warning(f"7timer 定时推送失败：{target}, {e}")
                    await self._send_failure_to_target(target, e)
        finally:
            if image_type == "file":
                self._remove_file_silent(image_ref)

    async def _send_failure_to_targets(
        self,
        targets: list[str],
        error: Exception | str | None = None,
    ) -> None:
        for target in targets:
            await self._send_failure_to_target(target, error)

    async def _send_failure_to_target(
        self,
        target: str,
        error: Exception | str | None = None,
    ) -> None:
        try:
            await self.context.send_message(
                target,
                MessageChain().message(self._failure_text(error)),
            )
        except Exception as e:
            logger.warning(f"7timer 失败提示发送失败：{target}, {e}")

    def _restart_schedule_task(self):
        if self._schedule_task and not self._schedule_task.done():
            self._schedule_task.cancel()
        self._schedule_task = None
        if self._schedule_enabled() and self._schedule_targets():
            self._schedule_task = asyncio.create_task(
                self._schedule_loop(),
                name="astrbot-plugin-7timer-schedule",
            )

    async def _stop_schedule_task(self):
        task = self._schedule_task
        self._schedule_task = None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    def _schedule_status_text(self, prefix: str) -> str:
        schedule = self._schedule_config()
        enabled = self._schedule_enabled()
        targets = self._schedule_targets()
        interval_minutes = self._schedule_interval_seconds() // 60
        return (
            f"{prefix}\n"
            f"状态：{'开启' if enabled else '关闭'}\n"
            f"间隔：{interval_minutes} 分钟\n"
            f"启动后立即发送：{'是' if self._bool_value(schedule.get('send_on_start'), False) else '否'}\n"
            f"目标会话数：{len(targets)}"
        )

    def _schedule_config(self) -> dict[str, Any]:
        schedule = self.config.get("schedule")
        if not isinstance(schedule, dict):
            schedule = {}
            self.config["schedule"] = schedule
        return schedule

    def _schedule_enabled(self) -> bool:
        return self._bool_value(self._schedule_config().get("enabled"), False)

    def _schedule_targets(self) -> list[str]:
        schedule = self._schedule_config()
        targets = schedule.get("targets")
        if isinstance(targets, str):
            targets = [targets]
        if not isinstance(targets, list):
            targets = []
        cleaned = [str(target).strip() for target in targets if str(target).strip()]
        schedule["targets"] = cleaned
        return cleaned

    def _schedule_interval_seconds(self) -> int:
        raw = self._schedule_config().get("interval_minutes", 720)
        return max(1, self._int_value(raw, 720)) * 60

    def _base_url(self) -> str:
        base_url = str(self.config.get("base_url") or DEFAULT_BASE_URL).strip()
        return base_url or DEFAULT_BASE_URL

    async def _resolve_image_ref(self, url: str) -> tuple[str, str]:
        return "file", await asyncio.to_thread(self._download_chart, url)

    def _download_chart(self, url: str) -> str:
        handlers = []
        if self._proxy_enabled():
            proxy_url = self._proxy_url()
            if not proxy_url:
                raise RuntimeError("已启用代理，但 proxy.url 为空。")
            handlers.append(ProxyHandler({"http": proxy_url, "https": proxy_url}))
        else:
            handlers.append(ProxyHandler({}))

        opener = build_opener(*handlers)
        request = Request(
            url,
            headers={"User-Agent": "astrbot-plugin-7timer/1.0"},
        )
        try:
            with opener.open(
                request, timeout=self._request_timeout_seconds()
            ) as response:
                content_type = response.headers.get("Content-Type", "")
                data = response.read()
        except Exception as e:
            raise RuntimeError(str(e)) from e

        if not data:
            raise RuntimeError("7timer 返回内容为空。")

        fd, path = tempfile.mkstemp(
            prefix="astrbot_7timer_",
            suffix=self._image_suffix(content_type),
        )
        with os.fdopen(fd, "wb") as file:
            file.write(data)
        return path

    def _request_timeout_seconds(self) -> int:
        if self._proxy_enabled():
            return self._proxy_timeout_seconds()
        return max(1, self._int_value(self.config.get("request_timeout_seconds"), 30))

    def _failure_text(self, error: Exception | str | None = None) -> str:
        failure = self._failure_config()
        message = str(
            failure.get("message") or "获取 7timer 图表失败，请稍后再试。"
        ).strip()
        if not message:
            message = "获取 7timer 图表失败，请稍后再试。"
        if error and self._bool_value(failure.get("include_error_details"), False):
            return f"{message}\n错误详情：{error}"
        return message

    def _failure_config(self) -> dict[str, Any]:
        failure = self.config.get("failure")
        if not isinstance(failure, dict):
            failure = {}
            self.config["failure"] = failure
        return failure

    def _image_suffix(self, content_type: str) -> str:
        content_type = content_type.lower()
        if "jpeg" in content_type or "jpg" in content_type:
            return ".jpg"
        if "gif" in content_type:
            return ".gif"
        if "webp" in content_type:
            return ".webp"
        return ".png"

    def _remove_file_silent(self, path: str) -> None:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except OSError as e:
            logger.warning(f"7timer 临时文件清理失败：{path}, {e}")

    def _proxy_config(self) -> dict[str, Any]:
        proxy = self.config.get("proxy")
        if not isinstance(proxy, dict):
            proxy = {}
            self.config["proxy"] = proxy
        return proxy

    def _proxy_enabled(self) -> bool:
        return self._bool_value(self._proxy_config().get("enabled"), False)

    def _proxy_url(self) -> str:
        return str(self._proxy_config().get("url") or "").strip()

    def _proxy_timeout_seconds(self) -> int:
        return max(1, self._int_value(self._proxy_config().get("timeout_seconds"), 30))

    def _unit(self) -> str:
        unit = str(self.config.get("unit") or "metric").strip().lower()
        return unit if unit in VALID_UNITS else "metric"

    def _float_config(self, key: str, default: float) -> float:
        try:
            return float(self.config.get(key, default))
        except (TypeError, ValueError):
            return default

    def _int_config(self, key: str, default: int) -> int:
        return self._int_value(self.config.get(key), default)

    def _int_value(self, value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _bool_config(self, key: str, default: bool) -> bool:
        return self._bool_value(self.config.get(key), default)

    def _bool_value(self, value: Any, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "yes", "1", "on", "enable", "enabled"}:
                return True
            if lowered in {"false", "no", "0", "off", "disable", "disabled"}:
                return False
        return default

    def _save_config(self):
        save_config = getattr(self.config, "save_config", None)
        if callable(save_config):
            save_config()

    def _extract_args(self, message: str | None, command_names: tuple[str, ...]) -> str:
        text = re.sub(r"\s+", " ", (message or "").strip())
        text = text.lstrip("/!！")
        lowered = text.lower()
        for command in command_names:
            command_lower = command.lower()
            if lowered == command_lower:
                return ""
            if lowered.startswith(command_lower + " "):
                return text[len(command) :].strip()
        return ""
