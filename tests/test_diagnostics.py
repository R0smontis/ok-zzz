"""Real image/video/file output with simulated frames and no game input."""
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock
import zipfile

import cv2
import numpy as np
import pytest

from src.diagnostics import recorder as diagnostics


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


@pytest.fixture
def recorder():
    instance = diagnostics.DiagnosticRecorder()
    yield instance
    instance.stop(wait=True)


def screen():
    image = np.full((1080, 1920, 3), 80, np.uint8)
    panel = cv2.imread(str(Path(__file__).parent / 'fixtures/combat_recording/near_enemy.png'))
    image[370:370+panel.shape[0], 830:830+panel.shape[1]] = panel
    return image


def wait_samples(recorder, count=1):
    limit = time.monotonic()+5
    while recorder.status['images'] < count and time.monotonic() < limit:
        time.sleep(0.01)
    assert recorder.status['images'] >= count, recorder.status


def test_frames_events_logs_zip_share_time_and_mask_uid(recorder, tmp_path):
    (tmp_path / 'logs').mkdir()
    (tmp_path / 'logs/ok-script.log').write_text('runtime started\n', encoding='utf-8')
    frame = screen()
    original = frame.copy()
    folder = Path(recorder.start(tmp_path, mode='截图', image_interval=0.2,
                                 snapshot_provider=lambda: {'application': 'charge_plan', 'enemy_gate': False}))
    recorder.record('battle_start', entry='stage_script', enemy_gate_installed=False)
    recorder.observe(frame, captured_at=time.time())
    wait_samples(recorder)
    recorder.stop(wait=True)
    state = recorder.status
    assert state['state'] == '已保存' and state['error'] is None
    assert np.array_equal(frame, original)
    entry = read_jsonl(folder / 'frames.jsonl')[0]
    saved = cv2.imread(str(folder / entry['image']))
    assert saved[1065:1075, 1830:1900].max() <= 2
    assert entry['visual_evidence']['enemy_health_bar']
    assert entry['runtime']['application'] == 'charge_plan'
    assert '+08:00' in entry['time'] and entry['elapsed'] >= 0
    event = read_jsonl(folder / 'events.jsonl')[0]
    assert event['type'] == 'battle_start' and not event['enemy_gate_installed']
    assert (folder / 'logs/ok-script-start.log').read_text() == 'runtime started\n'
    assert (folder / 'logs/ok-script-end.log').is_file()
    with zipfile.ZipFile(state['archive']) as archive:
        assert archive.testzip() is None
        assert f'{folder.name}/{entry["image"]}' in archive.namelist()
        assert f'{folder.name}/session.json' in archive.namelist()


def test_video_has_playable_frames_and_timestamp_index(recorder, tmp_path):
    folder = Path(recorder.start(tmp_path, fps=10))
    recorder.observe(screen())
    wait_samples(recorder)
    time.sleep(0.35)
    recorder.stop(wait=True)
    metadata = json.loads((folder / 'session.json').read_text(encoding='utf-8'))
    assert not metadata['error']
    assert metadata['video_frames'] >= 3
    video = cv2.VideoCapture(str(folder / metadata['video']))
    try:
        assert video.isOpened()
        success, first = video.read()
        assert success and first.shape[:2] == (720, 1280)
        assert video.get(cv2.CAP_PROP_FPS) == pytest.approx(10)
        visible_frames = [first]
        while True:
            success, recorded = video.read()
            if not success:
                break
            visible_frames.append(recorded)
        # Diagnostic timestamps must not overwrite the top-of-screen boss HUD.
        assert any(recorded[5:15, 25:100].mean() > 40 for recorded in visible_frames)
    finally:
        video.release()
    timeline = read_jsonl(folder / 'video-timeline.jsonl')
    assert len(timeline) == metadata['video_frames']
    assert timeline[-1]['elapsed'] >= 0.2


def test_video_codec_failure_keeps_screenshots_and_logs(recorder, tmp_path, monkeypatch):
    monkeypatch.setattr(recorder, '_video_writer', Mock(side_effect=RuntimeError('codec unavailable')))
    folder = Path(recorder.start(tmp_path, mode='视频'))
    recorder.observe(screen())
    wait_samples(recorder)
    recorder.stop(wait=True)
    assert list((folder / 'frames').glob('*.jpg'))
    assert recorder.status['state'] == '已保存'
    assert recorder.status['error'] == 'codec unavailable'


