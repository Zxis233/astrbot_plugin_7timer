# astrbot_plugin_7timer

AstrBot 插件：根据经纬度生成 7timer 天文天气图。

默认接口示例：

```text
https://www.7timer.info/bin/astro.php?lon=108.648&lat=34.236&lang=zh-CN&ac=0&unit=metric&tzshift=0
```

## 功能

- `/7timer` 使用配置中的默认经纬度发送图表。
- `/7timer <经度> <纬度>` 临时使用指定经纬度发送图表。
- `/7timer_set <经度> <纬度>` 保存默认经纬度。
- `/7timer_bind` 把当前会话加入定时推送目标。
- `/7timer_unbind` 从定时推送目标中移除当前会话。
- `/7timer_schedule [on|off|status]` 开启、关闭或查看定时推送状态。

命令别名：

- `/7t`、`/astro` 等同于 `/7timer`
- `/7timer_config` 等同于 `/7timer_set`
- `/7timer_timer` 等同于 `/7timer_schedule`

## 示例

```text
/7timer
/7timer 108.648 34.236
/7timer lon=108.648 lat=34.236
/7timer_set 108.648 34.236
/7timer_bind
/7timer_schedule on
```

## 配置

插件会通过 `_conf_schema.json` 自动生成配置文件。主要配置项：

- `default_lon` / `default_lat`：默认经纬度。
- `lang`：图表语言，默认 `zh-CN`。
- `unit`：单位制，默认 `metric`，也可填 `british`。
- `ac`：7timer 的大气透明度/海拔修正参数，默认 `0`。
- `tzshift`：时区显示偏移参数，默认 `0`。
- `output`：可选的 7timer `output` 参数，留空时使用默认图片输出。
- `reply_with_link`：是否在图片后附带图表 URL。
- `proxy.enabled`：是否启用代理下载。开启后插件会先通过代理请求 7timer 图表，再发送本地图片。
- `proxy.url`：HTTP/HTTPS 代理地址，例如 `http://127.0.0.1:7890`。
- `proxy.timeout_seconds`：代理请求超时时间，单位秒。
- `schedule.enabled`：是否启用定时推送。
- `schedule.interval_minutes`：定时推送间隔，默认 720 分钟。
- `schedule.send_on_start`：插件启动后是否先推送一次。
- `schedule.targets`：定时推送目标会话，建议通过 `/7timer_bind` 自动写入。

## 代理

默认情况下，插件会把 7timer 图片 URL 交给 AstrBot/平台适配器发送。启用 `proxy.enabled` 后，插件会自己通过 `proxy.url` 下载图表到临时文件，再把本地图片交给 AstrBot 发送，因此 7timer 请求会实际走代理。

## 定时推送

定时推送需要两步：

1. 在要接收图表的会话中发送 `/7timer_bind`。
2. 发送 `/7timer_schedule on` 开启定时推送。

插件重载或停用时会自动取消后台定时任务。
