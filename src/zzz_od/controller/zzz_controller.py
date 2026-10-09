# -*- coding: utf-8 -*-
"""绝区零控制器（ok-zzz）。

继承移植版 ZPcController（完整一条龙控制器栈：截图 capper、键鼠、
虚拟手柄、窗口管理），仅增加 ok-script 帧源注入：battle 引擎等
高频取帧场景可走 ok-script 的 WGC/BitBlt 截图，其余行为不变。
"""
import time

import win32con
import win32gui
from cv2.typing import MatLike

from zzz_od.config.game_config import GameConfig
from zzz_od.controller.zzz_pc_controller import ZPcController
from onedragon.base.controller.input_guard import execution_input_allowed, execution_action
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
        if allowed:
            super().btn_press(key, press_time)

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
        return super().click(pos, press_time, pc_alt, gamepad_key)

    def click_dialogue_event(self, pos, *, expected_hwnd, allow_background=False):
        """Deliver a current dialogue event without activating a background window."""
        if not execution_input_allowed():
            return False
        record_event('dialogue_input_request', x=pos.x, y=pos.y, hwnd=expected_hwnd,
                     allow_background=allow_background)
        window = self.game_win
        if not expected_hwnd or window.get_hwnd() != expected_hwnd or not window.is_win_valid:
            return False
        if window.is_win_active and not allow_background and not self.is_background_input:
            return self._foreground_click(pos, press_time=0.001)
        if not allow_background and not (window.is_win_active and self.is_background_input):
            return False
        scaled = window.get_scaled_game_pos(pos)
        if scaled is None or window.get_hwnd() != expected_hwnd:
            return False
        coordinates = (int(scaled.x) & 0xffff) | ((int(scaled.y) & 0xffff) << 16)
        try:
            # No SetCursorPos, input-mode switch or foreground activation here.
            win32gui.PostMessage(expected_hwnd, win32con.WM_MOUSEMOVE, 0, coordinates)
            win32gui.PostMessage(expected_hwnd, win32con.WM_LBUTTONDOWN,
                                 win32con.MK_LBUTTON, coordinates)
            win32gui.PostMessage(expected_hwnd, win32con.WM_LBUTTONUP, 0, coordinates)
            return True
        except Exception:
            # Always try to release the original target if delivery was interrupted.
            try:
                win32gui.PostMessage(expected_hwnd, win32con.WM_LBUTTONUP, 0, coordinates)
            except Exception:
                pass
            return False

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
            return timestamp, frame
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
