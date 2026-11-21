"""Standalone GUI startup: diagnostic streams and supported update controls."""
import functools
import logging
import sys
import threading
import time
from pathlib import Path

import win32gui

logger = logging.getLogger('ok')


def prepare_runtime_directory():
    """Keep installed binaries read-only; seed per-user resources before imports."""
    import os
    import shutil

    if not getattr(sys, 'frozen', False):
        return None
    installation = Path(sys.executable).resolve().parent
    local_data = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local')
    work = local_data / 'ok-zzz'
    work.mkdir(parents=True, exist_ok=True)
    # Configs are copied only when absent, including settings from older releases.
    # Bundled assets refresh on upgrade; downloaded models remain untouched.
    for folder in ('config', 'configs', 'assets', 'icons', 'i18n'):
        source = installation / folder
        if not source.is_dir():
            continue
        for original in source.rglob('*'):
            if not original.is_file():
                continue
            target = work / folder / original.relative_to(source)
            if target.exists():
                if folder in ('config', 'configs'):
                    continue
                old, new = target.stat(), original.stat()
                if old.st_size == new.st_size and old.st_mtime_ns == new.st_mtime_ns:
                    continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, target)
    from onedragon.utils import os_utils
    os_utils.set_work_dir(work)
    os.chdir(work)
    return work


def ensure_output_streams(output_path=None):
    # Windowed PyInstaller bootloaders intentionally provide no stdio handles.
    # Dependencies still print and create StreamHandlers during initialization.
    if output_path is None and sys.stdout is not None and sys.stderr is not None:
        return
    path = Path(output_path or 'logs/startup.log')
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open('a', encoding='utf-8', buffering=1)
    if output_path is not None or sys.stdout is None:
        sys.stdout = stream
    if output_path is not None or sys.stderr is None:
        sys.stderr = stream


def supports_online_updates(module):
    return bool(getattr(module, 'pyappify_version', None)
                and callable(getattr(module, 'get_version_list', None)))


STATUS_UNBROKEN_WIDTH = 160
"""Status texts up to this width (e.g. 「已是最新版本。」) never wrap."""

LAUNCHER_MISSING_MARKER = 'PyAppify executable was not found'
LAUNCHER_MISSING_HINT = ('检查更新失败：未找到启动器 ok-zzz.exe，可能被安全软件隔离；'
                         '请恢复安装目录中的该文件或重新安装')


def update_status_text(message):
    """Replace the launcher lookup exception with an actionable explanation."""
    if LAUNCHER_MISSING_MARKER in str(message):
        return LAUNCHER_MISSING_HINT
    return message


def fit_update_status(card):
    """Give the about page's update status room before the spacer takes it.

    The framework puts a stretch-1 spacer after a word-wrapping status label; the spacer took all
    free width and squeezed the label to a few characters, so 「已是最新版本。」 broke into lines.
    """
    from PySide6.QtWidgets import QSpacerItem
    layout, label = card.controls_layout, card.status_label
    index = layout.indexOf(label)
    if index < 0:
        return
    layout.setStretch(index, 1)
    for position in range(index + 1, layout.count()):
        if isinstance(layout.itemAt(position), QSpacerItem):
            layout.setStretch(position, 0)
            break
    original_set = card._set_status

    def set_status(message, error=False):
        message = update_status_text(message)
        original_set(message, error)
        width = label.fontMetrics().horizontalAdvance(str(message)) + 2
        label.setMinimumWidth(min(width, STATUS_UNBROKEN_WIDTH, label.maximumWidth()))

    card._set_status = set_status
    set_status(label.text())


def install_update_compat():
    from ok.ui.qt.about.UpdateCard import UpdateCard
    from ok.ui.qt.MainWindow import MainWindow
    if getattr(UpdateCard, '_zzz_standalone_updates', False):
        return
    original_init = UpdateCard.__init__
    original_check = UpdateCard.check_for_updates
    original_schedule = MainWindow._schedule_update_check

    def standalone_status(card):
        card._set_status('独立安装版：请下载新版本后更新')
        card.check_button.setEnabled(False)
        card.test_version_checkbox.setEnabled(False)
        card.update_button.setEnabled(False)

    @functools.wraps(original_init)
    def init(card, *args, **kwargs):
        original_init(card, *args, **kwargs)
        fit_update_status(card)
        if not supports_online_updates(card.pyappify_module):
            standalone_status(card)

    @functools.wraps(original_check)
    def check(card):
        if not supports_online_updates(card.pyappify_module):
            standalone_status(card)
            return
        return original_check(card)

    @functools.wraps(original_schedule)
    def schedule(window):
        card = window.about_tab.update_card
        if card is not None and not supports_online_updates(card.pyappify_module):
            logging.getLogger('ok').info('独立安装版未配置在线更新服务，已跳过自动更新检查')
            return
        return original_schedule(window)

    UpdateCard.__init__ = init
    UpdateCard.check_for_updates = check
    MainWindow._schedule_update_check = schedule
    UpdateCard._zzz_standalone_updates = True


