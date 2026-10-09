"""Real Qt recording buttons and passive task lifecycle; no game input."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QApplication
from qfluentwidgets import SwitchButton
from ok import og
from ok.ui.qt.tasks.TaskCard import TaskCard
from ok.util.config import Config

from src.diagnostics import recorder as diagnostics
from src.controls import user_input_trace
from src.tasks import diagnostic_task
from src.tasks.option_widgets import install_option_widgets

_QT_APP = None


@pytest.fixture
def recording_ui(tmp_path, monkeypatch):
    global _QT_APP
    _QT_APP = QApplication.instance() or QApplication([])
    install_option_widgets()
    rec = diagnostics.DiagnosticRecorder()
    monkeypatch.setattr(diagnostic_task, 'recorder', rec)
    monkeypatch.setattr(diagnostics, 'recorder', rec)
    monkeypatch.setattr(diagnostic_task.os_utils, 'get_work_dir', lambda: str(tmp_path))
    app = SimpleNamespace(tr=lambda text: text)
    monkeypatch.setattr(og, 'app', app)
    monkeypatch.setattr(og, 'config', {'gui_title': 'ok-zzz'})
    monkeypatch.setattr(og, 'my_app', SimpleNamespace(_context=None))
    input_factory = Mock(return_value=SimpleNamespace(start=Mock(), stop=Mock()))
    monkeypatch.setattr(user_input_trace, 'GameInputTrace', input_factory)
    others = [SimpleNamespace(name='副本', enabled=True, running=True)]
    executor = SimpleNamespace(scene=None, get_all_tasks=lambda: others,
                               interaction=SimpleNamespace(on_run=Mock()), enqueue_onetime_task=Mock(),
                               remove_onetime_task=Mock(), _wake_executor=Mock(), next_frame=Mock(), paused=False)
    task = diagnostic_task.DiagnosticRecordingTask(executor=executor, app=app)
    task.config = Config(type(task).__name__, task.default_config, folder=str(tmp_path), validator=task.validate)
    task.on_create()
    card = TaskCard(task, False)
    card.show()
    _QT_APP.processEvents()
    yield task, card, rec, executor, others, input_factory
    task.disable()
    rec.stop(wait=True)
    card.dispose()
    card.close()
    card.deleteLater()
    _QT_APP.processEvents()


def test_buttons_start_pause_resume_stop_and_save_without_pausing_game(recording_ui):
    task, card, recorder, executor, others, input_factory = recording_ui
    controls = card.recording_controls
    assert card.enable_button is None
    assert not any(button is not None and isinstance(button, SwitchButton) for button in card.all_buttons)
    assert [b.text() for b in (controls.start_button, controls.pause_button, controls.stop_button)] == [
        '开始录制', '暂停录制', '停止录制']
    assert task.config['录制时长秒'] == 0
    assert controls.start_button.isEnabled() and not controls.pause_button.isEnabled()
    controls.start_button.click()
    import time
    limit=time.monotonic()+3
    while input_factory.call_args is None and time.monotonic()<limit:
        time.sleep(.01)
    controls.refresh()
    assert task.enabled and recorder.active
    assert not controls.start_button.isEnabled() and controls.stop_button.isEnabled()
    folder = recorder.status['folder']
    controls.pause_button.click()
    assert task.enabled and recorder.paused
    assert controls.pause_button.text() == '继续录制'
    assert not task.should_trigger()
    controls.pause_button.click()
    assert recorder.active and not recorder.paused
    assert controls.pause_button.text() == '暂停录制'
    assert recorder.status['folder'] == folder
    enabled_provider = input_factory.call_args.kwargs['enabled_provider']
    assert enabled_provider()
    controls.pause_button.click()
    assert not enabled_provider()
    controls.stop_button.click()
    recorder.stop(wait=True)
    controls.refresh()
    assert not task.enabled and recorder.status['state'] == '已保存'
    assert controls.start_button.isEnabled() and not controls.stop_button.isEnabled()
    assert Path(recorder.status['archive']).is_file()
    assert others[0].enabled and others[0].running
    executor.interaction.on_run.assert_not_called()


@pytest.mark.parametrize('old_seconds,version,expected', [(60, 0, 0), (180, 0, 0), (300, 1, 0), (600, 2, 600)])
def test_old_default_duration_migrates_once(recording_ui, old_seconds, version, expected):
    task, _, _, _, _, _ = recording_ui
    task.config.update(录制时长秒=old_seconds, _recording_controls_version=version)
    task.on_create()
    assert task.config['录制时长秒'] == expected
    assert task.config['_recording_controls_version'] == 2


def test_other_resident_task_keeps_switch(recording_ui, tmp_path):
    _, _, _, executor, _, _ = recording_ui
    from src.tasks.auto_combat_task import AutoCombatTask
    task = AutoCombatTask(executor=executor, app=og.app)
    task.config = Config(type(task).__name__, task.default_config, folder=str(tmp_path), validator=task.validate)
    card = TaskCard(task, False)
    try:
        assert isinstance(card.enable_button, SwitchButton)
        assert not hasattr(card, 'recording_controls')
    finally:
        card.dispose()
        card.close()
        card.deleteLater()


def test_video_dropdowns_reach_recorder_session(recording_ui):
    task, card, recorder, *_ = recording_ui
    fps = card.config_widget_by_key['视频帧率'].combo_box
    size = card.config_widget_by_key['视频分辨率'].combo_box
    fps.setCurrentText('60 帧/秒')
    size.setCurrentText('1080P（1920×1080）')
    assert task.config['视频帧率'] == 60 and task.config['视频分辨率'] == '1080P'
    card.recording_controls.start_button.click()
    assert recorder.status['fps'] == 60 and recorder.status['video_size'] == [1920, 1080]
    task.should_trigger()
    assert task.trigger_interval == pytest.approx(1/60)
    recorder.stop(wait=True)
