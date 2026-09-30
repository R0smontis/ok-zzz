# -*- coding: utf-8 -*-
"""全功能移植脚本（v2，闭合驱动）。

以 zzz_od/application 与共享操作层为入口计算一条龙源码导入闭包，
按排除清单过滤后整包复制到 ok-zzz（one_dragon→onedragon 改名），
并应用逐文件补丁（剥 Qt、去 envs/launcher、stub 通知等）。
幂等：重复运行覆盖旧文件（手写文件不在此列）。
"""
import ast
import os
import sys

SRC_REPO = r"D:\Temp\ref\ZenlessZoneZero-OneDragon"
SRC = os.path.join(SRC_REPO, 'src')
DST = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src')

HEADER = (
    '# -*- coding: utf-8 -*-\n'
    '# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)\n'
    '# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon\n'
    '# 路径: {src_path}\n'
    '# 本文件随 ok-zzz 以 GPL-3.0 继续分发。\n'
)

# 排除前缀：不移植（GUI 由 ok-script 承载；遥测丢弃；envs/launcher 由 ok-script 交付模式替代）
EXCLUDE_PREFIXES = (
    'zzz_od/gui/',
    'zzz_od/telemetry/',
    'zzz_od/backend/',
    'zzz_od/win_exe/',
    'zzz_od/context/',                          # 保留 ok-zzz 手写 ZContext
    'zzz_od/application/one_dragon_app/',       # 队列重建（ok-zzz 自写）
    'zzz_od/application/zzz_application_launcher.py',  # ok-zzz CLI 自写
    'one_dragon/envs/git_service.py',   # envs 服务层不移植（交付由 ok-script 承担）
    'one_dragon/envs/python_service.py',
    'one_dragon/envs/download_service.py',
    'one_dragon/envs/update_service.py',
    'one_dragon/envs/ghproxy_service.py',
    'one_dragon/launcher/',
    'one_dragon_qt/',   # P11 单独移植 overlay
    'onnxocr/',         # OCR 走 ok-script[ocr]
    'one_dragon/base/operation/application/application_run_context.py',  # 自建精简版
    'one_dragon/base/operation/application/application_group_manager.py',  # 并入自建 RunContext
    'one_dragon/base/operation/one_dragon_context.py',   # ok-zzz ZContext 替代
    'one_dragon/base/operation/one_dragon_env_context.py',
    'one_dragon/base/operation/one_dragon_app.py',      # 队列重建
    'one_dragon/base/operation/application/group_application.py',
    'one_dragon/base/operation/operation_notify.py',    # 通知点 P11；用 stub
)

APP_SETTING_SUFFIX = '_app_setting.py'

# 入口：应用层 + 共享操作层（闭包自动带出 operation/config/controller 依赖）
ENTRY_DIRS = ['zzz_od/application', 'zzz_od/operation']


def module_to_path(mod):
    base = os.path.join(SRC, mod.replace('.', os.sep))
    if os.path.exists(base + '.py'):
        return base + '.py'
    if os.path.isdir(base):
        return os.path.join(base, '__init__.py')
    return None


def parse_imports(path):
    tree = ast.parse(open(path, encoding='utf-8').read())
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                mods.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                rel = os.path.relpath(path, SRC).replace('\\', '/')
                pkg = '.'.join(rel.split('/')[:-1])
                if node.module:
                    mods.add((pkg + '.' if pkg else '') + node.module)
            elif node.module:
                mods.add(node.module)
                for a in node.names:
                    cand = node.module + '.' + a.name
                    if module_to_path(cand):
                        mods.add(cand)
    return mods


