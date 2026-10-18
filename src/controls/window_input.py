"""只向选中窗口发送输入消息，不操作前台窗口或系统光标。"""
import threading
import time

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
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

ELEVATION_MESSAGE = ('游戏以管理员权限运行，而 ok-zzz 未以管理员身份启动：Windows 会拦截发往游戏的点击与按键，'
                     '菜单操作无法生效。请关闭 ok-zzz 后右键「以管理员身份运行」。')


def _process_elevated(pid=None):
    import win32security
    handle = win32api.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid) if pid else win32api.GetCurrentProcess()
    try:
        token = win32security.OpenProcessToken(handle, win32con.TOKEN_QUERY)
        return bool(win32security.GetTokenInformation(token, win32security.TokenElevation))
    finally:
        if pid:
            win32api.CloseHandle(handle)


def input_blocked_by_elevation(hwnd):
    """Windows UIPI drops window messages and SendInput from a non-elevated process to an elevated one."""
    if not hwnd:
        return False
    try:
        import win32process
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return not _process_elevated() and _process_elevated(pid)
    except Exception:
        return False  # Unknown: let the task try and report its own failures.


class WindowMessageInput(PcButtonController):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.position = Point(960, 540)
        self._lock = threading.RLock()
        self._held = {}
        # reset()（停止、暂停、窗口切换）递增代际；进行中的调用在下一个检查点退出，
        # 之后的新调用照常执行。不用单个取消 Event：下一次调用 clear() 会吞掉
        # 另一线程刚发出的 reset()，让已释放的按键残留。
        self._epoch = 0

    def target(self):
        hwnd = self.window.get_hwnd()
        return hwnd if hwnd and self.window.is_win_valid else None

    def _valid(self, hwnd, epoch):
        return bool(hwnd and epoch == self._epoch and self.target() == hwnd)

    def _pause(self, seconds, epoch):
        """可被 reset() 提前打断的等待（20 ms 粒度）。"""
        deadline = time.monotonic() + max(0, float(seconds))
        while epoch == self._epoch:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(.02, remaining))

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
        epoch = self._epoch
        hwnd, point = self.target(), self._point(pos)
        if point is None or not self._valid(hwnd, epoch):
            return False
        try:
            self._post(hwnd, win32con.WM_MOUSEMOVE, 0, self.pack(*point))
            return True
        except Exception:
            log.warning('后台鼠标消息发送失败', exc_info=True)
            return False

    def click(self, pos=None, duration=.02, alt=False, button='left'):
        epoch = self._epoch
        hwnd, point = self.target(), self._point(pos)
        if point is None or not self._valid(hwnd, epoch):
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
            self._pause(.04, epoch)
            if not self._valid(hwnd, epoch):
                return False
            self._post(hwnd, down, flag, coordinates)
            pressed = True
            self._pause(max(.001, duration), epoch)
            return self._valid(hwnd, epoch)
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
        epoch = self._epoch
        hwnd = self.target()
        first, last = self._point(start), self._point(end)
        if first is None or last is None or not self._valid(hwnd, epoch):
            return False
        pressed = False
        coordinates = self.pack(*first)
        try:
            self.activate(hwnd)
            self._post(hwnd, win32con.WM_MOUSEMOVE, 0, coordinates)
            self._pause(.04, epoch)
            if not self._valid(hwnd, epoch):
                return False
            self._post(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, coordinates)
            pressed = True
            steps = max(1, int(max(0, duration) / .02))
            for index in range(1, steps + 1):
                if not self._valid(hwnd, epoch):
                    return False
                ratio = index / steps
                coordinates = self.pack(first[0] + (last[0] - first[0]) * ratio,
                                        first[1] + (last[1] - first[1]) * ratio)
                self._post(hwnd, win32con.WM_MOUSEMOVE, win32con.MK_LBUTTON, coordinates)
                self._pause(max(0, duration) / steps, epoch)
            return True
        except Exception:
            log.warning('后台拖拽消息发送失败', exc_info=True)
            return False
        finally:
            if pressed:
                self._release_message(hwnd, win32con.WM_LBUTTONUP, 0, coordinates)
            record_event('window_input', action='drag', hwnd=hwnd)

    def scroll(self, down, pos=None):
        epoch = self._epoch
        hwnd, point = self.target(), self._point(pos)
        if point is None or not self._valid(hwnd, epoch):
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
        epoch = self._epoch
        hwnd = self.target()
        if not self._valid(hwnd, epoch):
            return False
        try:
            self.activate(hwnd)
            encoded = str(text).encode('utf-16-le')
            for index in range(0, len(encoded), 2):
                if not self._valid(hwnd, epoch):
                    return False
                self._post(hwnd, win32con.WM_CHAR, int.from_bytes(encoded[index:index+2], 'little'))
                self._pause(max(0, interval), epoch)
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
        epoch = self._epoch
        hwnd = self.target()
        if not self._valid(hwnd, epoch):
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
                if not self._valid(hwnd, epoch):
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
        with self._lock:
            self._epoch += 1
            for held in self._held.values():
                self._release_held(held)
            self._held.clear()