def test_deadline_finishes_even_without_new_frames(recorder, tmp_path):
    finished = threading.Event()
    folder = Path(recorder.start(tmp_path, duration=5, mode='截图', on_finished=finished.set))
    assert finished.wait(8)
    assert not recorder.active
    assert recorder.status['state'] == '已保存'
    assert json.loads((folder / 'session.json').read_text(encoding='utf-8'))['reason'] == '达到录制时长'


def test_observer_preserves_frame_and_one_shot_task_state(recorder, tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics, 'recorder', recorder)
    frame = screen()
    active_task = SimpleNamespace(name='副本', enabled=True, running=True, info={})
    capture = Mock(return_value=frame)
    executor = SimpleNamespace(next_frame=capture, current_task=active_task,
                               _last_frame_time=time.time())
    diagnostics.install_frame_observer(executor)
    diagnostics.install_frame_observer(executor)  # Idempotent.
    folder = Path(recorder.start(tmp_path, mode='截图'))
    assert executor.next_frame(time_out=4) is frame
    capture.assert_called_once_with(time_out=4)
    wait_samples(recorder)
    assert active_task.enabled and active_task.running and executor.current_task is active_task
    recorder.stop(wait=True)
    assert read_jsonl(folder / 'frames.jsonl')[0]['source'] == 'ok-script'


def test_recorder_failure_does_not_break_capture(monkeypatch):
    failed = SimpleNamespace(observe=Mock(side_effect=OSError('disk full')), record=Mock())
    monkeypatch.setattr(diagnostics, 'recorder', failed)
    frame = screen()
    executor = SimpleNamespace(next_frame=lambda: frame)
    diagnostics.install_frame_observer(executor)
    assert executor.next_frame() is frame
    failed.record.assert_called_once()


def test_runtime_snapshot_uses_existing_context_only(monkeypatch):
    from ok import og
    fake = SimpleNamespace(_context=None)
    monkeypatch.setattr(og, 'my_app', fake)
    executor = SimpleNamespace(get_all_tasks=lambda: [], paused=True, device_manager=None,
                               method=None, _last_frame_time=time.time())
    state = diagnostics.runtime_snapshot(executor)
    assert state['executor_paused'] and state['capture_backend'] is None
    assert fake._context is None


def test_log_tail_is_bounded(recorder, tmp_path):
    (tmp_path / 'logs').mkdir()
    (tmp_path / 'logs/ok-script.log').write_bytes(b'x' * (diagnostics.LOG_TAIL_BYTES+32))
    folder = Path(recorder.start(tmp_path, mode='截图'))
    recorder.stop(wait=True)
    assert (folder / 'logs/ok-script-end.log').stat().st_size == diagnostics.LOG_TAIL_BYTES


def test_recording_start_source_and_dedupe(recorder, tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics, 'recorder', recorder)
    folder = Path(recorder.start(tmp_path, mode='截图'))
    diagnostics.record_battle_start('start_auto_battle', SimpleNamespace(auto_op=SimpleNamespace()))
    for _ in range(4):
        diagnostics.record_event('idle', throttle='idle', state='waiting')
    recorder.stop(wait=True)
    events = read_jsonl(folder / 'events.jsonl')
    assert len(events) == 2
    assert events[0]['source'][-1]['function'] == 'test_recording_start_source_and_dedupe'
    assert not events[0]['enemy_gate_installed']


@pytest.mark.parametrize('settings', [dict(duration=float('nan')), dict(duration=-1),
                                     dict(image_interval=0), dict(fps=120), dict(mode='unknown'),
                                     dict(resolution='4K'), dict(fps=60.5)])
def test_invalid_settings_do_not_start_writer(recorder, tmp_path, settings):
    with pytest.raises(ValueError):
        recorder.start(tmp_path, **settings)
    assert not recorder.active and not (tmp_path / 'debug').exists()


