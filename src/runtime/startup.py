"""Standalone GUI startup: diagnostic streams and supported update controls."""
import functools
import logging
import sys
from pathlib import Path


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