def collect_files():
    visited, queue, missing = set(), [], set()
    for entry_dir in ENTRY_DIRS:
        root = os.path.join(SRC, entry_dir.replace('/', os.sep))
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                if f.endswith('.py'):
                    rel = os.path.relpath(os.path.join(dirpath, f), SRC).replace('\\', '/')
                    queue.append(rel[:-3].replace('/', '.'))
    # 补充入口：框架配置/控制器/系统配置层
    queue += [
        'one_dragon.base.operation.operation',
        'one_dragon.base.operation.operation_base',
        'one_dragon.base.operation.operation_node',
        'one_dragon.base.operation.operation_edge',
        'one_dragon.base.operation.operation_round_result',
        'one_dragon.base.operation.application_base',
        'one_dragon.base.operation.application_run_record',
        'one_dragon.base.operation.application.application_config',
        'one_dragon.base.operation.application.application_group_config',
        'one_dragon.base.operation.application.application_factory',
        'one_dragon.base.operation.one_dragon_finalizer',
        'one_dragon.base.config.yaml_config',
        'one_dragon.base.config.one_dragon_config',
        'one_dragon.base.config.game_account_config',
        'one_dragon.base.config.notify_config',
        'one_dragon.base.config.custom_config',
        'one_dragon.base.config.standalone_app_config',
        'one_dragon.base.config.basic_game_config',
        'one_dragon.base.controller.controller_base',
        'one_dragon.base.controller.pc_controller_base',
        'one_dragon.base.controller.pc_game_window',
        'one_dragon.base.controller.pc_clipboard',
        'zzz_od.config.team_config',
        'zzz_od.game_data.compendium',
        'zzz_od.game_data.map_area',
        'zzz_od.screen_area.screen_normal_world',
        'zzz_od.yolo.hollow_event_detector',
        'one_dragon.envs.repo_config',
        'one_dragon.base.config.basic_model_config',
        'one_dragon.base.web.common_downloader',
        'one_dragon.base.web.zip_downloader',
    ]
    # 定向移植：overlay 悬浮窗包及其专用 widgets（one_dragon_qt 下自包含子集）
    overlay_deps = ['one_dragon_qt/widgets/overlay_text_widget.py']
    for rel in overlay_deps:
        queue.append(rel[:-3].replace('/', '.'))
    overlay_root = os.path.join(SRC, 'one_dragon_qt', 'overlay')
    for dirpath, _dirs, files in os.walk(overlay_root):
        for f in files:
            if f.endswith('.py'):
                rel = os.path.relpath(os.path.join(dirpath, f), SRC).replace(os.sep, '/')
                queue.append(rel[:-3].replace('/', '.'))
    while queue:
        mod = queue.pop()
        if mod in visited:
            continue
        visited.add(mod)
        p = module_to_path(mod)
        if p is None:
            if mod.split('.')[0] in ('one_dragon', 'zzz_od'):
                missing.add(mod)
            continue
        for m in parse_imports(p):
            if m not in visited:
                queue.append(m)
    files = sorted(m for m in visited if module_to_path(m))
    return files, missing


def to_dst_rel(rel):
    if rel.startswith('one_dragon_qt/widgets/'):
        return 'onedragon/qt/widgets/' + rel[len('one_dragon_qt/widgets/'):]
    if rel.startswith('one_dragon_qt/overlay/'):
        return 'onedragon/qt/overlay/' + rel[len('one_dragon_qt/overlay/'):]
    if rel.startswith('one_dragon/'):
        return 'onedragon/' + rel[len('one_dragon/'):]
    return rel


def excluded(rel):
    if rel.startswith('one_dragon_qt/overlay/') or rel.startswith('one_dragon_qt/widgets/'):
        return False  # 定向移植豁免
    if any(rel.startswith(p) or rel == p.rstrip('/') for p in EXCLUDE_PREFIXES):
        return True
    if os.path.basename(rel).endswith(APP_SETTING_SUFFIX):
        return True  # 原版 Qt 设置页，由 ok-script 选项桥替代
    return False


# ---------------- 逐文件内容补丁 ----------------

QT_ADAPTER_IMPORT = 'from one_dragon_qt.widgets.setting_card.yaml_config_adapter import YamlConfigAdapter'
ADAPTER_COMPAT = 'from onedragon.base.config.yaml_config_adapter import YamlConfigAdapter'

