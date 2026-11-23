"""Auto resize must leave Unity fullscreen first and give the player's window mode back on exit.

The fake window reproduces what the live game did on 2026-11-23: while fullscreen it ignores
SetWindowPos, Alt+Enter toggles fullscreen, and entering fullscreen keeps the current windowed
size for the next Alt+Enter.
"""
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import win32con

from src.runtime import window_resolution as module

HWND = 4242
MONITOR = (0, 0, 3024, 1898)
WORK = (0, 0, 3024, 1850)
FRAME = (22, 56)
RESIZE_TO = [(2560, 1440), (1920, 1080), (1600, 900), (1280, 720), (3840, 2160)]


class UnityWindow:
    def __init__(self, fullscreen=True, rect=(300, 150, 2000, 1150), accepts_resize=True,
                 answers_toggle=True):
        self.fullscreen = fullscreen
        self.windowed_rect = rect
        self.accepts_resize = accepts_resize
        self.answers_toggle = answers_toggle
        self.posted = []
        self.show_state = win32con.SW_SHOWNORMAL
        self.saved_placement = None

    def rect(self):
        return MONITOR if self.fullscreen else self.windowed_rect

    def client(self):
        if self.fullscreen:
            return 0, 0, MONITOR[2] - MONITOR[0], MONITOR[3] - MONITOR[1]
        left, top, right, bottom = self.windowed_rect
        return 0, 0, right - left - FRAME[0], bottom - top - FRAME[1]

    def set_pos(self, hwnd, _after, x, y, width, height, _flags):
        assert hwnd == HWND
        if not self.fullscreen and self.accepts_resize:
            self.windowed_rect = (x, y, x + width, y + height)
        return True

    def get_placement(self, hwnd):
        assert hwnd == HWND
        return (0, self.show_state, (-1, -1), (-1, -1), self.windowed_rect)

    def set_placement(self, hwnd, placement):
        assert hwnd == HWND
        self.saved_placement = placement
        self.show_state = placement[1]
        self.windowed_rect = placement[4]

    def show(self, hwnd, command):
        assert hwnd == HWND and command == win32con.SW_RESTORE
        self.show_state = win32con.SW_SHOWNORMAL

    def post(self, hwnd, message, wparam, _lparam):
        assert hwnd == HWND
        self.posted.append((message, wparam))
        if (message, wparam) == (win32con.WM_SYSKEYDOWN, win32con.VK_RETURN) and self.answers_toggle:
            self.fullscreen = not self.fullscreen


@pytest.fixture
def game(monkeypatch):
    window = UnityWindow()
    gui = SimpleNamespace(
        GetWindowRect=lambda hwnd: window.rect(),
        GetClientRect=lambda hwnd: window.client(),
        GetWindowPlacement=window.get_placement,
        SetWindowPlacement=window.set_placement,
        SetWindowPos=window.set_pos,
        PostMessage=window.post,
        ShowWindow=window.show,
        IsWindow=lambda hwnd: hwnd == HWND,
        IsIconic=lambda hwnd: False,
        error=OSError,
    )
    monkeypatch.setattr(module, 'win32gui', gui)
    monkeypatch.setattr(module.win32api, 'MonitorFromWindow', lambda hwnd, flags: 1)
    monkeypatch.setattr(module.win32api, 'GetMonitorInfo', lambda monitor: {'Monitor': MONITOR, 'Work': WORK})
    for name, value in (('POLL_SECONDS', 0), ('STABLE_SECONDS', 0), ('SETTLE_TIMEOUT', .05),
                        ('TOGGLE_TIMEOUT', .05), ('FULLSCREEN_RESIZE_TIMEOUT', .05),
                        ('FULLSCREEN_TOGGLE_TIMEOUT', .05)):
        monkeypatch.setattr(module, name, value)
    monkeypatch.setattr(module, '_adjustment', None)
    monkeypatch.setattr(module, '_guard_stop', None)
    return window


def framework_window(enabled=True):
    options = {'Auto Resize Game Window': enabled}

    def update():
        target.width, target.height = module._client_size(HWND)

    target = SimpleNamespace(hwnd=HWND, window_width=1, width=0, height=0,
                             app_exit_event=threading.Event(), do_update_window_size=update,
                             global_config=SimpleNamespace(get_config=lambda name: options))
    return target


def toggles(window):
    return sum(1 for posted in window.posted if posted == (win32con.WM_SYSKEYDOWN, win32con.VK_RETURN))


def test_fullscreen_game_leaves_fullscreen_and_gets_supported_client(game):
    window = framework_window()
    assert module.try_resize_to(window, RESIZE_TO) is True
    assert not game.fullscreen and toggles(game) == 1
    assert (window.width, window.height) == (2560, 1440)
    left, top, right, bottom = game.windowed_rect
    assert WORK[0] <= left and WORK[1] <= top and right <= WORK[2] and bottom <= WORK[3]


def test_exit_restores_fullscreen_without_changing_the_stored_windowed_size(game):
    assert module.try_resize_to(framework_window(), RESIZE_TO)
    assert module.restore_game_window() is True
    assert game.fullscreen and toggles(game) == 2
    # Unity keeps this size for the player's next Alt+Enter; it must be the monitor size again.
    assert module._rect_size(game.windowed_rect) == (MONITOR[2] + FRAME[0], MONITOR[3] + FRAME[1])
    assert module.restore_game_window() is False  # Restored once only.


def test_windowed_game_gets_its_original_rect_back(game):
    game.fullscreen = False
    original = game.windowed_rect
    assert module.try_resize_to(framework_window(), RESIZE_TO)
    assert game.windowed_rect != original and toggles(game) == 0
    assert module.restore_game_window() is True
    assert game.windowed_rect == original and not game.fullscreen


