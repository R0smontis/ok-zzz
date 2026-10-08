import logging
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtWidgets import QApplication


def test_windowed_startup_keeps_diagnostics_with_missing_stdio(tmp_path, monkeypatch):
    from src.startup_runtime import ensure_output_streams
    monkeypatch.setattr(sys, 'stdout', None)
    monkeypatch.setattr(sys, 'stderr', None)
    path = tmp_path / 'logs/startup.log'
    ensure_output_streams(path)
    stream = sys.stdout
    try:
        print('STARTUP_OK')
        handler = logging.StreamHandler(sys.stderr)
        handler.handle(logging.LogRecord('startup', logging.ERROR, __file__, 1, 'TEST_ERROR', (), None))
        stream.flush()
        assert path.read_text(encoding='utf-8') == 'STARTUP_OK\nTEST_ERROR\n'
    finally:
        stream.close()


def test_existing_console_output_is_preserved(monkeypatch):
    from src.startup_runtime import ensure_output_streams
    output, error = Mock(), Mock()
    monkeypatch.setattr(sys, 'stdout', output)
    monkeypatch.setattr(sys, 'stderr', error)
    ensure_output_streams()
    assert sys.stdout is output and sys.stderr is error


def test_standalone_update_has_no_worker_or_error(monkeypatch):
    from src.startup_runtime import install_update_compat
    from ok.ui.qt.about.UpdateCard import UpdateCard
    from ok.ui.qt.MainWindow import MainWindow
    qt = QApplication.instance() or QApplication([])
    install_update_compat()
    module = SimpleNamespace(pyappify_version=None, get_version_list=Mock(side_effect=RuntimeError('unsupported')))
    card = UpdateCard('0.1.0', module)
    try:
        card.check_for_updates()
        window = SimpleNamespace(about_tab=SimpleNamespace(update_card=card), update_check_timer=None)
        MainWindow._schedule_update_check(window)
        module.get_version_list.assert_not_called()
        assert window.update_check_timer is None
        assert not card.check_button.isEnabled()
        assert not card.update_button.isEnabled()
        assert not card._busy
        assert '独立安装版' in card.status_label.text()
    finally:
        card.deleteLater()
        qt.processEvents()


def test_launcher_managed_update_remains_available(monkeypatch):
    from src.startup_runtime import install_update_compat
    from ok.ui.qt.about.UpdateCard import UpdateCard
    qt = QApplication.instance() or QApplication([])
    install_update_compat()
    module = SimpleNamespace(pyappify_version='1.0', get_version_list=Mock(return_value=[]))
    card = UpdateCard('0.1.0', module)
    try:
        operations = []
        monkeypatch.setattr(card, '_run_in_background', lambda operation, *_: operations.append(operation))
        assert card.check_button.isEnabled()
        card.check_for_updates()
        assert len(operations) == 1
        assert operations[0]() == []
        module.get_version_list.assert_called_once()
    finally:
        card.deleteLater()
        qt.processEvents()


def test_exit_callback_stops_existing_resources_once(monkeypatch):
    from ok import og
    from ok.util.handler import ExitEvent
    from src.globals import Globals
    from src.diagnostics import recorder
    task = SimpleNamespace(_stop_engine=Mock())
    context = SimpleNamespace(run_context=SimpleNamespace(stop_running=Mock()), after_app_shutdown=Mock())
    globals_ = Globals.__new__(Globals)
    globals_._shutdown_lock = threading.Lock()
    globals_._stopped = False
    globals_._context = context
    monkeypatch.setattr(og, 'executor', SimpleNamespace(trigger_tasks=[task]))
    stop_recording = Mock()
    monkeypatch.setattr(recorder, 'stop', stop_recording)
    event = ExitEvent()
    event.bind_stop(globals_)
    event.set()
    globals_.stop()
    task._stop_engine.assert_called_once()
    context.run_context.stop_running.assert_called_once()
    context.after_app_shutdown.assert_called_once()
    stop_recording.assert_called_once_with('程序退出')


def test_uninitialized_context_is_not_created_during_exit(monkeypatch):
    from zzz_od.context.zzz_context import ZContext
    context = ZContext.__new__(ZContext)
    context.after_app_shutdown()
    assert '_auto_battle_context' not in context.__dict__


def test_audio_stop_precedes_executor_shutdown(monkeypatch):
    from zzz_od.auto_battle import auto_battle_dodge_context as module
    order = []
    dodge = module.AutoBattleDodgeContext.__new__(module.AutoBattleDodgeContext)
    dodge._audio_recorder = SimpleNamespace(stop_running=lambda: order.append('audio_stop'))
    dodge.event_listener = Mock()
    executor = Mock()
    executor.shutdown.side_effect = lambda **_: order.append('pool_shutdown')
    monkeypatch.setattr(module, '_dodge_check_executor', executor)
    dodge.after_app_shutdown()
    assert order == ['audio_stop', 'pool_shutdown']
    assert dodge.event_listener is None
