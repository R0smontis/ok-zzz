import logging
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtWidgets import QApplication



def test_installed_runtime_preserves_settings_and_refreshes_assets(tmp_path, monkeypatch):
    from src.runtime.startup import prepare_runtime_directory
    from onedragon.utils import os_utils
    installation = tmp_path / 'Program Files' / 'ok-zzz'
    installation.mkdir(parents=True)
    exe = installation / 'ok-zzz.exe'
    exe.write_bytes(b'')
    for name, content in {'config/00/game.yml': 'game_path: custom',
                          'configs/devices.json': '{"selected": "saved"}',
                          'config/auto_battle/default.sample.yml': 'template: true',
                          'assets/game_data/data.yml': 'old resource'}.items():
        path = installation / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(exe))
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'user'))
    monkeypatch.chdir(tmp_path)
    previous = os_utils._work_dir
    try:
        work = prepare_runtime_directory()
        assert os_utils.get_work_dir() == str(work.resolve())
        game = work / 'config/00/game.yml'
        game.write_text('game_path: changed', encoding='utf-8')
        downloaded = work / 'assets/models/downloaded/model.onnx'
        downloaded.parent.mkdir(parents=True)
        downloaded.write_bytes(b'downloaded model')
        (installation / 'assets/game_data/data.yml').write_text('updated resource', encoding='utf-8')
        prepare_runtime_directory()
        assert game.read_text(encoding='utf-8') == 'game_path: changed'
        assert (work / 'configs/devices.json').read_text(encoding='utf-8') == '{"selected": "saved"}'
        assert (work / 'assets/game_data/data.yml').read_text(encoding='utf-8') == 'updated resource'
        assert downloaded.read_bytes() == b'downloaded model'
        assert (installation / 'config/00/game.yml').read_text(encoding='utf-8') == 'game_path: custom'
        from src.runtime.startup import ensure_output_streams
        monkeypatch.setattr(sys, 'stdout', None)
        monkeypatch.setattr(sys, 'stderr', None)
        ensure_output_streams()
        stream = sys.stdout
        try:
            print('PER_USER_STARTUP_OK')
            assert (work / 'logs/startup.log').read_text(encoding='utf-8') == 'PER_USER_STARTUP_OK\n'
        finally:
            stream.close()
        assert not (installation / 'logs').exists()
    finally:
        os_utils.set_work_dir(previous)


def test_source_startup_keeps_project_directory(monkeypatch, tmp_path):
    import os
    from src.runtime.startup import prepare_runtime_directory
    monkeypatch.setattr(sys, 'frozen', False, raising=False)
    monkeypatch.chdir(tmp_path)
    assert prepare_runtime_directory() is None
    assert os.getcwd() == str(tmp_path)

def test_windowed_startup_keeps_diagnostics_with_missing_stdio(tmp_path, monkeypatch):
    from src.runtime.startup import ensure_output_streams
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
    from src.runtime.startup import ensure_output_streams
    output, error = Mock(), Mock()
    monkeypatch.setattr(sys, 'stdout', output)
    monkeypatch.setattr(sys, 'stderr', error)
    ensure_output_streams()
    assert sys.stdout is output and sys.stderr is error


def test_standalone_update_has_no_worker_or_error(monkeypatch):
    from src.runtime.startup import install_update_compat
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
    from src.runtime.startup import install_update_compat
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
    from src.diagnostics.recorder import recorder
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
    stop_recording.assert_called_once_with('程序退出', wait=True)


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