def install_launcher_shutdown_compat():
    """Do not terminate the same launcher's PID again after a confirmed exit."""
    import pyappify

    original = getattr(pyappify, 'kill_pyappify', None)
    if not callable(original) or getattr(original, '_zzz_idempotent_shutdown', False) is True:
        return
    lock = threading.Lock()
    exited = False

    @functools.wraps(original)
    def shutdown(*args, **kwargs):
        nonlocal exited
        with lock:
            if exited:
                return True
            result = original(*args, **kwargs)
            exited = result is True
            return result

    shutdown._zzz_idempotent_shutdown = True
    pyappify.kill_pyappify = shutdown


def _started_window_min_size(controller):
    """Use the app's configured capture minimum, falling back to the framework's."""
    fallback = getattr(controller, 'STARTED_WINDOW_MIN_SIZE', (100, 100))
    config = getattr(controller, 'config', None) or {}
    supported = config.get('supported_resolution') or {}
    configured = supported.get('min_size') if hasattr(supported, 'get') else None
    if configured:
        try:
            width, height = int(configured[0]), int(configured[1])
        except (IndexError, KeyError, TypeError, ValueError):
            pass
        else:
            if width > 0 and height > 0:
                return width, height
    return fallback


def _started_window_target(hwnd_window):
    """Return (hwnd, client width, client height) once the window can be captured.

    Hidden and minimized windows still have a client rect, so they must be rejected
    explicitly; the game creates a small hidden client area before its real window appears.
    Foreground state is deliberately irrelevant: background capture is supported.
    """
    hwnd = getattr(hwnd_window, 'hwnd', 0)
    if not hwnd:
        return None
    try:
        if not win32gui.IsWindow(hwnd):
            return None
        if not win32gui.IsWindowVisible(hwnd):
            return None
        if win32gui.IsIconic(hwnd):
            return None
        left, top, right, bottom = win32gui.GetClientRect(hwnd)
    except Exception as error:
        logger.debug(f'cannot use started window {hwnd}: {error}')
        return None
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        return None
    return hwnd, width, height


def _wait_until_started_window_stable(controller):
    from ok import og
    from ok.core.events import communicate

    wait_until = time.monotonic() + controller.start_timeout
    stable_target = None
    stable_since = None
    min_width, min_height = _started_window_min_size(controller)

    while not controller.exit_event.is_set():
        hwnd_window = getattr(getattr(og, 'device_manager', None), 'hwnd_window', None)
        target = None
        if hwnd_window is not None:
            hwnd_window.do_update_window_size()
            target = _started_window_target(hwnd_window)
        if target is not None and target[1] >= min_width and target[2] >= min_height:
            now = time.monotonic()
            if target != stable_target:
                logger.info(f'waiting for started window to stabilize, hwnd {target[0]} '
                            f'client {target[1]}x{target[2]}')
                stable_target = target
                stable_since = now
            elif now - stable_since >= controller.STARTED_WINDOW_STABLE_SECONDS:
                logger.info(f'started window stable for {controller.STARTED_WINDOW_STABLE_SECONDS}s: '
                            f'hwnd {target[0]} client {target[1]}x{target[2]}')
                return True
        else:
            stable_target = None
            stable_since = None

        remaining_time = wait_until - time.monotonic()
        if remaining_time <= 0:
            communicate.starting_emulator.emit(True, controller.tr('Start game timeout!'), 0)
            return False
        time.sleep(controller.STARTED_WINDOW_POLL_INTERVAL)
    return False


def install_started_window_guard():
    """Refuse to hand hidden or minimized startup windows to the capture backend."""
    from ok.core.start_controller import StartController

    current = StartController._wait_until_started_window_stable
    if getattr(current, '_zzz_started_window_guard', False):
        return

    @functools.wraps(current)
    def wait_until_started_window_stable(controller):
        return _wait_until_started_window_stable(controller)

    wait_until_started_window_stable._zzz_started_window_guard = True
    StartController._wait_until_started_window_stable = wait_until_started_window_stable