def test_manual_change_after_adjustment_is_kept_on_exit(game):
    assert module.try_resize_to(framework_window(), RESIZE_TO)
    left, top, right, bottom = game.windowed_rect
    game.windowed_rect = (left, top, right - 200, bottom - 100)
    assert module.restore_game_window() is False
    assert game.windowed_rect == (left, top, right - 200, bottom - 100) and toggles(game) == 1


def test_resize_rejected_by_game_returns_fullscreen_player_to_fullscreen(game):
    game.accepts_resize = False
    assert module.try_resize_to(framework_window(), RESIZE_TO) is False
    assert game.fullscreen
    assert module.restore_game_window() is False  # Nothing was adjusted.


def test_exit_reports_when_game_ignores_fullscreen_restore(game):
    assert module.try_resize_to(framework_window(), RESIZE_TO)
    game.answers_toggle = False
    assert module.restore_game_window() is False
    assert not game.fullscreen


def test_cancelled_resize_restores_fullscreen_on_exit(game, monkeypatch):
    window = framework_window()

    def cancel_resize(hwnd, target, cancel):
        cancel.set()
        return False

    monkeypatch.setattr(module, '_settled', cancel_resize)
    assert module.try_resize_to(window, RESIZE_TO) is False
    assert not game.fullscreen and toggles(game) == 1
    assert module.restore_game_window() is True
    assert game.fullscreen and toggles(game) == 2


def test_maximized_window_is_maximized_again_on_exit(game):
    game.fullscreen = False
    game.show_state = win32con.SW_SHOWMAXIMIZED
    original = game.get_placement(HWND)
    assert module.try_resize_to(framework_window(), RESIZE_TO)
    assert game.show_state == win32con.SW_SHOWNORMAL
    assert module.restore_game_window() is True
    assert game.saved_placement == original


def test_disabled_option_never_touches_the_window(game):
    assert module.try_resize_to(framework_window(enabled=False), RESIZE_TO) is False
    assert game.posted == [] and game.fullscreen


@pytest.fixture
def framework_startup(game, monkeypatch):
    from ok import og
    from ok.core.start_controller import StartController
    from ok.device.capture_methods.hwnd_window import HwndWindow
    from src.runtime.startup import _started_window_min_size

    window = framework_window()
    normal_check = Mock(side_effect=lambda controller: HwndWindow.try_resize_to(window, RESIZE_TO))
    normal_start = StartController._do_start
    monkeypatch.setattr(StartController, '_do_start', getattr(normal_start, '__wrapped__', normal_start))
    monkeypatch.setattr(StartController, 'check_resolution', normal_check)
    monkeypatch.setattr(HwndWindow, 'try_resize_to', HwndWindow.try_resize_to)
    monkeypatch.setattr(og, 'device_manager', SimpleNamespace(
        capture_method=SimpleNamespace(hwnd_window=window), do_refresh=Mock()))
    executor = SimpleNamespace(current_task=None, onetime_tasks=[], trigger_tasks=[],
                               start=Mock(), enqueue_onetime_task=Mock())
    executor.get_all_tasks = lambda: executor.onetime_tasks + executor.trigger_tasks
    monkeypatch.setattr(og, 'executor', executor)
    monkeypatch.setattr(module, 'watch_startup', Mock())
    module.install_window_resolution()

    controller = StartController.__new__(StartController)
    controller.config = {'supported_resolution': {'min_size': (1280, 720), 'resize_to': RESIZE_TO}}
    controller.start_timeout = 1
    controller.start_exe = True
    controller.check_gpu_driver_post_processing = Mock()
    observed = SimpleNamespace(controller=controller, executor=executor, check=normal_check,
                               minimum=None)

    def start_device(initial_refresh_done):
        observed.minimum = _started_window_min_size(controller)
        controller.check_resolution()
        return True

    controller.start_device = start_device
    return observed


@pytest.mark.parametrize('task_name', ['start', 'story', 'battle', 'commission'])
def test_assistants_preserve_native_resolution_on_start(game, framework_startup, task_name):
    from src.tasks.app_tasks import App_CommissionAssistant
    from src.tasks.auto_combat_task import AutoCombatTask
    from src.tasks.dialogue_task import AutoDialogueTriggerTask

    startup = framework_startup
    story = AutoDialogueTriggerTask.__new__(AutoDialogueTriggerTask)
    battle = AutoCombatTask.__new__(AutoCombatTask)
    commission = App_CommissionAssistant.__new__(App_CommissionAssistant)
    tasks = {'start': None, 'story': story, 'battle': battle, 'commission': commission}
    task = tasks[task_name]
    if task is not None:
        task._enabled = True
        task._paused = False
    startup.executor.onetime_tasks = [SimpleNamespace(app_id='daily'), commission]
    assert startup.controller.do_start(1 if task is commission else task) is True
    assert startup.minimum == startup.controller.STARTED_WINDOW_MIN_SIZE
    startup.check.assert_not_called()
    module.watch_startup.assert_not_called()
    assert game.fullscreen and toggles(game) == 0
    assert module.restore_game_window() is False


@pytest.mark.parametrize('explicit', [True, False])
def test_fixed_resolution_tasks_keep_adjustment_and_restore(game, framework_startup, explicit):
    startup = framework_startup
    daily = SimpleNamespace(app_id='daily', enabled=True, paused=False, enable_after_start=not explicit)
    startup.executor.onetime_tasks = [daily]
    assert startup.controller.do_start(0 if explicit else None) is True
    assert startup.minimum == (1280, 720)
    startup.check.assert_called_once_with(startup.controller)
    module.watch_startup.assert_called_once()
    assert not game.fullscreen and toggles(game) == 1
    assert module.restore_game_window() is True
    assert game.fullscreen and toggles(game) == 2
