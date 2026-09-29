# 第三方组件与许可声明 (THIRD-PARTY NOTICES)

本项目（ok-zzz，GPL-3.0）依赖或移植了以下开源项目，感谢这些项目的作者。

## 运行时依赖

| 组件 | 许可 | 用途 |
|---|---|---|
| [ok-script](https://github.com/ok-oldking/ok-script) | Apache-2.0 + Commons Clause 及附加条款 | 自动化框架：UI、截图（WGC/BitBlt）、输入、OCR、任务调度 |
| [PySide6](https://wiki.qt.io/Qt_for_Python) | LGPL-3.0 | 桌面界面 |
| [PyQt-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets) | GPL-3.0 | Fluent UI 组件（经 ok-script 引入） |
| [OpenCV](https://opencv.org/) / opencv-contrib-python | Apache-2.0 | 图像处理与模板匹配 |
| [onnxruntime-directml](https://github.com/microsoft/onnxruntime) | MIT | YOLO 推理（DirectML） |
| [onnxocr-ppocrv5](https://pypi.org/project/onnxocr-ppocrv5/) | Apache-2.0 | OCR（PaddleOCR ONNX 移植，经 ok-script[ocr]） |
| [vgamepad](https://github.com/yannickbreaud/vgamepad) | MIT | ViGEm 虚拟手柄（后台模式） |
| [soundcard](https://github.com/bastibe/SoundCard) / [librosa](https://github.com/librosa/librosa) / [scipy](https://scipy.org/) / [scikit-learn](https://scikit-learn.org/) | BSD-3-Clause | 闪避音频识别 |
| [NumPy](https://numpy.org/) / [PyYAML](https://pyyaml.org/) / [pynput](https://github.com/moses-palmer/pynput) 等经 ok-script 引入的依赖 | 各自许可 | 见对应项目页面 |

## 代码与资产移植来源

- **[ZenlessZoneZero-OneDragon（绝区零一条龙）](https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon)**（GPL-3.0）
  本项目移植了其以下部分并继续以 GPL-3.0 分发：
  - `src/onedragon/` ← 原仓库 `src/one_dragon/` 的子集（条件战斗引擎 `conditional_operation`、
    画面/模板识别层 `screen`/`matcher`、CV 流水线 `cv_process`、YOLO 推理封装、工具函数）
  - `src/zzz_od/` ← 原仓库 `src/zzz_od/` 的战斗引擎、代理人与目标状态识别、闪避音频识别、键位配置
  - `assets/` 与 `config/` ← 原仓库的画面定义 YAML、战斗 DSL 配置、模板图、闪避音频模板
  - 依据 GPL-3.0 第 5 条，本项目的整体许可为 **GPL-3.0**。

## ok-script 署名（依其许可证附加条款要求）

本项目使用了 [ok-script](https://github.com/ok-oldking/ok-script)（[ok-script.com](https://ok-script.com/)）。
ok-script 以 Apache-2.0 + Commons Clause 及附加条款许可：本项目不以 ok-script 为主体进行出售；
分发时保留其 LICENSE.txt 及本署名声明。依赖经 pip 安装，未内联（vendor）其源码。
