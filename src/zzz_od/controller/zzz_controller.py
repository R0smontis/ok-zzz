# -*- coding: utf-8 -*-
"""绝区零 PC 控制器（ok-script 版）。

移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
  src/zzz_od/controller/zzz_pc_controller.py
  src/one_dragon/base/controller/pc_controller_base.py（部分）
  src/one_dragon/base/controller/pc_button/keyboard_mouse_controller.py

差异：截图不再由本类负责硬件采集，而是注入 ok-script 的取帧函数；
输入复用 pynput（前台键鼠）与 ViGEm 虚拟手柄（后台模式）。
"""
import ctypes
import time

from cv2.typing import MatLike

from onedragon.utils.log_utils import log
from zzz_od.config.game_config import GameConfig
from zzz_od.controller.gamepad import (
    Ds4ButtonController,
    PcButtonController,
    XboxButtonController,
    is_vgamepad_installed,
)

user32 = ctypes.windll.user32

MOUSEEVENTF_MOVE = 0x0001

# 一条龙 screen_normal_world.UID 区域（用于遮挡 UID 后再送识别模型）
UID_RECT = (1814, 1059, 1919, 1079)


class KeyboardBtnController(PcButtonController):
    """前台键鼠输入（pynput），与一条龙 KeyboardMouseController 行为一致。"""

    def __init__(self):
        PcButtonController.__init__(self)
        from pynput import keyboard, mouse
        self.keyboard = keyboard.Controller()
        self.mouse = mouse.Controller()
        self._pressed_keys: set[str] = set()

    @staticmethod
    def _is_mouse_button(key: str) -> bool:
        return key.startswith('mouse_')

    @staticmethod
    def _mouse_button(key: str):
        from pynput import mouse
        return mouse.Button[key[6:]]

    @staticmethod
    def _keyboard_button(key: str):
        from pynput import keyboard
        # 小键盘数字: numpad_0 ~ numpad_9
        if key.startswith('numpad_') and len(key) == 8 and key[-1].isdigit():
            return keyboard.KeyCode.from_vk(96 + int(key[-1]))
        if key in keyboard.Key.__members__:
            return keyboard.Key[key]
        if len(key) == 1:
            return keyboard.KeyCode.from_char(key)
        return key

    def tap(self, key: str) -> None:
        if key is None:
            return
        if self._is_mouse_button(key):
            self.mouse.click(self._mouse_button(key))
        else:
            self.keyboard.tap(self._keyboard_button(key))

    def press(self, key: str, press_time: float | None = None) -> None:
        if key is None:
            return
        is_mouse = self._is_mouse_button(key)
        real_key = self._mouse_button(key) if is_mouse else self._keyboard_button(key)
        if is_mouse:
            self.mouse.press(real_key)
        else:
            self.keyboard.press(real_key)
        if press_time is None:
            self._pressed_keys.add(key)
            return
        time.sleep(press_time)
        if is_mouse:
            self.mouse.release(real_key)
        else:
            self.keyboard.release(real_key)

    def release(self, key: str) -> None:
        if key is None or key not in self._pressed_keys:
            return
        self._pressed_keys.discard(key)
        if self._is_mouse_button(key):
            self.mouse.release(self._mouse_button(key))
        else:
            self.keyboard.release(self._keyboard_button(key))

    def reset(self) -> None:
        for key in list(self._pressed_keys):
            self.release(key)


