"""Regression tests: a startup window must be visible before capture is offered it."""
import threading
from types import SimpleNamespace

import pytest

from ok.core.start_controller import StartController

_FRAMEWORK_WAIT = getattr(StartController._wait_until_started_window_stable, '__wrapped__',
                          StartController._wait_until_started_window_stable)


class FakeClock:
    """Deterministic monotonic clock; every poll advances without real sleeping."""

    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        # Rounding keeps 0.2s polls on the expected whole/half-second boundaries.
        self.now = round(self.now + seconds, 9)


class FakeStartedWindow:
    def __init__(self, clock, timeline):
        self.clock = clock
        self.timeline = timeline
        self.hwnd = 0
        self.state = {}
        self.updates = 0
        # The framework's foreground flag is False for background windows.
        self.visible = False

    def do_update_window_size(self):
        self.updates += 1
        self.state = self.timeline(self.clock.now)
        self.hwnd = self.state.get('hwnd', 0)


class FakeWin32Gui:
    def __init__(self, window):
        self.window = window

    def IsWindow(self, hwnd):
        state = self.window.state
        return bool(hwnd and state.get('hwnd') == hwnd and state.get('exists', True))

    def IsWindowVisible(self, hwnd):
        return bool(self.IsWindow(hwnd) and self.window.state.get('visible', True))

    def IsIconic(self, hwnd):
        return bool(self.IsWindow(hwnd) and self.window.state.get('minimized', False))

    def GetClientRect(self, hwnd):
        if not self.IsWindow(hwnd):
            raise OSError('window is gone')
        return 0, 0, self.window.state['width'], self.window.state['height']


class FakeSignal:
    def __init__(self):
        self.emits = []

    def emit(self, *args):
        self.emits.append(args)


def window_state(**overrides):
    state = {'hwnd': 100, 'visible': True, 'minimized': False, 'width': 1280, 'height': 720}
    state.update(overrides)
    return state


@pytest.fixture()
def controller_class(monkeypatch):
    import src.runtime.startup as startup
    # Start from the framework method so repeated tests cannot stack wrappers.
    monkeypatch.setattr(StartController, '_wait_until_started_window_stable', _FRAMEWORK_WAIT)
    startup.install_started_window_guard()
    return StartController


@pytest.fixture()
def build_controller(controller_class, monkeypatch):
    import src.runtime.startup as startup
    import ok.core.events as events
    from ok import og

    clock = FakeClock()
    monkeypatch.setattr(startup, 'time', clock)
    signal = FakeSignal()
    monkeypatch.setattr(events, 'communicate',
                        SimpleNamespace(starting_emulator=signal))

    def build(timeline, *, config=None, timeout=10.0, exit_event=None):
        window = FakeStartedWindow(clock, timeline)
        monkeypatch.setattr(startup, 'win32gui', FakeWin32Gui(window))
        monkeypatch.setattr(og, 'device_manager', SimpleNamespace(hwnd_window=window),
                            raising=False)
        controller = object.__new__(controller_class)
        controller.config = config if config is not None else {
            'supported_resolution': {'min_size': (1280, 720)},
        }
        controller.start_timeout = timeout
        controller.exit_event = exit_event or threading.Event()
        controller.tr = lambda message: message
        return controller, window, signal, clock

    return build


def test_hidden_small_client_cannot_pass_before_visible_window_stabilizes(build_controller):
    visible_at = 4.0

    def timeline(now):
        if now < visible_at:
            return window_state(hwnd=329246, visible=False, width=298, height=184)
        return window_state(hwnd=329246, visible=True, width=2560, height=1440)

    controller, window, signal, clock = build_controller(timeline, timeout=20.0)
    assert controller._wait_until_started_window_stable() is True
    # The hidden client was stable well past 2s, but only the visible window counts.
    assert clock.now == pytest.approx(visible_at + 2.0)
    assert window.state['visible'] is True
    assert signal.emits == []


def test_hidden_window_with_supported_client_size_is_still_rejected(build_controller):
    visible_at = 3.0

    def timeline(now):
        return window_state(hwnd=123, visible=now >= visible_at, width=1280, height=720)

    controller, _, signal, clock = build_controller(timeline, timeout=10.0)
    assert controller._wait_until_started_window_stable() is True
    assert clock.now == pytest.approx(visible_at + 2.0)
    assert signal.emits == []


