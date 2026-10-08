# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/application/battle_assistant/battle_assistant_input_mode.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from __future__ import annotations

from typing import TYPE_CHECKING

from onedragon.base.controller.pc_button import pc_button_utils
from zzz_od.config.game_config import GamepadTypeEnum

if TYPE_CHECKING:
    from zzz_od.context.zzz_context import ZContext


def apply_battle_assistant_input_mode(ctx: ZContext, background_mode: bool | None = None,
                                    activate: bool = True) -> tuple[bool, str]:
    """按游戏助手临时后台开关和全局后台配置切换 controller。"""
    config = ctx.battle_assistant_config

    if (getattr(ctx.game_config, '_task_input_mode', None) == 'messages'
            or getattr(ctx.game_config, '_framework_message_mode', False)):
        ctx.controller.enable_window_message_mode()
        ctx.controller.action_keys = ctx.game_config.get_action_keys('keyboard')
        return True, '后台模式-窗口消息'

    if background_mode is None:
        background_mode = config.background_mode
    background_mode = (background_mode or getattr(ctx.game_config, '_framework_background_mode', False)
                       or getattr(ctx.game_config, '_task_input_mode', None) == 'gamepad')
    if background_mode:
        gamepad_type = ctx.game_config.background_gamepad_type

        if not pc_button_utils.is_vgamepad_installed():
            return False, '后台模式不可用：未安装虚拟手柄依赖和 ViGEmBus 驱动'

        if gamepad_type == GamepadTypeEnum.DS4.value.value:
            ctx.controller.enable_background_mode(GamepadTypeEnum.DS4.value.value)
            if not ctx.controller.background_mode:
                return False, '后台虚拟手柄初始化失败'
            ctx.controller.btn_controller.set_key_press_time(ctx.game_config.ds4_key_press_time)
            return True, '后台模式-DS4'

        ctx.controller.enable_background_mode(GamepadTypeEnum.XBOX.value.value)
        if not ctx.controller.background_mode:
            return False, '后台虚拟手柄初始化失败'
        ctx.controller.btn_controller.set_key_press_time(ctx.game_config.xbox_key_press_time)
        return True, '后台模式-Xbox'

    ctx.controller.enable_foreground_mode()
    if activate:
        ctx.controller.active_window()
    return True, '前台模式-键鼠'
