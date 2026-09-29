# -*- coding: utf-8 -*-
"""虚拟手柄控制器（移植自 one_dragon pc_button 模块，合并为单文件）。

移植自 ZenlessZoneZero-OneDragon (GPL-3.0):
  base/controller/pc_button/pc_button_controller.py
  base/controller/pc_button/virtual_gamepad_controller.py
  base/controller/pc_button/xbox_button_controller.py
  base/controller/pc_button/ds4_button_controller.py
  base/controller/pc_button/pc_button_utils.py

依赖 vgamepad(ViGEm)。未安装时手柄类仍可导入，动作调用报错。
"""
import contextlib
import time
from enum import Enum
from typing import Callable

try:
    import vgamepad
    _VGAMEPAD_INSTALLED = True
except Exception:
    vgamepad = None
    _VGAMEPAD_INSTALLED = False

from onedragon.base.config.config_item import ConfigItem


def is_vgamepad_installed() -> bool:
    return _VGAMEPAD_INSTALLED


class PcButtonController:

    def __init__(self) -> None:
        self.key_press_time: float = 0.02
        self.combo_press_time: float = 0.5

    def tap(self, key: str) -> None:
        pass

    def tap_combo(self, keys: list[str]) -> None:
        """顺序按下组合键：先按修饰键等待轮盘，再按动作键，最后全部释放。"""
        if not keys:
            return
        pressed: list[str] = []
        try:
            for i, key in enumerate(keys):
                if key is not None:
                    self.press(key, press_time=None)  # 按住不放
                    pressed.append(key)
                    if i < len(keys) - 1:
                        time.sleep(self.combo_press_time)
            time.sleep(self.key_press_time)
        finally:
            for key in reversed(pressed):
                with contextlib.suppress(Exception):
                    self.release(key)

    def press(self, key: str, press_time: float | None = None) -> None:
        pass

    def reset(self) -> None:
        pass

    def release(self, key: str) -> None:
        pass

    def set_key_press_time(self, key_press_time: float) -> None:
        self.key_press_time = key_press_time


class VirtualGamepadController(PcButtonController):
    """数据驱动的虚拟手柄控制器基类。

    子类提供 ``pad`` 实例并用 ``_register_*`` 注册按键，
    基类自动构建 tap / press / release 的字符串分发。
    """

    def __init__(self) -> None:
        PcButtonController.__init__(self)
        self.pad = None
        self._key_bindings: dict[str, tuple[Callable[[], None], Callable[[], None]]] = {}

    def _register_button(self, key: str, btn_const) -> None:
        self._key_bindings[key] = (
            lambda b=btn_const: self.pad.press_button(b),
            lambda b=btn_const: self.pad.release_button(b),
        )

    def _register_trigger(self, key: str, *, left: bool) -> None:
        trigger = 'left_trigger' if left else 'right_trigger'
        self._key_bindings[key] = (
            lambda t=trigger: getattr(self.pad, t)(value=255),
            lambda t=trigger: getattr(self.pad, t)(value=0),
        )

    def _register_stick(self, key: str, *, stick: str, x: float, y: float) -> None:
        fn_name = f'{stick}_joystick_float'
        self._key_bindings[key] = (
            lambda f=fn_name, _x=x, _y=y: getattr(self.pad, f)(_x, _y),
            lambda f=fn_name: getattr(self.pad, f)(0, 0),
        )

    def _do_action(self, activate: Callable[[], None], deactivate: Callable[[], None], *,
                   press: bool, press_time: float | None) -> None:
        activate()
        self.pad.update()

        if press:
            if press_time is None:  # 按住不放
                return
        else:
            if press_time is None:
                press_time = self.key_press_time

        time.sleep(max(self.key_press_time, press_time))
        deactivate()
        self.pad.update()

    def tap(self, key: str) -> None:
        if key is None:
            return
        activate, deactivate = self._key_bindings[key]
        self._do_action(activate, deactivate, press=False, press_time=None)

    def press(self, key: str, press_time: float | None = None) -> None:
        if key is None:
            return
        activate, deactivate = self._key_bindings[key]
        self._do_action(activate, deactivate, press=True, press_time=press_time)

    def release(self, key: str) -> None:
        if key is None:
            return
        _, deactivate = self._key_bindings[key]
        deactivate()
        self.pad.update()

    def reset(self) -> None:
        self.pad.reset()
        self.pad.update()


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
        if not is_vgamepad_installed():
            return

        import vgamepad as vg
        self.pad = vg.VX360Gamepad()
        btn = vg.XUSB_BUTTON

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

        self._register_trigger('xbox_lt', left=True)
        self._register_trigger('xbox_rt', left=False)

        for key, x, y in [
            ('xbox_ls_up', 0, 1), ('xbox_ls_down', 0, -1),
            ('xbox_ls_left', -1, 0), ('xbox_ls_right', 1, 0),
        ]:
            self._register_stick(key, stick='left', x=x, y=y)

        for key, x, y in [
            ('xbox_rs_up', 0, 1), ('xbox_rs_down', 0, -1),
            ('xbox_rs_left', -1, 0), ('xbox_rs_right', 1, 0),
        ]:
            self._register_stick(key, stick='right', x=x, y=y)


