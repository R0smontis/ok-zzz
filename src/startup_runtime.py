"""Standalone GUI startup: diagnostic streams and supported update controls."""
import functools
import logging
import sys
from pathlib import Path


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