PATCHES = {
    # yaml_config: get_prop_adapter 内的惰性 Qt 导入 → 兼容 shim
    'one_dragon/base/config/yaml_config.py': [
        ("from one_dragon_qt.widgets.setting_card.yaml_config_adapter import (\n            YamlConfigAdapter,\n        )",
         ADAPTER_COMPAT),
    ],
    # basic_game_config: 顶层 Qt 适配器导入
    'one_dragon/base/config/basic_game_config.py': [
        (QT_ADAPTER_IMPORT, ADAPTER_COMPAT),
    ],
    # 应用配置类里的适配器导入
    'zzz_od/application/hollow_zero/withered_domain/withered_domain_config.py': [
        (QT_ADAPTER_IMPORT, ADAPTER_COMPAT),
    ],
    'zzz_od/application/life_on_line/life_on_line_config.py': [
        (QT_ADAPTER_IMPORT, ADAPTER_COMPAT),
    ],
    # 键盘事件枚举来自被排除的 one_dragon_context → compat 模块
    'zzz_od/application/commission_assistant/commission_assistant_app.py': [
        ('from one_dragon.base.operation.one_dragon_context import ContextKeyboardEventEnum',
         'from onedragon.base.operation.context_keyboard_event import ContextKeyboardEventEnum'),
    ],
    'zzz_od/application/devtools/screenshot_helper/screenshot_helper_app.py': [
        ('from one_dragon.base.operation.one_dragon_context import ContextKeyboardEventEnum',
         'from onedragon.base.operation.context_keyboard_event import ContextKeyboardEventEnum'),
    ],
    # CV 模板匹配步骤里的 GUI 工具惰性导入
    'one_dragon/base/cv_process/steps/step_template_matching.py': [
        ('from one_dragon_qt.logic.image_analysis_logic import ImageAnalysisLogic',
         'raise NotImplementedError("ok-zzz 未移植图像分析 GUI 逻辑")'),
    ],
    # cv_service 只需要类型引用；剥掉对总上下文的运行时导入
    'one_dragon/base/cv_process/cv_service.py': [
        ('from one_dragon.base.operation.one_dragon_context import OneDragonContext',
         '''from typing import TYPE_CHECKING as _TC, Any as _Any

if _TC:
    OneDragonContext = _Any  # ok-zzz: 鸭子类型，不引入总上下文'''),
        ('def __init__(self, od_ctx: OneDragonContext):',
         "def __init__(self, od_ctx: 'OneDragonContext'):"),
    ],
    # factory_manager 只需要类型引用；剥掉对总上下文/应用插件的运行时导入
    'one_dragon/base/operation/application_factory_manager.py': [
        ('from one_dragon.base.operation.one_dragon_context import OneDragonContext',
         '''from typing import TYPE_CHECKING as _TC, Any as _Any

if _TC:
    OneDragonContext = _Any  # ok-zzz: 鸭子类型'''),
    ],
    # basic_model_config 的 OCR 下载元数据改走 compat（不引入 onnx_ocr_matcher）
    'one_dragon/base/config/basic_model_config.py': [
        ("""from one_dragon.base.matcher.ocr.onnx_ocr_matcher import (
    DEFAULT_OCR_MODEL_NAME,
    PPOCRV6_MODEL_NAME,
    get_final_file_list,
    get_ocr_download_urls,
    get_ocr_model_dir,
)""",
         """from onedragon.base.matcher.ocr.ocr_model_info import (
    DEFAULT_OCR_MODEL_NAME,
    PPOCRV6_MODEL_NAME,
    get_final_file_list,
    get_ocr_download_urls,
    get_ocr_model_dir,
)"""),
    ],
}


def apply_patches(rel, content):
    if rel.startswith('one_dragon_qt/overlay/'):
        content = content.replace('from one_dragon_qt.overlay.',
                                  'from onedragon.qt.overlay.')
        content = content.replace('from one_dragon_qt.',
                                  'from onedragon.qt.')
    for old, new in PATCHES.get(rel, []):
        if old in content:
            content = content.replace(old, new)
        else:
            print(f'  [补丁未命中] {rel}: {old[:60]}...')
    content = content.replace('from one_dragon.', 'from onedragon.')
    content = content.replace('import one_dragon.', 'import onedragon.')
    content = content.replace('from one_dragon ', 'from onedragon ')
    return content


# 特殊处理：zzz_od 的控制器入口
ZPC_ENTRY = ('zzz_od/application/zzz_pc_controller.py',
             'zzz_od/controller/zzz_pc_controller.py')


def main():
    files, missing = collect_files()
    print(f'闭包文件 {len(files)}，引用缺失 {len(missing)}')
    for m in sorted(missing):
        print('  [missing]', m)

    # __init__.py 骨架
    copied = 0
    for mod in files:
        f = module_to_path(mod)
        rel = os.path.relpath(f, SRC).replace('\\', '/')
        if excluded(rel):
            continue
        dst_rel = to_dst_rel(rel)
        dst = os.path.join(DST, dst_rel.replace('/', os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        content = open(f, encoding='utf-8').read()
        content = apply_patches(rel, content)
        with open(dst, 'w', encoding='utf-8', newline='\n') as fp:
            fp.write(HEADER.format(src_path=rel) + content)
        copied += 1


    print(f'复制 {copied} 个文件')


if __name__ == '__main__':
    main()
