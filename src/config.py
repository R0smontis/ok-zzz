# -*- coding: utf-8 -*-
"""ok-zzz 应用配置（ok-script config 字典）。"""
from ok import ConfigOption
from src.controls.interaction import INTERACTIONS
from src.controls.hotkey_settings import validate_hotkey
from src.runtime.inference import recognition_config
from src.controls.application_input import task_input_config

version = "0.1.0"

gui_config = {
    'type': 'qt',
    'window_size': {
        'width': 1200,
        'height': 800,
        'min_width': 600,
        'min_height': 450,
    },
}

# 全局配置：游戏键位（与一条龙 GameConfig 默认键位一致，可在界面修改）
key_config_option = ConfigOption('Game Hotkey Config', {
    'Dodge Key': 'shift',
    'Normal Attack Key': 'mouse_left',
    'Special Attack Key': 'e',
    'Ultimate Key': 'q',
    'Switch Agent Key': 'space',
}, description='游戏内键鼠战斗按键，修改后在下次任务启动时生效；手柄键位在 config/00/game.yml 调整',
   validator=validate_hotkey)

# ok-script 截图后遮挡 UID，避免识别模型把 UID 当目标
def make_uid_black(frame):
    """遮挡右下角 UID 区域（坐标对齐一条龙 ScreenNormalWorldEnum.UID）。"""
    try:
        height, width = frame.shape[:2]
        x1, y1, x2, y2 = 1814, 1059, 1919, 1079
        sy = int(y1 / 1080 * height)
        ey = int(y2 / 1080 * height)
        sx = int(x1 / 1920 * width)
        ex = int(x2 / 1920 * width)
        frame[sy:ey, sx:ex] = 0
        return frame
    except Exception:
        return frame


config = {
    'debug': False,
    'gui': gui_config,
    'config_folder': 'configs',
    'global_configs': [key_config_option, recognition_config, task_input_config],
    'screenshot_processor': make_uid_black,
    'gui_icon': 'icons/icon.png',
    'wait_until_before_delay': 0,
    'wait_until_check_delay': 0,
    'wait_until_settle_time': 0,
    'ocr': {
        'lib': 'onnxocr',
        'auto_simplify': True,
        'params': {
            'use_openvino': False,
        }
    },
    'windows': {
        # 绝区零 PC 客户端：进程名与窗口类（P1 实机校准项，可在 configs 覆盖）
        'exe': ['ZenlessZoneZero.exe'],
        'hwnd_class': 'UnityWndClass',
        # 选择只决定 ZzzController 的输入模式；列表首项也是旧选项（已移除的
        # ForegroundPostMessage/PyDirect，行为与前台键鼠相同）的回退目标。
        'interaction': INTERACTIONS,
        'capture_method': ['WGC', 'BitBlt_RenderFull', 'BitBlt'],
        'check_hdr': False,
        'force_no_hdr': False,
        'require_bg': True,
    },
    'start_timeout': 120,
    'supported_resolution': {
        'ratio': '16:9',
        'min_size': (1280, 720),
        'resize_to': [(2560, 1440), (1920, 1080), (1600, 900), (1280, 720), (3840, 2160)],
    },
    'links': {
        'default': {
            'github': 'https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon',
            'ok-script': 'https://github.com/ok-oldking/ok-script',
            'faq': 'https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon/issues',
        }
    },
    'screenshots_folder': 'screenshots',
    'gui_title': 'ok-zzz',
    'version': version,
    'my_app': ['src.globals', 'Globals'],
    'custom_tabs': [['src.tasks.debug_tab', 'DebugToolsTab']],
    # 触发器任务（常驻勾选，帧循环驱动）：ok-ww 式战斗/闪避挂机
    'trigger_tasks': [
        ["src.tasks.auto_combat_task", "AutoCombatTask"],
        ["src.tasks.auto_combat_task", "DodgeAssistantTriggerTask"],
        ["src.tasks.dialogue_task", "AutoDialogueTriggerTask"],
        ["src.tasks.diagnostic_task", "DiagnosticRecordingTask"],
    ],
    # 一次性任务：一条龙日常为大入口，独立任务只保留大型玩法与工具
    'onetime_tasks': [
        # —— 日常 ——
        ["src.tasks.daily_task", "OneDragonDailyTask"],       # 🐉 一条龙
        # —— 独立玩法（大型）——
        ["src.tasks.app_tasks", "App_ChargePlan"],            # ⚡ 体力刷本
        ["src.tasks.app_tasks", "App_NotoriousHunt"],         # 🐲 恶名狩猎
        ["src.tasks.app_tasks", "App_ShiyuDefense"],          # 🛡️ 式舆防卫战
        ["src.tasks.app_tasks", "App_WitheredDomain"],        # 🕳️ 枯萎之都
        ["src.tasks.app_tasks", "App_LostVoid"],              # 🌌 迷失之地
        ["src.tasks.app_tasks", "App_WorldPatrol"],           # 🌍 锄大地
        ["src.tasks.app_tasks", "App_SuibianTemple"],         # 🏪 随便观
        ["src.tasks.app_tasks", "App_IntelBoard"],            # 📋 情报板
        ["src.tasks.app_tasks", "App_CommissionAssistant"],   # 🤝 委托助手
        ["src.tasks.app_tasks", "App_RandomPlay"],            # 🎬 录像店营业
        ["src.tasks.app_tasks", "App_LifeOnLine"],            # 🎮 真拿命验收
        ["src.tasks.app_tasks", "App_DriveDiscDismantle"],    # 💎 驱动盘拆解
        ["src.tasks.app_tasks", "App_RedemptionCode"],        # 🎫 兑换码
        # —— 校准/开发工具 ——
        ["src.tasks.app_tasks", "App_MouseSensitivityChecker"],      # 鼠标灵敏度
        ["src.tasks.app_tasks", "App_PredefinedTeamChecker"],        # 预备编队识别
        ["src.tasks.app_tasks", "App_OperationDebug"],               # 指令调试
        ["src.tasks.app_tasks", "App_ScreenshotHelper"],             # 闪避截图
        ["src.tasks.battle_demo_task", "BattleDemoTask"],            # 战斗演示
        ["src.tasks.framework_diagnosis_task", "FrameworkDiagnosisTask"],
    ],
}