@pytest.mark.parametrize('resolution', ['480P', '720P', '1080P'])
def test_real_60fps_video_uses_selected_size_and_metadata(recorder, tmp_path, resolution):
    folder = Path(recorder.start(tmp_path, fps=60, resolution=resolution, mode='视频'))
    recorder.observe(np.full((720, 1280, 3), (20, 60, 160), np.uint8))
    time.sleep(.5)
    recorder.stop(wait=True)
    metadata = json.loads((folder / 'session.json').read_text(encoding='utf-8'))
    assert metadata['resolution'] == resolution
    assert metadata['video_size'] == list(diagnostics.VIDEO_RESOLUTIONS[resolution])
    assert not metadata['error'], metadata
    capture = cv2.VideoCapture(str(folder / metadata['video']))
    try:
        assert capture.get(cv2.CAP_PROP_FPS) == pytest.approx(60)
        assert (int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))) == (
            diagnostics.VIDEO_RESOLUTIONS[resolution])
        count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        assert count == metadata['video_frames']
        # Output should follow wall time at 60 FPS, rather than the old 50 FPS cap.
        assert abs(count/60-metadata['duration']) < .08, metadata
    finally:
        capture.release()


@pytest.mark.parametrize('fps', [5, 10, 15, 24, 30, 60])
def test_supported_video_fps_reaches_real_encoder(recorder, tmp_path, fps):
    folder = Path(recorder.start(tmp_path, fps=fps, resolution='480P', mode='视频'))
    time.sleep(.22)
    recorder.stop(wait=True)
    metadata = json.loads((folder / 'session.json').read_text(encoding='utf-8'))
    capture = cv2.VideoCapture(str(folder / metadata['video']))
    try:
        assert capture.isOpened() and capture.read()[0]
        assert capture.get(cv2.CAP_PROP_FPS) == pytest.approx(fps)
        assert metadata['fps'] == fps and metadata['video_frames'] >= 1
    finally:
        capture.release()


def test_disabled_recorder_does_not_copy_frame(recorder):
    frame = SimpleNamespace(copy=Mock())
    recorder.observe(frame)
    frame.copy.assert_not_called()


def test_diagnostic_toggle_keeps_combat_and_stage_enabled(recorder, tmp_path, monkeypatch):
    from ok import og
    from src.tasks import diagnostic_task
    monkeypatch.setattr(diagnostic_task, 'recorder', recorder)
    monkeypatch.setattr(diagnostics, 'recorder', recorder)
    monkeypatch.setattr(diagnostic_task.os_utils, 'get_work_dir', lambda: str(tmp_path))
    combat = SimpleNamespace(name='自动战斗', enabled=True, running=False, info={})
    stage = SimpleNamespace(name='副本', enabled=True, running=True, info={})
    tasks = [combat, stage]
    executor = SimpleNamespace(scene=None, get_all_tasks=lambda: tasks,
        interaction=SimpleNamespace(on_run=Mock()), enqueue_onetime_task=Mock(),
        remove_onetime_task=Mock(), _wake_executor=Mock(), next_frame=lambda: screen(), paused=False)
    monkeypatch.setattr(og, 'my_app', SimpleNamespace(_context=None))
    from src.controls import user_input_trace
    fake_inputs = SimpleNamespace(start=Mock(), stop=Mock())
    monkeypatch.setattr(user_input_trace, 'GameInputTrace', Mock(return_value=fake_inputs))
    task = diagnostic_task.DiagnosticRecordingTask(executor=executor, app=SimpleNamespace(tr=lambda s: s))
    task.config = dict(task.default_config, _enabled=True)
    tasks.append(task)
    task.on_create()
    assert not task.enabled and not task.config['_enabled']
    task.enable()
    assert task.enabled and combat.enabled and stage.enabled and stage.running
    executor.interaction.on_run.assert_not_called()
    executor.next_frame()
    wait_samples(recorder)
    task.disable()
    recorder.stop(wait=True)
    assert not task.enabled and not task.config['_enabled']
    assert task.info['诊断状态'] == '已保存' and task.info['诊断包']
    assert combat.enabled and stage.enabled and stage.running
    fake_inputs.start.assert_called_once()
    fake_inputs.stop.assert_called_once()


