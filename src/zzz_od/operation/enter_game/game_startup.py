# -*- coding: utf-8 -*-
"""Whether an open game window still has to go through the enter-game flow.

ok-script launches the game itself before a task starts, so tasks find a ready window while the game
is still on its splash, loading or title screens. Upstream OneDragon always ran EnterGame right after
launching; these checks restore that for a freshly started game process.
"""
import time

STATUS_AT_TITLE: str = '游戏停在标题画面，先登录'
STATUS_STARTING: str = '游戏刚启动，等待进入游戏'

STARTUP_SECONDS: float = 300
"""A younger game process may still be starting up; it has to reach the game once before tasks act."""

TITLE_STATUS_WORDS: tuple[str, ...] = ('加载配置数据中', '版本校对中', '登录游戏服务器中', '资源下载中')
"""Shown where the enter button will appear, while the title is still loading."""


def at_title_screen(ctx, screen) -> bool:
    """The title shows 「点击进入游戏」 (keyboard prompts) or 「进入游戏」 (controller prompts) at the bottom,
    or one of its loading states before the button appears."""
    if screen is None or getattr(ctx, 'ocr_service', None) is None:
        return False
    area = ctx.screen_loader.get_area('打开游戏', '进入游戏点击后状态')
    rows = ctx.ocr_service.get_ocr_result_list(image=screen, rect=area.rect)
    words = [str(r.data).replace(' ', '') for r in rows] if isinstance(rows, (list, tuple)) else []
    return any(word.endswith('进入游戏') or any(status in word for status in TITLE_STATUS_WORDS)
               for word in words)


def _game_process(ctx) -> tuple[int, float] | None:
    """(pid, seconds since the process started) of the bound game window; None when unknown."""
    try:
        import psutil
        import win32process
        hwnd = ctx.controller.game_win.get_hwnd()
        if not isinstance(hwnd, int) or hwnd <= 0:
            return None
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return pid, max(0.0, time.time() - psutil.Process(pid).create_time())
    except Exception:
        return None


def startup_seconds(ctx) -> float | None:
    """Age of a recently started game process that has not reached the game yet; None otherwise."""
    process = _game_process(ctx)
    if process is None:
        return None
    pid, age = process
    if age >= STARTUP_SECONDS or getattr(ctx, 'entered_game_pid', None) == pid:
        return None
    return age


def mark_game_entered(ctx) -> None:
    """The current game process has reached the game; later tasks trust its screen."""
    process = _game_process(ctx)
    if process is not None:
        ctx.entered_game_pid = process[0]


def in_game_screen(ctx, screen) -> bool:
    """Whether the screen matches a known in-game screen (the title and startup screens have no id marks)."""
    if screen is None:
        return False
    try:
        from onedragon.base.screen import screen_utils
        return screen_utils.get_match_screen_name(ctx, screen) is not None
    except Exception:
        return False
