# 实时调试与游戏控制

实时调试接口用于在「不抢前台、不移动物理鼠标」的前提下观察游戏实时画面、识别状态、线程栈，或通过本机脚本接管手柄/窗口消息并执行节点演练。

## 开启与关闭监控

实时调试默认关闭，先在「截图方式」页面选好游戏窗口后，可通过三种方式开启同一套只读监控（无需按 F9，也无需启动诊断录制）：

1. **界面手动开启**：在「调试 → 实时调试与控制」点击「开始监控」。
2. **启动参数或环境变量**：`python main.py --live-debug`，或设置环境变量 `OK_ZZZ_LIVE_DEBUG=1` 后启动。
3. **运行中按需唤醒（供本机脚本 / Agent）**：

   ```powershell
   python tools/live_debug.py --root <运行目录> enable
   ```

   客户端在运行目录写入 `debug/live/request`，主程序每 0.5 秒轮询一次，删除该文件并开启监控；客户端等待会话就绪后输出接口地址（默认超时 15 秒，可用 `--timeout` 调整；已开启时直接返回现有会话）。

**控制生命周期与安全边界**：

- **接管与释放**：点击界面「接管控制」或发送 `acquire` 指令会先停止当前自动任务，默认接入虚拟 Xbox 手柄后台；点击「释放控制」或发送 `release` 立即松开按键并还原账号原本的控制器与键位映射，自动任务保持停止，需重新启动。
- **自动释放条件**：接管后超过 **60 秒**未发送操作或 `heartbeat`、切换游戏窗口、窗口最小化或分辨率变化时，自动释放控制与按键。
- **停止监控**：点击「停止监控」会一并关闭 HTTP 接口、输入监听和调试控制；此后需重新请求才会再次开启。实时监控仅保留最近 **600 条**事件，长期归档请使用「画面与日志诊断」录制或 `bundle` 导出。

---

## 运行目录与本机客户端

接口每次启动分配随机端口，仅监听 `127.0.0.1`。地址与随机 Bearer Token 保存在运行目录的 `debug/live/session.json`（程序退出时自动删除；**切勿将 `session.json` 打包进公开问题附件**）：

| 运行形态 | `<运行目录>` 路径 |
| --- | --- |
| 源码直接运行 | 项目根目录（如 `D:\ok-zzz-dev`） |
| PyAppify 在线更新安装版 | `<安装目录>\data\apps\ok-zzz\working`（如 `D:\ok-zzz\data\apps\ok-zzz\working`） |
| 旧独立冻结版（0.1.x / PyInstaller） | `%LOCALAPPDATA%\ok-zzz` |

安装包不附带源码树的 `tools/` 目录；在源码环境运行 `tools/live_debug.py`（或 `python main.py --live-client`），把 `--root` 指向目标实例的 `<运行目录>` 即可连接：

```powershell
# 查看实时状态、抓取单帧 PNG、读取事件流、导出完整现场包
python tools/live_debug.py --root D:\ok-zzz\data\apps\ok-zzz\working status
python tools/live_debug.py --root D:\ok-zzz\data\apps\ok-zzz\working frame D:\Temp\live-frame.png
python tools/live_debug.py --root D:\ok-zzz\data\apps\ok-zzz\working events
python tools/live_debug.py --root D:\ok-zzz\data\apps\ok-zzz\working bundle D:\Temp\live-bundle
```

向 `command` 子命令传 JSON 时，建议写入文件后用 `@文件路径` 传入，避免 PowerShell 引号转义问题：

```json
{"op": "acquire", "mode": "gamepad"}
```

```powershell
python tools/live_debug.py --root D:\ok-zzz\data\apps\ok-zzz\working command @D:\Temp\command.json
```

---

## 指令参考（`command` / `POST /commands`）

| `op` | 参数与说明 |
| --- | --- |
| `acquire` | `mode` 默认为 `"gamepad"`（虚拟 Xbox 手柄），可选 `"messages"`（后台窗口消息）；停止自动任务并获取 60 秒控制租约 |
| `release` | 立即释放控制租约与所有按键 |
| `heartbeat` | 续期控制租约 60 秒 |
| `analyze` | 对当前截图执行攻击按钮、敌人血条、方向箭头、连携条与大世界状态检测；`ocr` 默认 `true`；`roi` 为 `[x, y, width, height]` |
| `click` | `x`、`y`、`button`（`left` / `right` / `middle`）、`duration` |
| `drag` | `x`、`y`、`end_x`、`end_y`、`duration` |
| `scroll` | `x`、`y`、`amount`（正数向下，范围 `-10`～`10`） |
| `key` | `key`（如 `w`、`space`、`esc`、`mouse_left`）、`duration` |
| `action` | 预定义动作：`normal_attack`、`special_attack`、`ultimate`、`dodge`、`switch_next`、`switch_prev`、`chain_left`、`chain_right`、`move_w/a/s/d`、`confirm`、`back`、`menu`、`dpad_up/down/left/right`、`turn_left/right`（转向需手柄） |
| `action`（组合键） | 手柄后台下用 `pad_lt+b` 形式同时按住 2～3 个手柄键（支持 `lt`、`rt`、`lb`、`rb`、`a`、`b`、`x`、`y`、`start`、`back`、`l_thumb`、`r_thumb`） |
| `task_start` / `task_pause` / `task_resume` / `task_stop` | `task` 为 `/status` 返回的任务类名；`task_start` 可选附 `app`（一条龙子应用 ID）与 `stop_before`（节点名前置停止列表，见下节）；启动前若处于手动接管会自动释放接管 |