def test_user_input_file_separates_physical_and_program_records(recorder, tmp_path):
    folder = Path(recorder.start(tmp_path, mode='截图'))
    recorder.record('user_input', device='keyboard', action='down', key='W', source='user')
    recorder.record('input_call', action='tap', key='mouse_left')
    recorder.record('observed_injected_input', action='down', key='E', source='injected')
    recorder.stop(wait=True)
    user = read_jsonl(folder / 'user-input.jsonl')
    assert len(user) == 1 and user[0]['source'] == 'user'
    assert len(read_jsonl(folder / 'events.jsonl')) == 3
    assert recorder.status['user_inputs'] == 1


def test_pause_freezes_capture_events_and_video_then_resumes_same_session(recorder, tmp_path):
    folder = Path(recorder.start(tmp_path, duration=300, fps=10, image_interval=0.2))
    recorder.observe(screen())
    recorder.record('user_input', key='W', action='down')
    wait_samples(recorder)
    time.sleep(0.12)
    assert recorder.pause() and recorder.paused and not recorder.active
    time.sleep(0.08)  # Let the writer drain observations accepted before pausing.
    before = recorder.status
    recorder.observe(screen())
    recorder.record('input_call', action='tap', key='ignored_while_paused')
    recorder.record('user_input', key='ignored_while_paused', action='down')
    time.sleep(0.35)
    after = recorder.status
    assert after['state'] == '已暂停'
    assert after['elapsed'] == before['elapsed']
    assert after['video_frames'] == before['video_frames']
    assert after['images'] == before['images']
    assert after['events'] == before['events']
    assert recorder.resume() and recorder.active and not recorder.paused
    recorder.observe(np.full((1080, 1920, 3), 140, np.uint8))
    recorder.record('user_input', key='W', action='up')
    wait_samples(recorder, 2)
    time.sleep(0.23)
    recorder.stop(wait=True)
    events = read_jsonl(folder/'events.jsonl')
    assert [e['type'] for e in events] == ['user_input', 'recording_pause', 'recording_resume', 'user_input']
    assert events[2]['elapsed']-events[1]['elapsed'] < 0.03
    assert events[2]['wall_elapsed']-events[1]['wall_elapsed'] >= 0.35
    metadata = json.loads((folder/'session.json').read_text(encoding='utf-8'))
    assert metadata['requested_duration'] == 300
    assert metadata['paused_duration'] >= 0.35
    assert metadata['wall_duration']-metadata['duration'] == pytest.approx(metadata['paused_duration'], abs=0.002)
    assert metadata['video_frames'] <= metadata['duration']*10+2  # No catch-up frames for the paused gap.
    assert metadata['user_input_events'] == 2
    video = cv2.VideoCapture(str(folder/metadata['video']))
    assert video.isOpened() and video.read()[0]
    video.release()


def test_five_minute_deadline_ignores_pause_time(recorder, tmp_path):
    finished = threading.Event()
    folder = Path(recorder.start(tmp_path, duration=300, mode='截图', on_finished=finished.set))
    assert recorder.pause()
    # Move the session clock close to its limit without waiting five real minutes.
    with recorder._lock:
        recorder._session['start'] -= 299.75
    time.sleep(0.4)
    assert recorder.paused and not finished.is_set()
    assert recorder.status['elapsed'] < 300
    assert recorder.resume()
    assert finished.wait(3)
    metadata = json.loads((folder/'session.json').read_text(encoding='utf-8'))
    assert metadata['reason'] == '达到录制时长'
    assert metadata['duration'] == pytest.approx(300, abs=0.1)
    assert metadata['paused_duration'] >= 0.35


def test_stop_while_paused_saves_and_restart_creates_new_session(recorder, tmp_path):
    first = Path(recorder.start(tmp_path, mode='截图'))
    assert recorder.pause()
    recorder.stop(wait=True)
    assert recorder.status['state'] == '已保存' and not recorder.paused
    stopped_time = recorder.status['elapsed']
    time.sleep(0.05)
    assert recorder.status['elapsed'] == stopped_time
    assert not recorder.resume() and not recorder.pause()
    second = Path(recorder.start(tmp_path, mode='截图'))
    assert first != second and recorder.active
    recorder.stop(wait=True)
    assert (first/'session.json').exists() and (second/'session.json').exists()
