"""在自建隐藏窗口验证 Windows 消息输入，不操作真实游戏。"""
import uuid
from types import SimpleNamespace

import win32con
import win32gui
import win32api

from onedragon.base.geometry.point import Point
from src.controls.window_input import WindowMessageInput


def check_background_input():
    received = []
    name = 'OkZzzInputCheck_' + uuid.uuid4().hex
    instance = win32api.GetModuleHandle(None)
    def procedure(hwnd, message, wparam, lparam):
        if message in (win32con.WM_MOUSEMOVE, win32con.WM_LBUTTONDOWN, win32con.WM_LBUTTONUP,
                       win32con.WM_MOUSEWHEEL, win32con.WM_CHAR, win32con.WM_KEYDOWN, win32con.WM_KEYUP):
            received.append((message, wparam, lparam))
            return 0
        # WA_ACTIVE 是后台提示，不让测试窗口获取键盘焦点。
        if message == win32con.WM_ACTIVATE:
            return 0
        return win32gui.DefWindowProc(hwnd, message, wparam, lparam)
    cls = win32gui.WNDCLASS()
    cls.hInstance, cls.lpszClassName, cls.lpfnWndProc = instance, name, procedure
    win32gui.RegisterClass(cls)
    hwnd = None
    try:
        hwnd = win32gui.CreateWindowEx(0, name, name, win32con.WS_POPUP, 0, 0, 1920, 1080, 0, 0, instance, None)
        window = SimpleNamespace(get_hwnd=lambda: hwnd, is_win_valid=True,
                                 get_scaled_game_pos=lambda p: p)
        backend = WindowMessageInput(window)
        assert backend.click(Point(120,240), duration=0)
        assert backend.drag(Point(120,240), Point(360,480), duration=0)
        assert backend.scroll(1, Point(120,240))
        assert backend.input_text('TEST', interval=0)
        backend.tap('space')
        backend.reset()
        win32gui.PumpWaitingMessages()
        expected = backend.pack(120,240)
        assert (win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, expected) in received
        assert (win32con.WM_LBUTTONUP, 0, backend.pack(360,480)) in received
        assert any(msg == win32con.WM_MOUSEWHEEL and wp == ((-120 & 0xffff)<<16) for msg,wp,_ in received)
        # 消息泵还会把后面的 Space 键翻译为 WM_CHAR。
        assert ''.join(chr(wp) for msg,wp,_ in received if msg == win32con.WM_CHAR).startswith('TEST')
        assert any(msg == win32con.WM_KEYDOWN and wp == win32con.VK_SPACE for msg,wp,_ in received)
        assert any(msg == win32con.WM_KEYUP and lp & (1<<31) for msg,_,lp in received)
        assert not win32gui.IsWindowVisible(hwnd)
        assert win32gui.GetForegroundWindow() != hwnd
        return {'native_receiver': 'passed', 'target': 'own hidden window',
                'click_drag_wheel_text_keyboard': 'passed', 'game_input': 'none'}
    finally:
        if hwnd:
            win32gui.DestroyWindow(hwnd)
        win32gui.UnregisterClass(name, instance)