def test_visible_background_window_stabilizes_without_foreground(build_controller):
    controller, window, signal, clock = build_controller(
        lambda now: window_state(hwnd=456, visible=True, width=1280, height=720),
        timeout=10.0,
    )
    assert window.visible is False  # framework's foreground flag
    assert controller._wait_until_started_window_stable() is True
    assert clock.now == pytest.approx(2.0)
    assert signal.emits == []


def test_same_size_new_hwnd_restarts_stability(build_controller):
    switched_at = 1.8

    def timeline(now):
        hwnd = 111 if now < switched_at else 222
        return window_state(hwnd=hwnd, visible=True, width=1280, height=720)

    controller, window, signal, clock = build_controller(timeline, timeout=10.0)
    assert controller._wait_until_started_window_stable() is True
    assert window.state['hwnd'] == 222
    # A size-only key would have returned at 2.0s, before the replacement hwnd is stable.
    assert switched_at + 2.0 <= clock.now <= switched_at + 2.0 + controller.STARTED_WINDOW_POLL_INTERVAL
    assert signal.emits == []


@pytest.mark.parametrize('mode', ['hidden', 'minimized', 'missing'])
def test_invalid_window_resets_stability(build_controller, mode):
    invalid_from, invalid_until = 1.8, 2.2

    def timeline(now):
        state = window_state(hwnd=789, visible=True, width=1280, height=720)
        if invalid_from <= now < invalid_until:
            if mode == 'hidden':
                state['visible'] = False
            elif mode == 'minimized':
                state['minimized'] = True
            else:
                state['hwnd'] = 0
        return state

    controller, _, signal, clock = build_controller(timeline, timeout=10.0)
    assert controller._wait_until_started_window_stable() is True
    # The earlier 1.8s of stability must not be counted after the window reappears.
    assert clock.now == pytest.approx(invalid_until + 2.0)
    assert signal.emits == []


def test_exit_during_wait_returns_false_without_timeout_notice(build_controller):
    exit_event = threading.Event()

    def timeline(now):
        if now >= 0.6:
            exit_event.set()
        return window_state(hwnd=321, visible=True, width=1280, height=720)

    controller, _, signal, clock = build_controller(timeline, timeout=10.0,
                                                    exit_event=exit_event)
    assert controller._wait_until_started_window_stable() is False
    assert clock.now == pytest.approx(0.8)  # the in-flight poll completes, then the loop exits
    assert signal.emits == []


def test_configured_minimum_rejects_small_visible_client(build_controller):
    controller, _, signal, clock = build_controller(
        lambda now: window_state(hwnd=333, visible=True, width=1279, height=720),
        timeout=1.0,
    )
    assert controller._wait_until_started_window_stable() is False
    assert clock.now == pytest.approx(1.0)
    assert signal.emits == [(True, 'Start game timeout!', 0)]


def test_timeout_returns_false_and_preserves_notification(build_controller):
    controller, _, signal, clock = build_controller(
        lambda now: window_state(hwnd=654, visible=False, width=1280, height=720),
        timeout=1.0,
    )
    assert controller._wait_until_started_window_stable() is False
    assert clock.now == pytest.approx(1.0)
    assert signal.emits == [(True, 'Start game timeout!', 0)]


def test_unconfigured_minimum_falls_back_to_framework_default(build_controller,
                                                               controller_class):
    controller, _, signal, clock = build_controller(
        lambda now: window_state(hwnd=987, visible=True, width=100, height=100),
        config={},
        timeout=10.0,
    )
    assert controller._wait_until_started_window_stable() is True
    assert clock.now == pytest.approx(2.0)
    assert signal.emits == []
    assert controller_class.STARTED_WINDOW_MIN_SIZE == (100, 100)


def test_installer_is_idempotent(controller_class):
    import src.runtime.startup as startup

    installed = controller_class._wait_until_started_window_stable
    assert getattr(installed, '_zzz_started_window_guard', False) is True
    startup.install_started_window_guard()
    assert controller_class._wait_until_started_window_stable is installed
