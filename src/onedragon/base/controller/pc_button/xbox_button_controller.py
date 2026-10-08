# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: one_dragon/base/controller/pc_button/xbox_button_controller.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from enum import Enum

from onedragon.base.config.config_item import ConfigItem
from onedragon.base.controller.pc_button import pc_button_utils
from onedragon.base.controller.pc_button.virtual_gamepad_controller import (
    VirtualGamepadController,
)


class XboxButtonEnum(Enum):

    A = ConfigItem('A', 'xbox_a')
    B = ConfigItem('B', 'xbox_b')
    X = ConfigItem('X', 'xbox_x')
    Y = ConfigItem('Y', 'xbox_y')
    LT = ConfigItem('LT', 'xbox_lt')
    RT = ConfigItem('RT', 'xbox_rt')
    LB = ConfigItem('LB', 'xbox_lb')
    RB = ConfigItem('RB', 'xbox_rb')
    L_STICK_W = ConfigItem('左摇杆-上', 'xbox_ls_up')
    L_STICK_S = ConfigItem('左摇杆-下', 'xbox_ls_down')
    L_STICK_A = ConfigItem('左摇杆-左', 'xbox_ls_left')
    L_STICK_D = ConfigItem('左摇杆-右', 'xbox_ls_right')
    L_THUMB = ConfigItem('左摇杆-按下', 'xbox_l_thumb')
    R_THUMB = ConfigItem('右摇杆-按下', 'xbox_r_thumb')
    DPAD_UP = ConfigItem('十字键-上', 'xbox_dpad_up')
    DPAD_DOWN = ConfigItem('十字键-下', 'xbox_dpad_down')
    DPAD_LEFT = ConfigItem('十字键-左', 'xbox_dpad_left')
    DPAD_RIGHT = ConfigItem('十字键-右', 'xbox_dpad_right')
    START = ConfigItem('START', 'xbox_start')
    BACK = ConfigItem('BACK', 'xbox_back')
    R_STICK_W = ConfigItem('右摇杆-上', 'xbox_rs_up')
    R_STICK_S = ConfigItem('右摇杆-下', 'xbox_rs_down')
    R_STICK_A = ConfigItem('右摇杆-左', 'xbox_rs_left')
    R_STICK_D = ConfigItem('右摇杆-右', 'xbox_rs_right')
    GUIDE = ConfigItem('GUIDE', 'xbox_guide')


class XboxButtonController(VirtualGamepadController):

    def __init__(self) -> None:
        VirtualGamepadController.__init__(self)
        if not pc_button_utils.is_vgamepad_installed():
            return

        import vgamepad as vg
        self.pad = vg.VX360Gamepad()
        btn = vg.XUSB_BUTTON

        # 普通按钮
        for key, const in [
            ('xbox_a', btn.XUSB_GAMEPAD_A),
            ('xbox_b', btn.XUSB_GAMEPAD_B),
            ('xbox_x', btn.XUSB_GAMEPAD_X),
            ('xbox_y', btn.XUSB_GAMEPAD_Y),
            ('xbox_lb', btn.XUSB_GAMEPAD_LEFT_SHOULDER),
            ('xbox_rb', btn.XUSB_GAMEPAD_RIGHT_SHOULDER),
            ('xbox_l_thumb', btn.XUSB_GAMEPAD_LEFT_THUMB),
            ('xbox_r_thumb', btn.XUSB_GAMEPAD_RIGHT_THUMB),
            ('xbox_dpad_up', btn.XUSB_GAMEPAD_DPAD_UP),
            ('xbox_dpad_down', btn.XUSB_GAMEPAD_DPAD_DOWN),
            ('xbox_dpad_left', btn.XUSB_GAMEPAD_DPAD_LEFT),
            ('xbox_dpad_right', btn.XUSB_GAMEPAD_DPAD_RIGHT),
            ('xbox_start', btn.XUSB_GAMEPAD_START),
            ('xbox_back', btn.XUSB_GAMEPAD_BACK),
            ('xbox_guide', btn.XUSB_GAMEPAD_GUIDE),
        ]:
            self._register_button(key, const)

        # 扳机
        self._register_trigger('xbox_lt', left=True)
        self._register_trigger('xbox_rt', left=False)

        # 左摇杆
        for key, x, y in [
            ('xbox_ls_up', 0, 1), ('xbox_ls_down', 0, -1),
            ('xbox_ls_left', -1, 0), ('xbox_ls_right', 1, 0),
        ]:
            self._register_stick(key, stick='left', x=x, y=y)
        for direction, x, y in [('up',0,.35),('down',0,-.35),('left',-.35,0),('right',.35,0)]:
            self._register_stick('xbox_ls_slow_'+direction,stick='left',x=x,y=y)

        # 右摇杆
        for key, x, y in [
            ('xbox_rs_up', 0, 1), ('xbox_rs_down', 0, -1),
            ('xbox_rs_left', -1, 0), ('xbox_rs_right', 1, 0),
        ]:
            self._register_stick(key, stick='right', x=x, y=y)
