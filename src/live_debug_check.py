"""Live protocol smoke test against a substitute game; sends no real input."""
from pathlib import Path
import tempfile
import time

import cv2
import numpy as np

from src.live_client import LiveClient
from src.live_debug import LiveDebugService


class SubstituteGame:
    actions = {'dodge', 'move_w', 'confirm', 'back'}

    def __init__(self):
        self.hwnd = 101
        self.geometry = [0, 0, 1280, 720]
        self.control_target = None
        self.inputs = []
        self.release_count = 0
        self.capture_enabled = True
        self.image = np.full((720, 1280, 3), 180, np.uint8)

    def target(self):
        return {'hwnd': self.hwnd, 'geometry': list(self.geometry)}

    def capture(self):
        return (self.image, self.hwnd, time.time(), list(self.geometry)) if self.capture_enabled else None

    def snapshot(self):
        return {'window': self.target(), 'tasks': [], 'executor_paused': True}

    def acquire(self, mode):
        self.control_target = self.target()
        return {'mode': mode, 'automatic_tasks_stopped': True}

    def release(self):
        self.control_target = None
        self.release_count += 1

    def control_target_valid(self):
        return self.control_target == self.target()

    def input(self, command, cancel):
        self.inputs.append(dict(command))
        return not cancel.wait(command.get('duration', .01))

    def analyze(self, image, command):
        return {'attack_hud_visible': False, 'enemy_detection_skipped': True, 'ocr': []}

    def task(self, name, action):
        return {'task': name, 'action': action}


def wait_for_frame(service):
    deadline = time.monotonic()+3
    while service.status()['frame'] is None and time.monotonic() < deadline:
        time.sleep(.01)
    assert service.status()['frame'] is not None


def check_live_debug(root):
    with tempfile.TemporaryDirectory(prefix='.live-check-', dir=str(root)) as directory:
        game = SubstituteGame()
        service = LiveDebugService(game, Path(directory)/'live', interval=.05)
        game.service = service
        try:
            service.start()
            client = LiveClient(service.folder/'session.json')
            wait_for_frame(service)
            assert not client.request('/status')['control']
            threads = client.request('/threads')['threads']
            assert threads and all(isinstance(row['stack'], list) and len(row['stack']) <= 32 for row in threads)
            assert not service.owned and not game.inputs
            client.command({'op': 'acquire'})
            assert client.request('/status')['control']
            result = client.command({'op': 'click', 'x': 960, 'y': 540, 'duration': .01})
            assert result['result']['delivered'] and len(game.inputs) == 1
            assert game.inputs[0]['hwnd'] == 101
            frame_path = Path(directory)/'frame.png'
            client.save_frame(frame_path)
            image = cv2.imread(str(frame_path))
            assert image.shape == (1080, 1920, 3)
            assert image[1079, 1919].max() == 0 and game.image[-1, -1].max() == 180
            service.event('check_event', value='live')
            assert any(e['kind'] == 'check_event' for e in client.request('/events')['events'])
            client.request('/release', {})
            assert not service.owned and game.control_target is None
            assert len(game.inputs) == 1
        finally:
            service.stop()
        assert not (service.folder/'session.json').exists()
    return {'protocol_roundtrip': 'passed', 'background_command': 'substitute passed',
            'authenticated_read_only_threads': 'passed',
            'uid_mask_and_coordinates': 'passed', 'release_and_shutdown': 'passed', 'game_input': 'none'}
