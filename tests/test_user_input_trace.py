"""Synthetic native-hook packets, never generate physical input."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.user_input_trace import GameInputTrace, key_name


@pytest.fixture
def trace():
    events = []
    state = {'foreground': True, 'enabled': True}

    def scope(hwnd, point=None):
        if not state['foreground'] or hwnd != 101:
            return None
        result = {'hwnd': hwnd}
        if point is not None:
            if not (0 <= point[0] < 1920 and 0 <= point[1] < 1080):
                return None
            result.update(x=point[0], y=point[1], game_x=point[0], game_y=point[1])
        return result

    recorder = GameInputTrace(lambda: 101, lambda kind, **data: events.append((kind, data)),
        scope_reader=scope, enabled_provider=lambda: state['enabled'])
    recorder.running = True
    return recorder, events, state


def keyboard(vk=0x57, flags=0):
    return SimpleNamespace(vkCode=vk, scanCode=17, flags=flags)


def mouse(x=500, y=300, flags=0, data=0):
    return SimpleNamespace(pt=SimpleNamespace(x=x, y=y), flags=flags, mouseData=data)


def test_physical_keys_include_down_repeat_up(trace):
    recorder, events, _ = trace
    for msg in (0x100, 0x100, 0x101):
        assert recorder.keyboard_filter(msg, keyboard()) is False
    physical = [event for kind, event in events if kind == 'user_input']
    assert [event['action'] for event in physical] == ['down', 'repeat', 'up']
    assert all(event['key'] == 'W' and event['source'] == 'user' for event in physical)
    assert not recorder.held_keys


@pytest.mark.parametrize('flag', [0x10, 0x02, 0x12])
def test_injected_keyboard_is_separate_from_user(trace, flag):
    recorder, events, _ = trace
    recorder.keyboard_filter(0x100, keyboard(flags=flag))
    assert [kind for kind, _ in events] == ['user_input_scope', 'observed_injected_input']
    assert not recorder.held_keys


def test_other_window_keys_are_not_recorded(trace):
    recorder, events, state = trace
    recorder.keyboard_filter(0x100, keyboard())
    state['foreground'] = False
    for vk in (0x41, 0x42, 0x43):
        recorder.keyboard_filter(0x100, keyboard(vk=vk))
    assert len([1 for kind, _ in events if kind == 'user_input']) == 1
    assert not recorder.held_keys
    assert events[-1][0] == 'user_input_scope' and not events[-1][1]['active']


def test_live_disable_and_stop_do_not_record_more_input(trace):
    recorder, events, state = trace
    state['enabled'] = False
    recorder.keyboard_filter(0x100, keyboard())
    recorder.mouse_filter(0x201, mouse())
    assert not events
    state['enabled'] = True
    recorder.keyboard_filter(0x100, keyboard())
    assert any(kind == 'user_input' for kind, _ in events)
    recorder.running = False
    count = len(events)
    recorder.keyboard_filter(0x101, keyboard())
    recorder.mouse_filter(0x201, mouse())
    assert len(events) == count


def test_mouse_client_coordinates_click_scroll_and_injected_source(trace):
    recorder, events, _ = trace
    recorder.mouse_filter(0x201, mouse())
    recorder.mouse_filter(0x202, mouse())
    recorder.mouse_filter(0x20A, mouse(data=(0x10000-120) << 16))
    recorder.mouse_filter(0x201, mouse(flags=1))
    physical = [event for kind, event in events if kind == 'user_input']
    assert [event['action'] for event in physical] == ['down', 'up', 'scroll']
    assert physical[0]['button'] == 'left' and physical[0]['game_x'] == 500
    assert physical[-1]['dy'] == -1
    assert events[-1][0] == 'observed_injected_input'
    before = len(events)
    recorder.mouse_filter(0x201, mouse(x=2500))
    assert len(events) == before


def test_mouse_moves_throttled_independently_per_source(trace, monkeypatch):
    recorder, events, _ = trace
    monkeypatch.setattr('src.user_input_trace.time.monotonic', lambda: 100)
    recorder.mouse_filter(0x200, mouse())
    recorder.mouse_filter(0x200, mouse(x=501))
    recorder.mouse_filter(0x200, mouse(flags=1))
    assert len([1 for kind, _ in events if kind == 'user_input']) == 1
    assert len([1 for kind, _ in events if kind == 'observed_injected_input']) == 1


def test_listener_lifecycle_never_suppresses_input(monkeypatch):
    from pynput import keyboard as keyboard_module, mouse as mouse_module
    factories = []
    for module in (keyboard_module, mouse_module):
        factory = Mock(return_value=SimpleNamespace(start=Mock(), stop=Mock(),
                                                    is_alive=lambda: True, join=Mock()))
        factories.append(factory)
        monkeypatch.setattr(module, 'Listener', factory)
    recorder = GameInputTrace(lambda: 0, Mock())
    recorder.start()
    for factory in factories:
        assert factory.call_args.kwargs['suppress'] is False
        factory.return_value.start.assert_called_once()
    recorder.stop()
    for factory in factories:
        factory.return_value.stop.assert_called_once()
        factory.return_value.join.assert_called_once()
    assert not recorder.running and not recorder.listeners


def test_key_names_use_key_codes_and_do_not_assemble_typed_text():
    assert key_name(0x57) == 'W'
    assert key_name(0xA0) == 'LeftShift'
    assert key_name(0x79) == 'F10'
    assert key_name(0xFE) == 'VK_FE'
