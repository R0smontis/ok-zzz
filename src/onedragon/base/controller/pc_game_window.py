# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: one_dragon/base/controller/pc_game_window.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
import ctypes
from ctypes.wintypes import RECT

import pyautogui
import win32ui
import win32gui
from pygetwindow import Win32Window

from onedragon.base.geometry.point import Point
from onedragon.base.geometry.rectangle import Rect
from onedragon.utils.log_utils import log
from src.frame_geometry import FrameGeometry


class PcGameWindow:

    def __init__(self,
                 standard_width: int = 1920,
                 standard_height: int = 1080):
        self.win_title: str | None = None
        self.standard_width: int = standard_width
        self.standard_height: int = standard_height
        self.standard_game_rect: Rect = Rect(0, 0, standard_width, standard_height)

        self._win: Win32Window | None = None
        self._hWnd = None
        self.window_provider = None

    def _clear_cached_window(self) -> None:
        self._win = None
        self._hWnd = None

    def init_win(self) -> None:
        """
        初始化窗口
        :return:
        """
        if self.window_provider is not None:
            # ok-script is authoritative: capture and input must use the same
            # selected handle, including after the game restarts.
            hwnd = self.window_provider()
            if not hwnd or not ctypes.windll.user32.IsWindow(hwnd):
                self._clear_cached_window()
                return
            if hwnd != self._hWnd:
                self._win = Win32Window(hwnd)
                self._hWnd = hwnd
            return
        if self.win_title is None:
            return

        windows = pyautogui.getWindowsWithTitle(self.win_title)
        if len(windows) > 0:
            for win in windows:
                if win.title == self.win_title:
                    self._win = win
                    self._hWnd = win._hWnd
        else:
            self._win = None
            self._hWnd = None

    def update_win_title(self, new_title: str) -> None:
        """
        更新窗口标题并清除缓存的窗口句柄
        :param new_title: 新的窗口标题
        """
        if self.win_title != new_title:
            self.win_title = new_title
            self._clear_cached_window()

    def refresh_win(self) -> None:
        self._clear_cached_window()
        self.init_win()

    def get_win(self) -> Win32Window | None:
        if self.window_provider is not None or self._win is None:
            self.init_win()
        return self._win

    def get_hwnd(self) -> int:
        if self.window_provider is not None or self._hWnd is None:
            self.init_win()
        return self._hWnd

    def _reset_cached_window(self) -> None:
        """清空缓存窗口对象与句柄，触发后续重新查找窗口。"""
        self._win = None
        self._hWnd = None

    @staticmethod
    def _try_get_client_rect(hwnd: int) -> tuple[bool, RECT]:
        client_rect = RECT()
        got_rect = ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(client_rect)) != 0
        return got_rect, client_rect

    @staticmethod
    def _is_valid_client_rect(got_rect: bool, client_rect: RECT) -> bool:
        return got_rect and client_rect.right > 0 and client_rect.bottom > 0

    @property
    def is_win_valid(self) -> bool:
        """
        当前窗口是否正常
        :return:
        """
        win = self.get_win()
        hwnd = self.get_hwnd()
        return win is not None and hwnd is not None and ctypes.windll.user32.IsWindow(hwnd) != 0

    @property
    def is_win_active(self) -> bool:
        """
        是否当前激活的窗口
        :return:
        """
        hwnd = self.get_hwnd()
        return bool(hwnd and win32gui.GetForegroundWindow() == hwnd)

    @property
    def is_win_scale(self) -> bool:
        """
        当前窗口是否缩放
        :return:
        """
        win_rect = self.win_rect
        if win_rect is None:
            return False
        else:
            return not (win_rect.width == self.standard_width and win_rect.height == self.standard_height)

    def active(self) -> bool:
        """
        显示并激活当前窗口
        :return:
        """
        win = self.get_win()
        if win is None:
            return False
        if self.is_win_active:
            return True

        try:
            win.restore()
            win.activate()
            return True
        except Exception as error:
            if getattr(error, 'args', None) and '1400' in str(error.args[0]):
                log.warning('无效的窗口句柄，尝试重置窗口')
                self._reset_cached_window()
                return False
            if isinstance(error, win32ui.error):
                log.error('激活窗口失败', exc_info=True)
                return False

            try:
                # 直接 activate 偶发失败，最小化再恢复可提高成功率
                win.minimize()
                win.restore()
                win.activate()
                return True
            except Exception as fallback_error:
                if getattr(fallback_error, 'args', None) and '1400' in str(fallback_error.args[0]):
                    log.warning('无效的窗口句柄，尝试重置窗口')
                    self._reset_cached_window()
                    return False
                log.error('切换到游戏窗口失败', exc_info=True)
                return False

    @property
    def win_rect(self) -> Rect | None:
        """
        获取游戏窗口在桌面上面的位置
        Win32Window 里是整个window的信息 参考源码获取里面client部分的
        :return: 游戏窗口信息
        """
        win = self.get_win()
        hwnd = self.get_hwnd()
        if win is None or hwnd is None:
            return None

        got_rect, client_rect = self._try_get_client_rect(hwnd)

        # 句柄失效时重置缓存并重试一次，避免永久复用坏句柄
        if not got_rect and ctypes.windll.user32.IsWindow(hwnd) == 0:
            log.warning('检测到失效窗口句柄，重置缓存后重试')
            self._reset_cached_window()
            win = self.get_win()
            hwnd = self.get_hwnd()
            if win is None or hwnd is None:
                return None
            got_rect, client_rect = self._try_get_client_rect(hwnd)

        # 查询坐标不恢复最小化窗口；没有客户区时等待有效截图。
        if not self._is_valid_client_rect(got_rect, client_rect):
            return None

        left_top_pos = ctypes.wintypes.POINT(client_rect.left, client_rect.top)
        ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(left_top_pos))
        return Rect(left_top_pos.x, left_top_pos.y, left_top_pos.x + client_rect.right, left_top_pos.y + client_rect.bottom)

    def get_scaled_game_pos(self, game_pos: Point) -> Point | None:
        """
        获取当前分辨率下游戏窗口里的坐标
        :param game_pos: 默认分辨率下的游戏窗口里的坐标
        :return: 当前分辨率下的游戏窗口里坐标
        """
        win = self.get_win()
        rect = self.win_rect
        if win is None or rect is None:
            return None
        if not self.is_valid_game_pos(game_pos, self.standard_game_rect) or rect.width <= 0 or rect.height <= 0:
            return None
        transform = FrameGeometry(rect.width, rect.height, self.standard_width, self.standard_height)
        return Point(*transform.to_client(game_pos.x, game_pos.y))

    def is_valid_game_pos(self, s_pos: Point, rect: Rect = None) -> bool:
        """
        判断游戏中坐标是否在游戏窗口内
        :param s_pos: 游戏中坐标 已经缩放
        :param rect: 窗口位置信息
        :return: 是否在游戏窗口内
        """
        if rect is None:
            rect = self.standard_game_rect
        return 0 <= s_pos.x < rect.width and 0 <= s_pos.y < rect.height

    def game2win_pos(self, game_pos: Point) -> Point | None:
        """
        获取在屏幕中的坐标
        :param game_pos: 默认分辨率下的游戏窗口里的坐标
        :return: 当前分辨率下的屏幕中的坐标
        """
        rect = self.win_rect
        if rect is None:
            return None
        gp: Point | None = self.get_scaled_game_pos(game_pos)
        # 缺少一个屏幕边界判断 游戏窗口拖动后可能会超出整个屏幕
        return rect.left_top + gp if gp is not None else None
