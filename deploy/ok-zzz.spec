# -*- mode: python ; coding: utf-8 -*-
"""ok-zzz PyInstaller 打包配置。

构建: .venv/Scripts/pyinstaller --noconfirm deploy/ok-zzz.spec
产物: dist/ok-zzz/ok-zzz.exe（onedir，含运行时与全部资产）

说明：
- 任务类经字符串动态导入（ok-script init_class_by_name），因此整包收集
  src/onedragon/zzz_od 子模块为 hiddenimports。
- onnxocr（ok-script[ocr]）在运行期按名导入，同样需要 hiddenimports。
- assets/config/i18n/icons 作为数据文件随包分发；config 中仅带模板与
  战斗/路线配置，不带用户运行时实例目录。
"""
import os
import sys
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(SPEC)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)  # 让 collect_submodules('src') 可导入

_collected_src = collect_submodules('src')
print(f'[spec] collect_submodules(src) -> {len(_collected_src)} 个模块')
assert len(_collected_src) > 10, 'src 子模块收集失败'
hiddenimports = (
    _collected_src
    + collect_submodules('onedragon')
    + collect_submodules('zzz_od')
    + collect_submodules('onnxocr')
    + ['onnxocr.onnx_paddleocr', 'vgamepad', 'win32timezone']
)

# 应用配置：只带模板/路线/战斗配置，排除测试产生的运行时实例目录
config_datas = []
for root, dirs, files in os.walk(os.path.join(ROOT, 'config')):
    rel = os.path.relpath(root, ROOT)
    parts = rel.split(os.sep)
    # 排除运行时目录 config/{NN}/ 与运行时单文件
    if len(parts) >= 2 and parts[1].isdigit():
        dirs[:] = []
        continue
    runtime_files = {'one_dragon.yml', 'game.yml', 'battle_assistant.yml',
                     'model.yml', 'env.yml'}
    for f in files:
        if not f.endswith(('.yml', '.yaml')):
            continue
        if len(parts) == 1 and f in runtime_files:
            continue  # config 根目录的运行时用户配置
        config_datas.append((os.path.join(root, f), rel))

datas = [
    (os.path.join(ROOT, 'assets'), 'assets'),
    (os.path.join(ROOT, 'i18n'), 'i18n'),
    (os.path.join(ROOT, 'icons'), 'icons'),
    (os.path.join(ROOT, 'pyappify.yml'), '.'),
] + config_datas + collect_data_files('vgamepad') \
    + collect_data_files('onnxocr') \
    + collect_data_files('ok')

a = Analysis(
    [os.path.join(ROOT, 'main.py')],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'tests', 'tools', 'matplotlib', 'pytest'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ok-zzz',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # 保留控制台便于排障；稳定后可改 False
    icon=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='ok-zzz',
)
