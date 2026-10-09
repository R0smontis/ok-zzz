# 实时调试与游戏控制

启动新版 ok-zzz 后，“调试 → 实时调试与控制”自动开启只读监控。无需按 F9，也无需开始录制。
先在截图方式页面选择游戏窗口；预览显示所选游戏的画面和帧龄。监控读取游戏截图，不移动系统鼠标，也不切换前台。

按钮“接管控制”默认使用手柄后台，停止自动任务后允许后台操作；“释放控制”松开按键。释放后自动任务保持停止，需重新启动。
“停止监控”同时关闭接口、输入监听和调试控制。连接超过 60 秒未发送操作或心跳时自动释放；窗口改变、最小化或分辨率变化也会释放。
调试录制仍可独立使用；实时监控保存最近 600 条事件，长期资料请使用录制或导出。

## 本机客户端

接口地址和认证信息保存在程序目录 `debug/live/session.json`。端口每次启动自动分配，只监听 127.0.0.1。
客户端自动读取认证信息；不要把 session.json 放入公共诊断包。程序退出时会删除当前会话文件。

源码环境：

```powershell
python tools/live_debug.py --root D:\okzzz status
python tools/live_debug.py --root D:\okzzz frame D:\okzzz\debug\live-frame.png
python tools/live_debug.py --root D:\okzzz events
python tools/live_debug.py --root D:\okzzz bundle D:\okzzz\debug\live-bundle
```

无需额外 Python 的打包版：在程序目录运行。无控制台 EXE 请指定 `--output`，客户端不会开启程序主窗口。

```powershell
Start-Process .\ok-zzz.exe -ArgumentList '--live-client --output debug\status.json status' -Wait
Start-Process .\ok-zzz.exe -ArgumentList '--live-client --output debug\frame-result.json frame debug\frame.png' -Wait
```

向 `command` 传 JSON，建议保存为文件后传 `@文件路径`，避免 PowerShell 引号问题：

```json
{"op":"acquire","mode":"gamepad"}
```

```powershell
python tools/live_debug.py --root D:\okzzz command @D:\okzzz\debug\command.json
```

可用指令：

| op | 参数和作用 |
| --- | --- |
| acquire | mode 默认为 gamepad（虚拟 Xbox 手柄），可选 messages（窗口消息）；停止自动任务并接管 |
| release | 释放控制和按键 |
| heartbeat | 续期控制 60 秒 |
| analyze | 对当前截图执行相同的攻击按钮、敌人血条、方向箭头、连携条检测；ocr 默认为 true；roi 为 [x,y,width,height] |
| click | x、y、button（left/right/middle）、duration |
| drag | x、y、end_x、end_y、duration |
| scroll | x、y、amount（正数向下，-10～10） |
| key | key，例如 w、space、esc、mouse_left；duration |
| action | action 为 normal_attack、special_attack、ultimate、dodge、switch_next、switch_prev、chain_left、chain_right、move_w/a/s/d、confirm、back、menu、dpad_up/down/left/right、turn_left/right（转向需手柄） |
| task_start / task_pause / task_resume / task_stop | task 为 status 返回的任务 class；自动任务和手动接管互斥 |

所有画面坐标统一使用 1920×1080，自动映射 720P、1080P、1440P 和 4K 客户区。
输入时长范围 0.01～2 秒，每条指令执行后释放；不支持无限按住。
客户端默认读取最新 frame_id 和 hwnd。依据已查看的截图操作时，应显式提供该 frame_id 和 hwnd；3 秒以上旧图或窗口变化会拒绝输入。
指令返回 delivered 表示消息已送出；游戏是否接受必须检查随后截图。窗口消息不能保证所有 Unity 输入均被接受，可改用手柄后台。

示例：

```json
{"op":"action","action":"dodge","duration":0.08}
```

```json
{"op":"click","x":1525,"y":340,"duration":0.08,"frame_id":123,"hwnd":456}
```

```json
{"op":"analyze","roi":[700,280,1150,150],"ocr":true}
```

roi 使用起点和宽、高。

## HTTP 接口

全部请求需 `Authorization: Bearer <会话token>`。拒绝浏览器跨域请求，不提供任意代码执行入口。

GET `/status`、`/events?after=序号`、`/frame.png?id=截图编号`、`/preview.jpg`、`/jobs/指令编号`。
POST `/commands` 接受 JSON 指令，返回 202 和 job id；轮询 jobs 获取 done/error/cancelled。
POST `/release` 可立即中断当前输入并取消排队操作；POST `/cancel/指令编号` 取消指定操作。
输入队列最多 8 条，排队超过 5 秒作废；request_id 可防止重试时重复点击。
用户实际输入只在游戏为前台时采集，游戏外的键鼠不会进入事件日志。画面遮挡 UID；诊断接口不采集桌面和音频。
# 降低监视开销

连续监视或录制客户端请使用 `/frame.jpg`（1920×1080 JPEG），单次精确取样仍可用 `/frame.png`。
调试画面缓存最多每秒更新10次，并复用同一帧的编码；任务识别帧率独立设置，默认30帧。
设置中的“识别计算设置”可选择20～60帧；此限制不改变诊断录像的可选帧率。
1440P/4K任务画面使用OpenCL GPU缩放和颜色转换；实际后端与回退原因显示在实时状态 `image_processing` 中。
调试页隐藏或程序最小化时不生成界面预览；后台监控、事件记录和HTTP截图仍可用。
再次显示调试页时，下一次刷新会显示最新画面。截图编码复用已保存的1080P画面，仍独立遮挡UID，不修改历史帧。

`/threads` 返回线程名称、Windows 原生线程编号 `native_id` 和调用栈，方便与进程CPU采样对应；仍不返回局部变量。
`runtime.recognition_queue` 显示每类战斗检测的待完成任务和繁忙跳过次数，每类最多一项，避免慢识别积压旧画面。
状态也包含 `capture_ready`、`interaction_class` 与捕获健康信息；分析结果额外核对普通大世界及控制器画面尺寸。
Windows 10 2004及以上可尝试WGC，低于20348的系统保留捕获边框。全黑画面拒绝发布给任务和监控。
捕获失败不会自动改用其他截图器；当前窗口持续无有效画面时停止输入，并报告截图问题。

## 调试演练（stop_before）

`task_start` 可带 `stop_before`：节点名称列表，最多 20 项。任务运行到这些节点之前会停止整个应用、不执行该节点，用于把会消耗资源或不可撤销的功能（拆解、兑换、接取委托、消耗次数）走到入口前做检查。

```json
{"op":"task_start","task":"App_DriveDiscDismantle","stop_before":["快速选择"]}
```

停止时写入日志 `调试演练：已到达 … 之前，停止执行`，`/status` 的 `dry_run.hits` 记录已触发的节点；列表只在带 `stop_before` 的 `task_start` 设置，且必须提供节点名称。该开关默认关闭，不带 `stop_before` 的启动不受影响。
