# -*- coding: utf-8 -*-
"""绝区零控制器（ok-zzz）。

继承移植版 ZPcController（完整一条龙控制器栈：截图 capper、键鼠、
虚拟手柄、窗口管理），仅增加 ok-script 帧源注入：battle 引擎等
高频取帧场景可走 ok-script 的 WGC/BitBlt 截图，其余行为不变。
"""
import time

from pyautogui import FailSafeException

from cv2.typing import MatLike

from zzz_od.config.game_config import GameConfig
from zzz_od.controller.zzz_pc_controller import ZPcController
from onedragon.base.controller.input_guard import execution_input_allowed, execution_action
from onedragon.base.controller.pc_controller_base import win_click
from src.diagnostics.recorder import record_event
from src.runtime.frame_geometry import FrameGeometry, normalize_bgr


class ZzzController(ZPcController):

    def __init__(self,
                 game_config: GameConfig,
                 screenshot_method: str = 'auto',
                 standard_width: int = 1920,
                 standard_height: int = 1080,
                 frame_provider=None):
        """
        Args:
            frame_provider: callable() -> (timestamp, frame)。设置后
                screenshot() 优先使用（ok-script 捕获），否则走原版 capper。
        """
        ZPcController.__init__(self,
                               game_config=game_config,
                               screenshot_method=screenshot_method,
                               standard_width=standard_width,
                               standard_height=standard_height)
        self.frame_provider = frame_provider
        self.battle_input_guard = None
        self.battle_action_guard = None

    def _battle_input_allowed(self, action=None):
        guard = getattr(self, 'battle_input_guard', None)
        action_guard = getattr(self, 'battle_action_guard', None)
        return (execution_input_allowed() and (guard is None or guard())
                and (action_guard is None or action_guard(action or execution_action.get())))

    def btn_tap(self, key):
        allowed = self._battle_input_allowed()
        record_event('input_call', action='tap', key=key, allowed=allowed,
                     background=getattr(self, 'background_mode', None))
        if allowed:
            super().btn_tap(key)

    def btn_press(self, key, press_time=None):
        allowed = self._battle_input_allowed()
        record_event('input_call', action='press', key=key, duration=press_time, allowed=allowed,
                     background=getattr(self, 'background_mode', None))
        if not allowed:
            return False
        return super().btn_press(key, press_time) is not False

    def btn_release(self, key):
        record_event('input_call', action='release', key=key, allowed=True,
                     background=getattr(self, 'background_mode', None))
        super().btn_release(key)

    def move_mouse_relative(self, dx, dy):
        allowed = self._battle_input_allowed('turn')
        record_event('input_call', action='turn', dx=dx, dy=dy, allowed=allowed,
                     background=getattr(self, 'background_mode', None))
        if allowed:
            super().move_mouse_relative(dx, dy)

    def click(self, pos=None, press_time=0.1, pc_alt=False, gamepad_key=None):
        record_event('input_call', action='click', x=getattr(pos, 'x', None), y=getattr(pos, 'y', None),
                     duration=press_time, background=self.background_mode, gamepad_key=gamepad_key)
        from src.runtime.logging_bridge import log_input
        if gamepad_key and self.background_mode:
            log_input(f'手柄 {gamepad_key}')
        else:
            where = f'({pos.x:.0f}, {pos.y:.0f})' if pos is not None else '当前鼠标位置'
            log_input(f'点击 {where}' + ('（后台消息）' if getattr(self, 'is_background_input', False) else ''))
        return super().click(pos, press_time, pc_alt, gamepad_key)

    def click_dialogue_event(self, pos, *, expected_hwnd, input_allowed):
        """Use physical mouse input for story only; leave every other controller mode intact."""
        window = self.game_win

        def ready():
            return (execution_input_allowed() and input_allowed() and self.game_win is window
                    and expected_hwnd and window.get_hwnd() == expected_hwnd
                    and window.is_win_valid)

        if not ready():
            return False
        if not window.is_win_active:
            window.active()
            # Activation can change controller prompts/layout; recognize a fresh frame first.
            return False
        target = window.game2win_pos(pos)
        if target is None:
            return False

        def before_press():
            if not ready() or not window.is_win_active:
                return False
            current = window.game2win_pos(pos)
            return current is not None and current.x == target.x and current.y == target.y

        record_event('dialogue_input_request', x=pos.x, y=pos.y, hwnd=expected_hwnd,
                     input_mode='keyboard_mouse')
        # Mouse movement may change the game's input prompts even if the later click is cancelled.
        self.forget_game_input_mode()
        try:
            delivered = win_click(target, press_time=.001, input_allowed=before_press)
        except FailSafeException:
            # The safety corner cancels this click, not the story task. Mouse-up is guaranteed.
            return False
        if delivered:
            self._game_input_mode = 'keyboard_mouse'
        return delivered

    def normalize_frame(self, frame: MatLike | None) -> MatLike | None:
        """将 ok-script 的 BGR 帧转换为一条龙使用的标准尺寸 RGB 帧。

        原版截图器、模板和模型均使用 RGB；转换仅发生在框架帧入口，
        原版截图回退不再转换，也不修改框架持有的原始帧。
        """
        normalized = normalize_bgr(frame, self.standard_width, self.standard_height)
        geometry = None if normalized is None else FrameGeometry(
            frame.shape[1], frame.shape[0], self.standard_width, self.standard_height).snapshot()
        if geometry != getattr(self, 'frame_geometry', None):
            record_event('frame_geometry_changed', geometry=geometry)
        self.frame_geometry = geometry
        return normalized

    def screenshot(self, independent: bool = False) -> tuple[float, MatLike | None]:
        if self.frame_provider is not None and not independent:
            from src.runtime.inference import recognition_interval
            wait = recognition_interval()-(time.monotonic()-getattr(self, '_last_frame_request', 0))
            if wait > 0:
                time.sleep(wait)
            self._last_frame_request = time.monotonic()
            timestamp, frame = self.frame_provider()
            frame = self.normalize_frame(frame)
            if frame is None:
                self.cancel_inputs()
                raise RuntimeError('选中窗口截图不可用，已停止输入；请检查截图方式')
            # normalize_bgr returns a fresh RGB buffer, not the capture provider's frame.
            return timestamp, self.fill_uid_black(frame, new_image=False)
        return ZPcController.screenshot(self, independent=independent)

    def sync_frames(self) -> tuple[float, MatLike | None]:
        """强制使用原版 capper 取帧（避免死循环调用 frame_provider）。"""
        return ZPcController.screenshot(self)

    def wait_frame(self, timeout: float = 5) -> tuple[float, MatLike | None] | None:
        """等待一帧（供需要帧间步进的应用使用）。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            t, frame = self.screenshot()
            if frame is not None:
                return t, frame
            time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        return None