class Ds4ButtonEnum(Enum):

    CROSS = ConfigItem('✕', 'ds4_cross')
    CIRCLE = ConfigItem('○', 'ds4_circle')
    SQUARE = ConfigItem('□', 'ds4_square')
    TRIANGLE = ConfigItem('△', 'ds4_triangle')
    L2 = ConfigItem('L2', 'ds4_l2')
    R2 = ConfigItem('R2', 'ds4_r2')
    L1 = ConfigItem('L1', 'ds4_l1')
    R1 = ConfigItem('R1', 'ds4_r1')
    L_STICK_W = ConfigItem('左摇杆-上', 'ds4_ls_up')
    L_STICK_S = ConfigItem('左摇杆-下', 'ds4_ls_down')
    L_STICK_A = ConfigItem('左摇杆-左', 'ds4_ls_left')
    L_STICK_D = ConfigItem('左摇杆-右', 'ds4_ls_right')
    L_THUMB = ConfigItem('左摇杆-按下', 'ds4_l_thumb')
    R_THUMB = ConfigItem('右摇杆-按下', 'ds4_r_thumb')
    DPAD_UP = ConfigItem('十字键-上', 'ds4_dpad_up')
    DPAD_DOWN = ConfigItem('十字键-下', 'ds4_dpad_down')
    DPAD_LEFT = ConfigItem('十字键-左', 'ds4_dpad_left')
    DPAD_RIGHT = ConfigItem('十字键-右', 'ds4_dpad_right')
    OPTIONS = ConfigItem('OPTIONS', 'ds4_options')
    SHARE = ConfigItem('SHARE', 'ds4_share')
    TOUCHPAD = ConfigItem('触控板', 'ds4_touchpad')
    R_STICK_W = ConfigItem('右摇杆-上', 'ds4_rs_up')
    R_STICK_S = ConfigItem('右摇杆-下', 'ds4_rs_down')
    R_STICK_A = ConfigItem('右摇杆-左', 'ds4_rs_left')
    R_STICK_D = ConfigItem('右摇杆-右', 'ds4_rs_right')
    PS = ConfigItem('PS', 'ds4_ps')


class Ds4ButtonController(VirtualGamepadController):

    def __init__(self) -> None:
        VirtualGamepadController.__init__(self)
        if not is_vgamepad_installed():
            return

        import vgamepad as vg
        self.pad = vg.VDS4Gamepad()
        btn = vg.DS4_BUTTONS
        dpad = vg.DS4_DPAD_DIRECTIONS
        special = vg.DS4_SPECIAL_BUTTONS

        for key, const in [
            ('ds4_cross', btn.DS4_BUTTON_CROSS),
            ('ds4_circle', btn.DS4_BUTTON_CIRCLE),
            ('ds4_square', btn.DS4_BUTTON_SQUARE),
            ('ds4_triangle', btn.DS4_BUTTON_TRIANGLE),
            ('ds4_l1', btn.DS4_BUTTON_SHOULDER_LEFT),
            ('ds4_r1', btn.DS4_BUTTON_SHOULDER_RIGHT),
            ('ds4_l_thumb', btn.DS4_BUTTON_THUMB_LEFT),
            ('ds4_r_thumb', btn.DS4_BUTTON_THUMB_RIGHT),
            ('ds4_options', btn.DS4_BUTTON_OPTIONS),
            ('ds4_share', btn.DS4_BUTTON_SHARE),
        ]:
            self._register_button(key, const)

        self._register_trigger('ds4_l2', left=True)
        self._register_trigger('ds4_r2', left=False)

        none_dir = dpad.DS4_BUTTON_DPAD_NONE
        for key, direction in [
            ('ds4_dpad_up', dpad.DS4_BUTTON_DPAD_NORTH),
            ('ds4_dpad_down', dpad.DS4_BUTTON_DPAD_SOUTH),
            ('ds4_dpad_left', dpad.DS4_BUTTON_DPAD_WEST),
            ('ds4_dpad_right', dpad.DS4_BUTTON_DPAD_EAST),
        ]:
            self._key_bindings[key] = (
                lambda d=direction: self.pad.directional_pad(direction=d),
                lambda n=none_dir: self.pad.directional_pad(direction=n),
            )

        for key, sb in [
            ('ds4_ps', special.DS4_SPECIAL_BUTTON_PS),
            ('ds4_touchpad', special.DS4_SPECIAL_BUTTON_TOUCHPAD),
        ]:
            self._key_bindings[key] = (
                lambda s=sb: self.pad.press_special_button(special_button=s),
                lambda s=sb: self.pad.release_special_button(special_button=s),
            )

        for key, x, y in [
            ('ds4_ls_up', 0, 1), ('ds4_ls_down', 0, -1),
            ('ds4_ls_left', -1, 0), ('ds4_ls_right', 1, 0),
        ]:
            self._register_stick(key, stick='left', x=x, y=y)

        for key, x, y in [
            ('ds4_rs_up', 0, 1), ('ds4_rs_down', 0, -1),
            ('ds4_rs_left', -1, 0), ('ds4_rs_right', 1, 0),
        ]:
            self._register_stick(key, stick='right', x=x, y=y)
