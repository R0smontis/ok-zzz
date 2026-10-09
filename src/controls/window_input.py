"""只向选中窗口发送输入消息，不操作前台窗口或系统光标。"""
import threading

import win32api
import win32con
import win32gui

from onedragon.base.controller.pc_button.pc_button_controller import PcButtonController
from onedragon.base.controller.pc_button import pc_button_utils
from onedragon.base.geometry.point import Point
from onedragon.utils.log_utils import log
from src.diagnostics.recorder import record_event

# 部分 pywin32 版本未导出侧键常量，沿用 Win32 定义的值。
WM_XBUTTONDOWN = 0x020b
WM_XBUTTONUP = 0x020c
MK_XBUTTON1 = 0x0020
MK_XBUTTON2 = 0x0040


class WindowMessageInput(PcButtonController):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.position = Point(960, 540)
        self._lock = threading.RLock()
        self._held = {}
        self._cancel = threading.Event()

    def target(self):
        hwnd = self.window.get_hwnd()
        return hwnd if hwnd and self.window.is_win_valid else None

    def _valid(self, hwnd):
        return bool(hwnd and not self._cancel.is_set() and self.target() == hwnd)

    def _post(self, hwnd, message, wparam=0, lparam=0):
        win32gui.PostMessage(hwnd, message, wparam, lparam)

    def activate(self, hwnd):
        self._post(hwnd, win32con.WM_ACTIVATE, win32con.WA_ACTIVE)

    def _point(self, pos):
        pos = pos or self.position
        scaled = self.window.get_scaled_game_pos(pos)
        if scaled is None:
            return None
        self.position = pos
        return (int(scaled.x), int(scaled.y))

    @staticmethod
    def pack(x, y):
        return (int(x) & 0xffff) | ((int(y) & 0xffff) << 16)

    def move(self, pos):
        self._cancel.clear()
        hwnd, point = self.target(), self._point(pos)
        if point is None or not self._valid(hwnd):
            return False
        try:
            self._post(hwnd, win32con.WM_MOUSEMOVE, 0, self.pack(*point))
            return True
        except Exception:
            log.warning('后台鼠标消息发送失败', exc_info=True)
            return False

    def click(self, pos=None, duration=.02, alt=False, button='left'):
        self._cancel.clear()
        hwnd, point = self.target(), self._point(pos)
        if point is None or not self._valid(hwnd):
            return False
        down, up, flag, release_flag = self._mouse_messages(button)
        coordinates = self.pack(*point)
        pressed = False
        try:
            self.activate(hwnd)
            if alt:
                self.press('alt')
            self._post(hwnd, win32con.WM_MOUSEMOVE, 0, coordinates)
            # 让游戏先处理悬停位置，避免点击继续使用上一帧的指针位置。
            if self._cancel.wait(.04):
                return False
            if not self._valid(hwnd):
                return False
            self._post(hwnd, down, flag, coordinates)
            pressed = True
            self._cancel.wait(max(.001, duration))
            return self._valid(hwnd)
        except Exception:
            log.warning('后台点击消息发送失败', exc_info=True)
            return False
        finally:
            if pressed:
                self._release_message(hwnd, up, release_flag, coordinates)
            if alt:
                self.release('alt')
            record_event('window_input', action='click', hwnd=hwnd, x=point[0], y=point[1])

    @staticmethod
    def _mouse_messages(button):
        return {'left': (win32con.WM_LBUTTONDOWN, win32con.WM_LBUTTONUP, win32con.MK_LBUTTON, 0),
                'right': (win32con.WM_RBUTTONDOWN, win32con.WM_RBUTTONUP, win32con.MK_RBUTTON, 0),
                'middle': (win32con.WM_MBUTTONDOWN, win32con.WM_MBUTTONUP, win32con.MK_MBUTTON, 0),
                'x1': (WM_XBUTTONDOWN, WM_XBUTTONUP, (1 << 16) | MK_XBUTTON1, 1 << 16),
                'x2': (WM_XBUTTONDOWN, WM_XBUTTONUP, (2 << 16) | MK_XBUTTON2, 2 << 16)}[button]

    def drag(self, start, end, duration=.5):
        self._cancel.clear()
        hwnd = self.target()
        first, last = self._point(start), self._point(end)
        if first is None or last is None or not self._valid(hwnd):
            return False
        pressed = False
        coordinates = self.pack(*first)
        try:
            self.activate(hwnd)
            self._post(hwnd, win32con.WM_MOUSEMOVE, 0, coordinates)
            if self._cancel.wait(.04) or not self._valid(hwnd):
                return False
            self._post(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, coordinates)
            pressed = True
            steps = max(1, int(max(0, duration) / .02))
            for index in range(1, steps + 1):
                if not self._valid(hwnd):
                    return False
                ratio = index / steps
                coordinates = self.pack(first[0] + (last[0] - first[0]) * ratio,
                                        first[1] + (last[1] - first[1]) * ratio)
                self._post(hwnd, win32con.WM_MOUSEMOVE, win32con.MK_LBUTTON, coordinates)
                if self._cancel.wait(max(0, duration) / steps):
                    return False
            return True
        except Exception:
            log.warning('后台拖拽消息发送失败', exc_info=True)
            return False
        finally:
            if pressed:
                self._release_message(hwnd, win32con.WM_LBUTTONUP, 0, coordinates)
            record_event('window_input', action='drag', hwnd=hwnd)

    def scroll(self, down, pos=None):
        self._cancel.clear()
        hwnd, point = self.target(), self._point(pos)
        if point is None or not self._valid(hwnd):
            return False
        try:
            self.activate(hwnd)
            # WM_MOUSEWHEEL 使用屏幕坐标，其余鼠标消息使用客户区坐标。
            screen_point = win32gui.ClientToScreen(hwnd, point)
            self._post(hwnd, win32con.WM_MOUSEWHEEL, ((-120 * int(down)) & 0xffff) << 16,
                       self.pack(*screen_point))
            return True
        except Exception:
            log.warning('后台滚轮消息发送失败', exc_info=True)
            return False

    def input_text(self, text, interval=.01):
        self._cancel.clear()
        hwnd = self.target()
        if not self._valid(hwnd):
            return False
        try:
            self.activate(hwnd)
            encoded = str(text).encode('utf-16-le')
            for index in range(0, len(encoded), 2):
                if not self._valid(hwnd):
                    return False
                self._post(hwnd, win32con.WM_CHAR, int.from_bytes(encoded[index:index+2], 'little'))
                if self._cancel.wait(max(0, interval)):
                    return False
            # 文本可能是账号、密码；诊断仅记录长度。
            record_event('window_input', action='text', hwnd=hwnd, length=len(text))
            return True
        except Exception:
            log.warning('后台文本消息发送失败', exc_info=True)
            return False

    def tap(self, key):
        return self.press(key, self.key_press_time)

    def press(self, key, press_time=None):
        if press_time is not None and press_time < 0:
            raise ValueError('press_time must be non-negative')
        self._cancel.clear()
        hwnd = self.target()
        if not self._valid(hwnd):
            return False
        if key.startswith('mouse_'):
            point = self._point(None)
            if point is None:
                return False
            down, up, vk, release_vk = self._mouse_messages(key[6:])
            flags = release_flags = self.pack(*point)
        else:
            resolved = pc_button_utils.get_keyboard_button(key)
            vk = getattr(getattr(resolved, 'value', resolved), 'vk', None)
            if vk is None and len(key) == 1:
                value = win32api.VkKeyScan(key)
                vk = value & 0xff if value >= 0 else None
            if vk is None:
                raise ValueError(f'不支持的后台按键：{key}')
            scan = win32api.MapVirtualKey(vk, 0)
            extended = vk in (0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2d, 0x2e, 0x6f)
            flags = 1 | (scan << 16) | (int(extended) << 24)
            release_flags, release_vk = flags | (1 << 30) | (1 << 31), vk
            down, up = (win32con.WM_SYSKEYDOWN, win32con.WM_SYSKEYUP) if vk == 0x12 else (win32con.WM_KEYDOWN, win32con.WM_KEYUP)
        released = threading.Event()
        try:
            with self._lock:
                previous = self._held.pop(key, None)
                if previous:
                    self._release_held(previous)
                self.activate(hwnd)
                if not self._valid(hwnd):
                    return False
                self._post(hwnd, down, vk, flags)
                self._held[key] = (hwnd, up, release_vk, release_flags, released)
            if press_time is not None:
                released.wait(press_time)
            return True
        except Exception:
            log.warning('后台按键消息发送失败', exc_info=True)
            return False
        finally:
            if press_time is not None:
                with self._lock:
                    if key in self._held and self._held[key][-1] is released:
                        self.release(key)

    def _release_message(self, hwnd, message, wparam=0, lparam=0):
        try:
            self._post(hwnd, message, wparam, lparam)
        except Exception:
            pass  # 只释放原窗口，不把按键转发到新的窗口。

    def _release_held(self, held):
        self._release_message(*held[:4])
        held[-1].set()

    def release(self, key):
        with self._lock:
            held = self._held.pop(key, None)
            if held:
                self._release_held(held)

    def reset(self):
        self._cancel.set()
        with self._lock:
            for held in self._held.values():
                self._release_held(held)
            self._held.clear()