### 坐标、时效与送达语义

- **统一逻辑坐标**：所有 `x`、`y` 与 `roi`（起点 `x, y` 加宽高 `width, height`）均采用 `1920×1080` 逻辑坐标系，服务端自动映射到 720P、1080P、1440P 或 4K 真实客户区。
- **按住时长**：`duration` 范围 `0.01`～`2` 秒，每条指令执行完毕后自动松开，不支持无限长按。
- **帧与句柄防过期**：CLI 默认补齐最新 `frame_id` 与 `hwnd`；若基于某张已查看截图下发点击或按键，应显式传入对应的 `frame_id` 与 `hwnd`——画面超过 **3 秒**或窗口句柄变化会直接拒绝执行。
- **送达不等于生效**：返回 `delivered: true` 仅代表输入事件已发出，游戏是否实际响应必须根据后续新截图核验（Unity 界面可能忽略部分后台窗口消息，此时应改用 `gamepad` 模式）。

常用 JSON 示例：

```json
{"op": "action", "action": "dodge", "duration": 0.08}
```

```json
{"op": "click", "x": 1525, "y": 340, "duration": 0.08, "frame_id": 123, "hwnd": 456}
```

```json
{"op": "analyze", "roi": [700, 280, 1150, 150], "ocr": true}
```

---

## 调试演练（`stop_before`）

`task_start` 支持传入节点名列表 `stop_before`（最多 20 项）。当操作流即将进入任一目标节点前，立即停止整个应用且**不执行该节点**，适合在不消耗电量、不拆解装备、不接取委托的前提下验证前置导航与编队流程：

```json
{"op": "task_start", "task": "App_DriveDiscDismantle", "stop_before": ["快速选择"]}
```

- 命中时写入日志 `调试演练：已到达 … 之前，停止执行`，并在 `/status` 的 `dry_run.hits` 记录命中的节点名。
- `stop_before` 仅对本次 `task_start` 运行生效，运行结束（含未命中、失败或手动停止）后立即清空，不影响后续界面或热键启动的任务；`dry_run.hits` 保留至下一次 `task_start`。

---

## HTTP 接口与监视开销

所有请求须携带请求头 `Authorization: Bearer <会话token>` 且 `Host` 匹配本机回环地址；服务端拒绝含 `Origin` 或跨站 `Sec-Fetch-Site` 的浏览器请求，请求体上限 8192 字节，不提供任何任意代码执行入口。

### 端点一览

| 方法与路径 | 说明 |
| --- | --- |
| `GET /status` | 返回监控状态、选中窗口与 `capture_ready`、`interaction_class`、任务列表、`runtime.recognition_queue`（各类识别待完成与繁忙跳过数）、`image_processing` 后端及 `dry_run.hits` |
| `GET /threads` | 返回所有线程名称、Windows 原生线程号 `native_id` 与当前调用栈（不含局部变量），便于对照进程 CPU 采样 |
| `GET /events?after=<序号>` | 增量拉取运行日志、指令结果与游戏前台物理输入事件（游戏外键鼠不采集） |
| `GET /frame.jpg?id=<编号>` | 1920×1080 JPEG 截图（已遮挡 UID，响应头带 `X-Frame-Id`），适合连续监视 |
| `GET /frame.png?id=<编号>` | 1920×1080 无损 PNG 截图（已遮挡 UID），适合单次精确取样或回归夹具采集 |
| `GET /preview.jpg` | 界面预览规格 JPEG |
| `POST /commands` | 提交异步指令（最多排队 8 条，排队超 5 秒作废；支持 `request_id` 幂等防重），返回 `202` 与 job 信息 |
| `GET /jobs/<指令编号>` | 查询指令执行状态（`queued` / `running` / `done` / `error` / `cancelled`） |
| `POST /cancel/<指令编号>` | 取消指定排队或运行中的指令 |
| `POST /release` | 紧急释放当前输入、清空控制租约并取消排队指令 |

### 降低监视开销与异常保护

- 连续轮询画面请使用 `/frame.jpg`：调试截图缓存每秒最多更新 10 次并复用同一帧编码，不会拖慢默认 30 FPS 的任务识别循环。
- 调试页隐藏或主窗口最小化时跳过界面预览渲染，后台监控、事件流和 HTTP 截图照常可用；切回调试页后自动恢复显示最新帧。
- 全黑画面与 15 秒未变化的冻结画面均拒绝发布给任务和实时监控；当前窗口持续无有效画面时自动停止输入并报告捕获异常。
