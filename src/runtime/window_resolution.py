"""Resize the game window for capture and put the player's own window mode back on exit.

The framework's ``HwndWindow.try_resize_to`` adds a caption and resizes the window. A Unity
fullscreen window ignores that: it keeps its fullscreen size, so a fullscreen game only lost its
borderless look while the client stayed at monitor size (verified live 2026-11-23: 3002x1842 on
a 3024x1898 display). Unity leaves fullscreen only through its own Alt+Enter handler, which also
accepts posted key messages while the game is in the background; after that the window accepts
an external resize and Unity stores the new size as its windowed size.

While loading and logging in, the game applies its in-game display setting again (seen live
about 22 s and 33 s after launch), which can turn a window that already passed the resolution
check back to fullscreen; a startup guard repeats the adjustment then. Exit restores the original
mode only while the window still has the size this module set, so a later manual change by the
player is kept.
"""
import functools
import threading
import time
from contextvars import ContextVar
from dataclasses import dataclass

import psutil
import win32api
import win32con
import win32gui
import win32process

from ok import Logger

logger = Logger.get_logger(__name__)

POLL_SECONDS = 0.05
TOGGLE_TIMEOUT = 3.0
SETTLE_TIMEOUT = 5.0
STABLE_SECONDS = 1.0
ATTEMPTS = 3
STARTUP_SECONDS = 90.0
"""Process age up to which the game may still re-apply its own fullscreen setting."""
STARTUP_REAPPLY_LIMIT = 4
"""Seen live: two re-applies during login (about 22 s and 33 s after launch)."""
EXIT_LOCK_TIMEOUT = 1.0
FULLSCREEN_RESIZE_TIMEOUT = 0.5
FULLSCREEN_TOGGLE_TIMEOUT = 1.0
SET_POS_FLAGS = win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE | win32con.SWP_NOOWNERZORDER


@dataclass
class Adjustment:
    hwnd: int
    fullscreen: bool
    window_rect: tuple
    maximized_placement: tuple | None = None
    target: tuple | None = None


_lock = threading.RLock()
_adjustment: Adjustment | None = None
_guard_stop: threading.Event | None = None
_check_standard_resolution = ContextVar('check_standard_resolution', default=True)
_NATIVE_RESOLUTION_APPS = frozenset(('auto_battle', 'dodge_assistant', 'commission_assistant'))


def should_check_standard_resolution():
    return _check_standard_resolution.get()


def _rect_size(rect):
    return rect[2] - rect[0], rect[3] - rect[1]


def _client_size(hwnd):
    return _rect_size(win32gui.GetClientRect(hwnd))


def _monitor(hwnd):
    info = win32api.GetMonitorInfo(win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONEAREST))
    return tuple(info['Monitor']), tuple(info['Work'])


def _maximized(hwnd):
    return win32gui.GetWindowPlacement(hwnd)[1] == win32con.SW_SHOWMAXIMIZED


def is_fullscreen(hwnd):
    """Exclusive or borderless fullscreen: the window is exactly its monitor and not maximized.

    This also matches a fullscreen window that only received a caption from the old framework
    resize; a maximized window extends past the monitor by its frame and stays windowed.
    """
    return tuple(win32gui.GetWindowRect(hwnd)) == _monitor(hwnd)[0] and not _maximized(hwnd)


def _post_alt_enter(hwnd):
    alt = win32api.MapVirtualKey(win32con.VK_MENU, 0) << 16
    enter = win32api.MapVirtualKey(win32con.VK_RETURN, 0) << 16
    alt_down, released = 1 << 29, (1 << 30) | (1 << 31)
    win32gui.PostMessage(hwnd, win32con.WM_SYSKEYDOWN, win32con.VK_MENU, 1 | alt | alt_down)
    win32gui.PostMessage(hwnd, win32con.WM_SYSKEYDOWN, win32con.VK_RETURN, 1 | enter | alt_down)
    win32gui.PostMessage(hwnd, win32con.WM_SYSKEYUP, win32con.VK_RETURN, 1 | enter | alt_down | released)
    win32gui.PostMessage(hwnd, win32con.WM_KEYUP, win32con.VK_MENU, 1 | alt | released)


def _cancelled(cancel):
    return cancel is not None and cancel.is_set()


def _wait(predicate, timeout, cancel=None):
    deadline = time.monotonic() + timeout
    while True:
        if predicate():
            return True
        if _cancelled(cancel) or time.monotonic() >= deadline:
            return False
        time.sleep(POLL_SECONDS)


def _choose_target(resize_to, frame, work):
    work_width, work_height = _rect_size(work)
    for width, height in resize_to:
        if width + frame[0] <= work_width and height + frame[1] <= work_height:
            return int(width), int(height)
    return None


