# -*- coding: utf-8 -*-
"""从 ZenlessZoneZero-OneDragon 本地克隆移植代码到 ok-zzz。

一次性的移植工具：按白名单复制文件、机械改写导入命名空间，
并写入 GPL 传承标注。改动需人工审查，勿盲跑覆盖手写文件。
"""
import os
import shutil
import sys

SRC_REPO = sys.argv[1] if len(sys.argv) > 1 else r"D:\Temp\ref\ZenlessZoneZero-OneDragon"
SRC = os.path.join(SRC_REPO, "src")
DST = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")

HEADER = (
    '# -*- coding: utf-8 -*-\n'
    '# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)\n'
    '# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon\n'
    '# 路径: {src_path}\n'
    '# 本文件随 ok-zzz 以 GPL-3.0 继续分发。\n'
)

# (源相对路径, 目标相对路径)
COPY_SET = []


def add_pkg(dst_pkg_root: str, src_pkg_root: str, files):
    for f in files:
        COPY_SET.append((f'{src_pkg_root}/{f}', f'{dst_pkg_root}/{f}'))


# one_dragon → onedragon（保持子包布局）
od = 'one_dragon'
add_pkg('onedragon', od, ['base/conditional_operation/atomic_op.py',
                          'base/conditional_operation/execution_info.py',
                          'base/conditional_operation/loader.py',
                          'base/conditional_operation/operation_def.py',
                          'base/conditional_operation/operation_executor.py',
                          'base/conditional_operation/operator.py',
                          'base/conditional_operation/scene.py',
                          'base/conditional_operation/state_cal_tree.py',
                          'base/conditional_operation/state_handler.py',
                          'base/conditional_operation/state_record_service.py',
                          'base/conditional_operation/state_recorder.py',
                          'base/screen/screen_area.py',
                          'base/screen/screen_info.py',
                          'base/screen/screen_loader.py',
                          'base/screen/screen_utils.py',
                          'base/screen/screen_match.py',
                          'base/screen/template_info.py',
                          'base/screen/template_loader.py',
                          'base/matcher/template_matcher.py',
                          'base/matcher/match_result.py',
                          'base/matcher/ocr/ocr_matcher.py',
                          'base/matcher/ocr/ocr_match_result.py',
                          'base/matcher/ocr/ocr_service.py',
                          'base/matcher/ocr/ocr_utils.py',
                          'base/geometry/point.py',
                          'base/geometry/rectangle.py',
                          'base/debug/debug_trace_bus.py',
                          'base/operation/context_notify_event.py',
                          'base/config/config_item.py',
                          'thread/atomic_bool.py',
                          'thread/atomic_int.py',
                          'utils/thread_utils.py',
                          'utils/log_utils.py',
                          'utils/os_utils.py',
                          'utils/yaml_utils.py',
                          'utils/str_utils.py',
                          'utils/cal_utils.py',
                          'utils/cv2_utils.py',
                          'utils/gpu_executor.py',
                          'utils/i18_utils.py',
                          'utils/yolo_config_utils.py',
                          'yolo/yolov8_onnx_det.py',
                          'yolo/yolov8_onnx_cls.py',
                          'yolo/onnx_model_loader.py',
                          'yolo/onnx_utils.py',
                          'yolo/detect_utils.py',
                          ])

# cv_process 全量
cv_dir = os.path.join(SRC, od, 'base/cv_process')
for root, _dirs, files in os.walk(cv_dir):
    for f in files:
        if f.endswith('.py'):
            rel = os.path.relpath(os.path.join(root, f), os.path.join(SRC, od)).replace('\\', '/')
            COPY_SET.append((f'{od}/{rel}', f'onedragon/{rel}'))

# zzz_od → zzz_od（包名不变，只改 one_dragon 导入）
add_pkg('zzz_od', 'zzz_od', ['auto_battle/auto_battle_context.py',
                             'auto_battle/auto_battle_operator.py',
                             'auto_battle/auto_battle_agent_context.py',
                             'auto_battle/auto_battle_target_context.py',
                             'auto_battle/auto_battle_dodge_context.py',
                             'auto_battle/auto_battle_custom_context.py',
                             'auto_battle/auto_battle_state.py',
                             'auto_battle/auto_battle_state_record_service.py',
                             'auto_battle/auto_battle_utils.py',
                             'auto_battle/atomic_op/atomic_op_factory.py',
                             'game_data/agent.py',
                             'game_data/target_state.py',
                             'yolo/flash_classifier.py',
                             'const/game_const.py',
                             ])

# auto_battle 剩余子目录（agent_state / target_state / atomic_op 其余文件）
for sub in ('agent_state', 'target_state', 'atomic_op'):
    d = os.path.join(SRC, 'zzz_od/auto_battle', sub)
    if os.path.isdir(d):
        for f in os.listdir(d):
            if f.endswith('.py') and f != '__init__.py':
                COPY_SET.append((f'zzz_od/auto_battle/{sub}/{f}', f'zzz_od/auto_battle/{sub}/{f}'))


def rewrite(content: str) -> str:
    content = content.replace('from one_dragon.', 'from onedragon.')
    content = content.replace('import one_dragon.', 'import onedragon.')
    content = content.replace('from one_dragon ', 'from onedragon ')
    return content


def main():
    # __init__.py 骨架
    for pkg in ['onedragon', 'onedragon/base', 'onedragon/base/conditional_operation',
                'onedragon/base/screen', 'onedragon/base/matcher', 'onedragon/base/matcher/ocr',
                'onedragon/base/geometry', 'onedragon/base/debug', 'onedragon/base/operation',
                'onedragon/base/cv_process', 'onedragon/base/cv_process/steps',
                'onedragon/base/config', 'onedragon/thread', 'onedragon/utils', 'onedragon/yolo',
                'zzz_od', 'zzz_od/auto_battle', 'zzz_od/atomic_op', 'zzz_od/game_data',
                'zzz_od/yolo', 'zzz_od/const']:
        d = os.path.join(DST, pkg.replace('/', os.sep))
        os.makedirs(d, exist_ok=True)
        init = os.path.join(d, '__init__.py')
        if not os.path.exists(init):
            with open(init, 'w', encoding='utf-8') as fp:
                fp.write('')

    copied, skipped = 0, 0
    for src_rel, dst_rel in COPY_SET:
        s = os.path.join(SRC, src_rel.replace('/', os.sep))
        if not os.path.exists(s):
            print(f'[缺失] {src_rel}')
            skipped += 1
            continue
        d = os.path.join(DST, dst_rel.replace('/', os.sep))
        os.makedirs(os.path.dirname(d), exist_ok=True)
        with open(s, 'r', encoding='utf-8') as fp:
            content = fp.read()
        # step_template_matching 的惰性 GUI 导入直接废弃
        content = content.replace(
            'from one_dragon_qt.logic.image_analysis_logic import ImageAnalysisLogic',
            'raise NotImplementedError("ok-zzz 未移植图像分析 GUI 逻辑")'
        )
        content = rewrite(content)
        with open(d, 'w', encoding='utf-8', newline='\n') as fp:
            fp.write(HEADER.format(src_path=src_rel) + content)
        copied += 1
    print(f'复制 {copied} 个文件，缺失 {skipped} 个')


if __name__ == '__main__':
    main()