class ZzzController:
    """绝区零控制器：动作按键 + 相对鼠标移动 + 截图委托。

    与一条龙 ZPcController 的方法面保持一致，战斗引擎无需感知差异。
    """

    def __init__(self, game_config: GameConfig, frame_provider=None):
        """
        Args:
            game_config: 键位等配置
            frame_provider: callable() -> (timestamp: float, frame: MatLike|None)
                由 ok-script 集成层注入（通常包装 executor.next_frame）
        """
        self.game_config: GameConfig = game_config
        self.frame_provider = frame_provider

        self.keyboard_controller: KeyboardBtnController = KeyboardBtnController()
        self.xbox_controller: XboxButtonController | None = None
        self.ds4_controller: Ds4ButtonController | None = None
        self.btn_controller: PcButtonController = self.keyboard_controller

        self.action_keys = self.game_config.get_action_keys('keyboard')
        self.gamepad_action_keys = self.game_config.get_gamepad_action_keys()

        self.is_moving: bool = False  # 是否正在移动
        self.background_mode: bool = False

    # ------------------------------------------------------------------ #
    # 模式切换
    # ------------------------------------------------------------------ #

    def sync_game_config(self, game_config: GameConfig) -> None:
        """切换实例后同步控制器持有的账号级配置"""
        self.game_config = game_config
        if self.game_config.background_mode:
            self.enable_background_mode(self.game_config.background_gamepad_type)
        else:
            self.enable_foreground_mode()
            self.active_window()

    def init_before_context_run(self) -> bool:
        """运行前根据配置启用后台/前台模式"""
        if self.game_config.background_mode:
            self.enable_background_mode(self.game_config.background_gamepad_type)
        else:
            self.enable_foreground_mode()
        return True

    def active_window(self) -> None:
        """把游戏窗口带到前台（由集成层注入 hwnd 激活实现，缺省为空操作）"""
        activate = getattr(self, '_activate_window_impl', None)
        if activate is not None:
            try:
                activate()
            except Exception as e:
                log.warning(f'激活游戏窗口失败: {e}')

    def enable_foreground_mode(self) -> None:
        self.background_mode = False
        self.enable_keyboard()

    def enable_background_mode(self, gamepad_type: str = 'xbox') -> None:
        """启用后台模式（虚拟手柄输入）"""
        if gamepad_type == 'ds4':
            self.enable_ds4()
        else:
            self.enable_xbox()
        if self.btn_controller is self.keyboard_controller:
            log.error('后台模式需要 vgamepad(ViGEm) 支持，当前不可用，保持键鼠模式')
            self.enable_keyboard()
            self.background_mode = False
            return
        self.background_mode = True
        if gamepad_type == 'ds4':
            self.btn_controller.set_key_press_time(self.game_config.ds4_key_press_time)
        else:
            self.btn_controller.set_key_press_time(self.game_config.xbox_key_press_time)

    def enable_keyboard(self) -> None:
        self.btn_controller = self.keyboard_controller
        self.action_keys = self.game_config.get_action_keys('keyboard')

    def enable_xbox(self) -> None:
        if self.xbox_controller is None:
            if not is_vgamepad_installed():
                log.error('未安装 vgamepad，无法使用 Xbox 虚拟手柄')
                return
            self.xbox_controller = XboxButtonController()
        self.btn_controller = self.xbox_controller
        self.action_keys = self.game_config.get_action_keys('xbox')
        self.gamepad_action_keys = self.game_config.get_gamepad_action_keys('xbox')

    def enable_ds4(self) -> None:
        if self.ds4_controller is None:
            if not is_vgamepad_installed():
                log.error('未安装 vgamepad，无法使用 DS4 虚拟手柄')
                return
            self.ds4_controller = Ds4ButtonController()
        self.btn_controller = self.ds4_controller
        self.action_keys = self.game_config.get_action_keys('ds4')
        self.gamepad_action_keys = self.game_config.get_gamepad_action_keys('ds4')

    def get_mouse_flash_duration(self) -> float:
        return self.game_config.mouse_flash_duration

    # ------------------------------------------------------------------ #
    # 动作按键
    # ------------------------------------------------------------------ #

    def _action_btn(self, key: str, press: bool = False, press_time: float | None = None,
                    release: bool = False) -> None:
        if press:
            self.btn_controller.press(key, press_time)
        elif release:
            self.btn_controller.release(key)
        else:
            self.btn_controller.tap(key)

    def dodge(self, press: bool = False, press_time: float | None = None, release: bool = False) -> None:
        """闪避"""
        self._action_btn(self.action_keys['dodge'], press, press_time, release)

    def switch_next(self, press: bool = False, press_time: float | None = None, release: bool = False) -> None:
        """切换角色-下一个"""
        self._action_btn(self.action_keys['switch_next'], press, press_time, release)

    def switch_prev(self, press: bool = False, press_time: float | None = None, release: bool = False) -> None:
        """切换角色-上一个"""
        self._action_btn(self.action_keys['switch_prev'], press, press_time, release)

    def switch_backup(self, press: bool = False, press_time: float | None = None, release: bool = False) -> None:
        """切换后援"""
        self._action_btn(self.action_keys['switch_backup'], press, press_time, release)

    def normal_attack(self, press: bool = False, press_time: float | None = None, release: bool = False) -> None:
        """普通攻击"""
        self._action_btn(self.action_keys['normal_attack'], press, press_time, release)

    def special_attack(self, press: bool = False, press_time: float | None = None, release: bool = False) -> None:
        """特殊攻击"""
        self._action_btn(self.action_keys['special_attack'], press, press_time, release)

    def ultimate(self, press: bool = False, press_time: float | None = None, release: bool = False) -> None:
        """终结技"""
        self._action_btn(self.action_keys['ultimate'], press, press_time, release)

    def chain_left(self, press: bool = False, press_time: float | None = None, release: bool = False) -> None:
        """连携技-左"""
        self._action_btn(self.action_keys['chain_left'], press, press_time, release)

    def chain_right(self, press: bool = False, press_time: float | None = None, release: bool = False) -> None:
        """连携技-右"""
        self._action_btn(self.action_keys['chain_right'], press, press_time, release)

    def move_w(self, press: bool = False, press_time: float | None = None, release: bool = False) -> None:
        """向前移动"""
        self._action_btn(self.action_keys['move_w'], press, press_time, release)

    def move_s(self, press: bool = False, press_time: float | None = None, release: bool = False) -> None:
        """向后移动"""
        self._action_btn(self.action_keys['move_s'], press, press_time, release)

    def move_a(self, press: bool = False, press_time: float | None = None, release: bool = False) -> None:
        """向左移动"""
        self._action_btn(self.action_keys['move_a'], press, press_time, release)

    def move_d(self, press: bool = False, press_time: float | None = None, release: bool = False) -> None:
        """向右移动"""
        self._action_btn(self.action_keys['move_d'], press, press_time, release)

    def interact(self, press: bool = False, press_time: float | None = None, release: bool = False) -> None:
        """交互"""
        self._action_btn(self.action_keys['interact'], press, press_time, release)

    def lock(self, press: bool = False, press_time: float | None = None, release: bool = False) -> None:
        """锁定敌人"""
        self._action_btn(self.action_keys['lock'], press, press_time, release)

    def chain_cancel(self, press: bool = False, press_time: float | None = None, release: bool = False) -> None:
        """取消连携"""
        self._action_btn(self.action_keys['chain_cancel'], press, press_time, release)

    def start_moving_forward(self) -> None:
        if self.is_moving:
            return
        self.is_moving = True
        self.move_w(press=True)

    def stop_moving_forward(self) -> None:
        self.is_moving = False
        self.move_w(release=True)

    # ------------------------------------------------------------------ #
    # 鼠标相对移动（镜头转向）
    # ------------------------------------------------------------------ #

    def move_mouse_relative(self, dx: float, dy: float) -> None:
        """相对移动鼠标（前台键鼠模式）。后台手柄模式下按右摇杆近似实现。"""
        if self.background_mode and isinstance(self.btn_controller, (XboxButtonController, Ds4ButtonController)):
            self._turn_by_gamepad(dx)
            return
        user32.mouse_event(MOUSEEVENTF_MOVE, int(dx), int(dy), 0, 0)

    def _turn_by_gamepad(self, dx: float) -> None:
        """手柄右摇杆转向：满偏转对应 gamepad_turn_speed 像素/秒。"""
        speed = max(self.game_config.gamepad_turn_speed, 1)
        duration = abs(dx) / speed
        turn_stick = None
        if isinstance(self.btn_controller, XboxButtonController):
            turn_stick = ('rs_right', 'rs_left') if dx >= 0 else ('rs_left', 'rs_right')
        elif isinstance(self.btn_controller, Ds4ButtonController):
            turn_stick = ('ds4_rs_right', 'ds4_rs_left') if dx >= 0 else ('ds4_rs_left', 'ds4_rs_right')
        if turn_stick is None:
            return
        press_key, _release_key = turn_stick
        self.btn_controller.press(press_key)
        time.sleep(min(duration, 1.0))
        self.btn_controller.release(press_key)

    def turn_by_distance(self, d: float) -> None:
        """横向转向 按距离转（正数往右）"""
        self.move_mouse_relative(d, 0)

    def turn_vertical_by_distance(self, d: float) -> None:
        """纵向转向 按距离转（正数往下）"""
        self.move_mouse_relative(0, d)

    def turn_by_angle_diff(self, angle_diff: float) -> None:
        """按角度偏移转向（逆时针为正）"""
        self.turn_by_distance(self.game_config.turn_dx * angle_diff)

    # ------------------------------------------------------------------ #
    # 截图
    # ------------------------------------------------------------------ #

    def screenshot(self) -> tuple[float, MatLike | None]:
        """获取当前游戏画面 (截图时间, 帧)。由 ok-script 取帧函数支撑。"""
        if self.frame_provider is None:
            raise RuntimeError('ZzzController 未注入 frame_provider')
        screenshot_time, frame = self.frame_provider()
        return screenshot_time, frame

    @staticmethod
    def fill_uid_black(screen: MatLike) -> MatLike:
        """遮挡右下角 UID 区域（与一条龙 ScreenNormalWorldEnum.UID 一致）"""
        import cv2
        import numpy as np
        mask = np.zeros(screen.shape[:2], dtype=np.uint8)
        x1, y1, x2, y2 = UID_RECT
        h, w = screen.shape[:2]
        mask[min(y1, h - 1):min(y2, h), min(x1, w - 1):min(x2, w)] = 255
        return cv2.bitwise_and(screen, screen, mask=cv2.bitwise_not(mask))
