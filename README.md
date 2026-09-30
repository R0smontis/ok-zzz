# ok-zzz

绝区零（Zenless Zone Zero）PC 客户端自动化助手，基于 [ok-script](https://github.com/ok-oldking/ok-script)（[ok-script.com](https://ok-script.com/)）框架重写，游戏逻辑移植自 [ZenlessZoneZero-OneDragon（绝区零一条龙）](https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon)。

> ⚠️ **免责声明**：本项目仅供学习交流使用。使用第三方自动化工具存在违反游戏用户协议、导致账号封禁的风险，请自行承担使用风险。开发者团队不为使用本软件产生的任何问题负责。

## 当前进度（全功能移植完成，待实机验证）

✅ 已完成（离线可验证，24 项测试通过）：
- **应用框架**：Operation 节点图执行器（round 重试/边跳转/暂停停止语义）、
  精简版应用运行上下文（注册表/分组/运行记录/通知池）、多账号实例、
  第三方插件目录（plugins/）
- **全部 27+ 应用**：一条龙队列、体力计划、恶名狩猎、式舆防卫战、枯萎之都、
  迷失之地、勘域巡逻、随便观、情报板、录像店、咖啡店、真拿命验收、
  委托助手（自动对话/剧情/钓鱼）、战斗助手+闪避助手、驱动盘拆解、
  兑换码、每日签到、邮件、活跃度、丽都城募、丽都周纪、通知推送、
  灵敏度/编队校准、开发工具
- **细则选项桥**：18 个应用的全部配置选项自动内省生成 ok-script 控件
  （枚举→下拉、清单→JSON 文本域），写回一条龙格式 YAML，配置互通
- **战斗引擎**：条件 DSL、8 套配置、代理人/目标状态识别、音频+闪光闪避
- **控制器**：原版全栈（BitBlt/PrintWindow 截图、键鼠、ViGEm 虚拟手柄后台）
- **边缘设施**：24 渠道推送、游戏内 Overlay 悬浮窗（热键 o）、AutoHDR、插件系统
- **全量资产**：模板 1877 张、画面 YAML、38 空洞事件、路线 21 条、语料

⏳ 待实机验证（需要安装《绝区零》的 Windows 环境）：
- 窗口识别/截图/输入链路（`ZenlessZoneZero.exe` / `UnityWndClass`）
- 每个应用的实际运行（诊断任务 → 简单日常 → 战斗类 → 空洞/锄大地）
- Overlay 与 ok-script 窗口联动
- 体力计划清单编辑器等复杂交互目前走 JSON 文本域，可在使用中迭代为专用 Tab

🗺️ 后续：PyAppify 打包 CI（pyappify.yml 已就位，需建更新仓库）、
复杂清单编辑 Tab、共享配队客户端（可选）

## 环境要求

- Windows 10 21H2 64 位及以上
- Python 3.12
- 《绝区零》PC 客户端，16:9 分辨率（最低 1280x720）
- 后台模式需安装 [ViGEm Bus 驱动](https://github.com/nefarius/ViGEmBus/releases)

## 快速开始

```powershell
# 1. 创建虚拟环境（uv 或 venv）
uv venv --python 3.12 .venv
.venv\Scripts\activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 下载识别模型（YOLO 闪光分类器，约几十 MB）
python tools\download_models.py

# 4. 运行（需要游戏窗口；调试模式会在画面上绘制识别框）
python main.py        # 正常运行
python main_debug.py  # 调试模式
```

首次启动后：
1. 在 ok-script 界面选择游戏窗口（自动检测 `ZenlessZoneZero.exe`）
2. 运行「诊断」任务确认截图/OCR/输入链路
3. 勾选「⚔️ 自动战斗」触发器，进入战斗即可由引擎接管

## 资产与代码来源说明

- `tools/fetch_onedragon_assets.py` 可从一条龙仓库（本地克隆或 GitHub raw）拉取/更新
  画面定义、战斗配置与模板资产
- 代码与资产的移植范围及各项目许可详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)

## 开发

```powershell
pip install -r requirements.txt
python -m pytest tests/ -q     # 离线测试（无需游戏）
```

目录结构：

```
src/
  config.py            # ok-script 应用配置
  globals.py           # my_app 全局单例（桥接 ok-script 运行时）
  tasks/               # ok-script 任务（自动战斗触发器、战斗演示、诊断）
  zzz_od/              # 游戏逻辑（移植自一条龙）
    context/           #   ZContext 总装配
    auto_battle/       #   战斗引擎（DSL 场景/原子操作/闪避）
    controller/        #   控制器（键鼠 + 虚拟手柄）
    config/            #   键位/模型/战斗助手配置
  onedragon/           # 一条龙框架层子集（画面/模板/CV/条件引擎）
assets/  config/       # 画面 YAML、模板图、战斗 DSL 配置（沿一条龙布局）
tools/                 # 资产拉取 / 模型下载 / 代码移植脚本
```

## 许可

本项目以 [GPL-3.0](LICENSE) 分发（因移植了一条龙的 GPL 代码与资产）。
依赖项目的许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)；
使用 ok-script 需保留其署名（见上文链接），且不得将其转售。