def _set_client_size(hwnd, size, area):
    """Resize so the client is ``size``, centred in ``area`` with the caption kept on screen."""
    window, client = _rect_size(win32gui.GetWindowRect(hwnd)), _client_size(hwnd)
    width, height = size[0] + window[0] - client[0], size[1] + window[1] - client[1]
    area_width, area_height = _rect_size(area)
    x = area[0] + max(0, (area_width - width) // 2)
    y = area[1] + max(0, (area_height - height) // 2)
    win32gui.SetWindowPos(hwnd, 0, x, y, width, height, SET_POS_FLAGS)


def _settled(hwnd, size, cancel=None):
    """Wait until the windowed client keeps ``size``; Unity reverts sizes it does not accept."""
    deadline = time.monotonic() + SETTLE_TIMEOUT
    since = None
    while time.monotonic() < deadline and not _cancelled(cancel):
        if not is_fullscreen(hwnd) and _client_size(hwnd) == size:
            since = time.monotonic() if since is None else since
            if time.monotonic() - since >= STABLE_SECONDS:
                return True
        else:
            since = None
        time.sleep(POLL_SECONDS)
    return False


def _remember(hwnd):
    global _adjustment
    previous = _adjustment
    if previous is not None and previous.hwnd == hwnd:
        return previous
    placement = win32gui.GetWindowPlacement(hwnd)
    maximized = placement if placement[1] == win32con.SW_SHOWMAXIMIZED else None
    _adjustment = Adjustment(hwnd, is_fullscreen(hwnd), tuple(win32gui.GetWindowRect(hwnd)), maximized)
    return _adjustment


def _enter_fullscreen(hwnd):
    """Alt+Enter back to fullscreen at monitor size.

    Unity enters fullscreen from its windowed size and stores it for the next Alt+Enter; give it
    the monitor size first so the player's saved fullscreen resolution stays unchanged.
    """
    monitor = _monitor(hwnd)[0]
    size = _rect_size(monitor)
    _set_client_size(hwnd, size, monitor)
    _wait(lambda: _client_size(hwnd) == size, FULLSCREEN_RESIZE_TIMEOUT)
    _post_alt_enter(hwnd)
    return _wait(lambda: is_fullscreen(hwnd), FULLSCREEN_TOGGLE_TIMEOUT)


def _resize_windowed(hwnd, resize_to, cancel):
    for attempt in range(1, ATTEMPTS + 1):
        if _cancelled(cancel):
            return None
        if is_fullscreen(hwnd):
            logger.info(f'游戏窗口为全屏，切换到窗口模式后调整分辨率（第 {attempt} 次）')
            _post_alt_enter(hwnd)
            if not _wait(lambda: not is_fullscreen(hwnd), TOGGLE_TIMEOUT, cancel):
                logger.warning('游戏未响应 Alt+Enter 退出全屏')
                continue
        if _maximized(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        window, client = _rect_size(win32gui.GetWindowRect(hwnd)), _client_size(hwnd)
        work = _monitor(hwnd)[1]
        target = _choose_target(resize_to, (window[0] - client[0], window[1] - client[1]), work)
        if target is None:
            logger.error(f'显示器可用区域放不下支持的分辨率 {list(resize_to)}')
            return None
        _set_client_size(hwnd, target, work)
        if _settled(hwnd, target, cancel):
            logger.info(f'游戏窗口已调整为 {target[0]}x{target[1]}')
            return target
        logger.warning(f'游戏窗口未保持 {target[0]}x{target[1]}，当前客户区 '
                       f'{"x".join(map(str, _client_size(hwnd)))}')
    return None


def adjust(hwnd, resize_to, cancel=None):
    """Bring the game into a windowed client from ``resize_to``; return that size or None."""
    with _lock:
        if _cancelled(cancel):
            return None
        record = _remember(hwnd)
        was_fullscreen = is_fullscreen(hwnd)
        target = _resize_windowed(hwnd, resize_to, cancel)
        if target is not None:
            record.target = target
        elif was_fullscreen and not is_fullscreen(hwnd):
            if _cancelled(cancel):
                # Shut down promptly and let the exit hook restore the mode.
                record.target = _client_size(hwnd)
            elif not _enter_fullscreen(hwnd):
                # Keep the window eligible for another restore on exit.
                record.target = _client_size(hwnd)
        return target


def _auto_resize_enabled(window):
    return bool(window.global_config.get_config('Basic Options').get('Auto Resize Game Window'))


def try_resize_to(window, resize_to):
    """Replacement for ``HwndWindow.try_resize_to`` with the same contract."""
    if not _auto_resize_enabled(window):
        return False
    hwnd = window.hwnd
    if not hwnd or window.window_width <= 0:
        return False
    try:
        target = adjust(hwnd, resize_to, getattr(window, 'app_exit_event', None))
    except win32gui.error as error:
        logger.error(f'调整游戏窗口失败：{error}')
        target = None
    window.do_update_window_size()
    if target is None:
        logger.error(f'resize hwnd failed: {window.width}x{window.height}')
        return False
    logger.info(f'resize hwnd success to {window.width}x{window.height}')
    return True


def _process_age(hwnd):
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return time.time() - psutil.Process(pid).create_time() if pid else None
    except (psutil.Error, OSError, win32gui.error):
        return None


def _stop_guard():
    global _guard_stop
    stop, _guard_stop = _guard_stop, None
    if stop is not None:
        stop.set()


def watch_startup(window, resize_to):
    """Re-adjust once more if a just-launched game switches itself back to fullscreen."""
    global _guard_stop
    hwnd = window.hwnd
    age = _process_age(hwnd) if hwnd else None
    if age is None or age >= STARTUP_SECONDS:
        return None
    _stop_guard()
    stop = _guard_stop = threading.Event()
    exit_event = getattr(window, 'app_exit_event', None)
    deadline = time.monotonic() + STARTUP_SECONDS - age

    def guard():
        reapplied = 0
        try:
            while not stop.wait(.5) and time.monotonic() < deadline and not _cancelled(exit_event):
                if not win32gui.IsWindow(hwnd) or window.hwnd != hwnd or not _auto_resize_enabled(window):
                    return
                if not is_fullscreen(hwnd):
                    continue
                if reapplied >= STARTUP_REAPPLY_LIMIT:
                    logger.warning('游戏启动期间多次恢复全屏，停止自动调整')
                    return
                reapplied += 1
                logger.info('游戏加载时恢复了全屏设置，重新调整窗口')
                if adjust(hwnd, resize_to, stop) is not None:
                    window.do_update_window_size()
        except win32gui.error as error:
            logger.warning(f'游戏启动窗口检查结束：{error}')

    thread = threading.Thread(target=guard, name='game_window_startup_guard', daemon=True)
    thread.start()
    return thread


def restore_game_window():
    """Put back the window mode and size from before the first adjustment."""
    global _adjustment
    _stop_guard()
    if not _lock.acquire(timeout=EXIT_LOCK_TIMEOUT):
        logger.warning('游戏窗口仍在调整中，退出时未恢复分辨率')
        return False
    try:
        record, _adjustment = _adjustment, None
        if record is None or record.target is None:
            return False
        hwnd = record.hwnd
        if not win32gui.IsWindow(hwnd) or win32gui.IsIconic(hwnd):
            return False
        if is_fullscreen(hwnd) or _client_size(hwnd) != record.target:
            logger.info('游戏窗口已被手动调整，退出时保持当前状态')
            return False
        if record.maximized_placement is not None:
            win32gui.SetWindowPlacement(hwnd, record.maximized_placement)
            return True
        if not record.fullscreen:
            left, top, right, bottom = record.window_rect
            win32gui.SetWindowPos(hwnd, 0, left, top, right - left, bottom - top, SET_POS_FLAGS)
            logger.info(f'已恢复游戏窗口 {right - left}x{bottom - top}')
            return True
        restored = _enter_fullscreen(hwnd)
        logger.info('已恢复游戏全屏' if restored else '已请求游戏恢复全屏')
        return restored
    except win32gui.error as error:
        logger.warning(f'恢复游戏窗口失败：{error}')
        return False
    finally:
        _lock.release()


def install_window_resolution():
    from ok import TriggerTask, og
    from ok.core.start_controller import StartController
    from ok.device.capture_methods.hwnd_window import HwndWindow

    if getattr(HwndWindow.try_resize_to, '_zzz_window_resolution', False) is not True:
        @functools.wraps(HwndWindow.try_resize_to)
        def resize(window, resize_to):
            return try_resize_to(window, resize_to)

        resize._zzz_window_resolution = True
        HwndWindow.try_resize_to = resize

    original_check = StartController.check_resolution
    if getattr(original_check, '_zzz_window_resolution', False) is True:
        return

    def requires_standard_resolution(task):
        return (task is not None and not isinstance(task, TriggerTask)
                and getattr(task, 'app_id', None) not in _NATIVE_RESOLUTION_APPS)

    original_start = StartController._do_start

    @functools.wraps(original_start)
    def start(controller, task=None, exit_after=False):
        executor = og.executor
        requested = task
        if isinstance(task, int):
            tasks = executor.onetime_tasks
            requested = tasks[task] if -len(tasks) <= task < len(tasks) else None
        elif task is None:
            requested = executor.current_task
        needs_check = requires_standard_resolution(requested) or any(
            getattr(candidate, 'enable_after_start', False) and requires_standard_resolution(candidate)
            for candidate in executor.get_all_tasks()
        )
        token = _check_standard_resolution.set(needs_check)
        try:
            return original_start(controller, task, exit_after)
        finally:
            _check_standard_resolution.reset(token)

    @functools.wraps(original_check)
    def check_resolution(controller):
        if not should_check_standard_resolution():
            # check_device_error already verified capture. These tasks normalize their own frames.
            _stop_guard()
            return None
        result = original_check(controller)
        window = getattr(getattr(og.device_manager, 'capture_method', None), 'hwnd_window', None)
        resize_to = (controller.config.get('supported_resolution') or {}).get('resize_to')
        record = _adjustment
        if (window is not None and resize_to and record is not None and record.hwnd == window.hwnd
                and record.target is not None and _auto_resize_enabled(window)):
            watch_startup(window, resize_to)
        return result

    check_resolution._zzz_window_resolution = True
    StartController._do_start = start
    StartController.check_resolution = check_resolution
