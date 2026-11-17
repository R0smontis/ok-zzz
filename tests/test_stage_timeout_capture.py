import json
import zipfile
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from src.runtime.stage_watchdog import capture_stall


@pytest.mark.parametrize('package', [False, True])
def test_stall_saves_logs_notifies_and_optionally_packages(tmp_path, monkeypatch, package):
    from ok import og
    from ok.core.events import communicate
    from onedragon.utils import os_utils
    from src.diagnostics import recorder as module
    (tmp_path / 'logs').mkdir()
    (tmp_path / 'logs/runtime.log').write_text('ERROR stuck token=PRIVATE\n', encoding='utf-8')
    monkeypatch.setattr(os_utils, 'get_work_dir', lambda: str(tmp_path))
    executor = SimpleNamespace(_frame=np.zeros((1080, 1920, 3), np.uint8))
    monkeypatch.setattr(og, 'executor', executor)
    monkeypatch.setattr(module, 'runtime_snapshot', lambda _: {'node': '开始挑战'})
    recorder = SimpleNamespace(active=False, paused=False, start=Mock(), record=Mock())
    monkeypatch.setattr(module, 'recorder', recorder)
    notices = []
    def notice(*args):
        notices.append(args)
    communicate.notification.connect(notice)
    try:
        capture_stall(None, {'operation': '迷失之地', 'stage': '开始挑战', 'elapsed_seconds': 300}, package)
    finally:
        communicate.notification.disconnect(notice)
    incident = next((tmp_path / 'debug/stalls').glob('*/incident.json'))
    assert json.loads(incident.read_text(encoding='utf-8'))['stage_timeout']['stage'] == '开始挑战'
    assert (incident.parent / 'threads.log').is_file()
    log = (incident.parent / 'runtime.log').read_text(encoding='utf-8')
    assert 'PRIVATE' not in log and 'stuck' in log
    recorder.start.assert_called_once()
    assert any(args[2] is True and '开始挑战' in args[0] for args in notices)
    archives = list((tmp_path / 'debug/reports').glob('*.zip'))
    assert len(archives) == int(package)
    if package:
        with zipfile.ZipFile(archives[0]) as archive:
            assert 'stage-timeout/threads.log' in archive.namelist()
            assert any(name.endswith('/logs/runtime.log') for name in archive.namelist())
