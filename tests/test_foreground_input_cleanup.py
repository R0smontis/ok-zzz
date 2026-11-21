from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from onedragon.base.controller import pc_controller_base as inputs
from onedragon.base.geometry.point import Point


@pytest.fixture
def devices(monkeypatch):
    move, down, up = Mock(), Mock(), Mock()
    native = SimpleNamespace(mouse_event=Mock(), GetSystemMetrics=Mock(return_value=0))
    monkeypatch.setattr(inputs.pyautogui, 'moveTo', move)
    monkeypatch.setattr(inputs.pyautogui, 'mouseDown', down)
    monkeypatch.setattr(inputs.pyautogui, 'mouseUp', up)
    monkeypatch.setattr(inputs.ctypes.windll, 'user32', native)
    monkeypatch.setattr(inputs.time, 'sleep', Mock())
    return SimpleNamespace(move=move, down=down, up=up, native=native)


def test_interrupted_click_releases_pressed_mouse_button(devices, monkeypatch):
    monkeypatch.setattr(inputs.time, 'sleep', Mock(side_effect=RuntimeError('interrupted hold')))

    with pytest.raises(RuntimeError, match='interrupted hold'):
        inputs.win_click(Point(100, 80))

    devices.down.assert_called_once_with(button=inputs.pyautogui.PRIMARY, _pause=False)
    devices.up.assert_called_once_with(button=inputs.pyautogui.PRIMARY)
    devices.native.mouse_event.assert_not_called()


def test_interrupted_drag_releases_button_without_moving_to_remaining_points(devices):
    devices.move.side_effect = [None, RuntimeError('drag interrupted')]

    with pytest.raises(RuntimeError, match='drag interrupted'):
        inputs.drag_mouse(Point(100, 80), Point(300, 100))

    devices.down.assert_called_once_with(_pause=False)
    devices.up.assert_called_once_with(button=inputs.pyautogui.PRIMARY)
    assert devices.move.call_count == 2


@pytest.mark.parametrize('primary', [False, True])
@pytest.mark.parametrize('swapped', [False, True])
def test_failsafe_still_releases_physical_button_and_propagates_abort(devices, primary, swapped):
    devices.native.GetSystemMetrics.return_value = int(swapped)
    devices.up.side_effect = inputs.pyautogui.FailSafeException('cursor in abort corner')

    with pytest.raises(inputs.pyautogui.FailSafeException, match='abort corner'):
        inputs.win_click(Point(100, 80), primary=primary)

    expected_flag = inputs.win32con.MOUSEEVENTF_LEFTUP if primary != swapped else inputs.win32con.MOUSEEVENTF_RIGHTUP
    devices.native.mouse_event.assert_called_once_with(expected_flag, 0, 0, 0, 0)
    assert devices.move.call_count == 1


def test_drag_failsafe_cleans_up_button_without_disabling_failsafe(devices):
    devices.move.side_effect = [None, inputs.pyautogui.FailSafeException('drag corner')]
    devices.up.side_effect = inputs.pyautogui.FailSafeException('release corner')
    original_failsafe = inputs.pyautogui.FAILSAFE

    with pytest.raises(inputs.pyautogui.FailSafeException):
        inputs.drag_mouse(Point(100, 80), Point(300, 100))

    assert inputs.pyautogui.FAILSAFE is original_failsafe
    devices.native.mouse_event.assert_called_once_with(inputs.win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def test_failed_pointer_position_before_mouse_down_does_not_release_an_unowned_button(devices):
    devices.move.side_effect = RuntimeError('position failed')

    with pytest.raises(RuntimeError, match='position failed'):
        inputs.win_click(Point(100, 80))

    devices.down.assert_not_called()
    devices.up.assert_not_called()
    devices.native.mouse_event.assert_not_called()


def test_alt_setup_interruption_releases_alt_before_click(devices, monkeypatch):
    controller = object.__new__(inputs.PcControllerBase)
    controller.game_win = SimpleNamespace(game2win_pos=lambda point: point)
    controller.keyboard_controller = SimpleNamespace(keyboard=Mock())
    monkeypatch.setattr(inputs.time, 'sleep', Mock(side_effect=RuntimeError('alt interrupted')))

    with pytest.raises(RuntimeError, match='alt interrupted'):
        controller._foreground_click(Point(100, 80), pc_alt=True)

    controller.keyboard_controller.keyboard.press.assert_called_once_with(inputs.keyboard.Key.alt)
    controller.keyboard_controller.keyboard.release.assert_called_once_with(inputs.keyboard.Key.alt)
    devices.down.assert_not_called()


def test_click_failure_also_releases_alt(devices, monkeypatch):
    controller = object.__new__(inputs.PcControllerBase)
    controller.game_win = SimpleNamespace(game2win_pos=lambda point: point)
    controller.keyboard_controller = SimpleNamespace(keyboard=Mock())
    devices.down.side_effect = RuntimeError('click failed')

    with pytest.raises(RuntimeError, match='click failed'):
        controller._foreground_click(Point(100, 80), pc_alt=True)

    devices.down.assert_called_once_with(button=inputs.pyautogui.PRIMARY, _pause=False)
    devices.up.assert_not_called()
    devices.native.mouse_event.assert_not_called()
    controller.keyboard_controller.keyboard.release.assert_called_once_with(inputs.keyboard.Key.alt)


@pytest.mark.parametrize('primary', [False, True])
def test_successful_click_keeps_one_press_release_pair(devices, primary):
    inputs.win_click(Point(100, 80), press_time=.04, primary=primary)

    button = inputs.pyautogui.PRIMARY if primary else inputs.pyautogui.SECONDARY
    devices.down.assert_called_once_with(button=button, _pause=False)
    devices.up.assert_called_once_with(button=button)
    devices.native.mouse_event.assert_not_called()


def test_successful_drag_reaches_destination_and_releases_once(devices):
    inputs.drag_mouse(Point(100, 80), Point(300, 100), duration=.5)

    assert devices.move.call_args.args == (300, 100)
    devices.down.assert_called_once_with(_pause=False)
    devices.up.assert_called_once_with(button=inputs.pyautogui.PRIMARY)


@pytest.fixture
def scaled_window_controller(monkeypatch):
    controller = object.__new__(inputs.PcControllerBase)
    controller.background_mode = controller.message_mode = False
    controller.game_win = SimpleNamespace(game2win_pos=lambda point: Point(100 + 2 * point.x, 200 + 2 * point.y))
    monkeypatch.setattr(inputs, 'get_current_mouse_pos', lambda: Point(500, 600))
    return controller


def test_default_drag_start_is_already_a_screen_coordinate(devices, scaled_window_controller):
    scaled_window_controller.drag_to(end=Point(300, 100))

    assert devices.move.call_args_list[0].args == (500, 600)
    assert devices.move.call_args.args == (700, 400)
    devices.up.assert_called_once_with(button=inputs.pyautogui.PRIMARY)


def test_explicit_drag_start_is_converted_from_game_coordinates(devices, scaled_window_controller):
    scaled_window_controller.drag_to(start=Point(20, 30), end=Point(300, 100))

    assert devices.move.call_args_list[0].args == (140, 260)
    assert devices.move.call_args.args == (700, 400)


@pytest.mark.parametrize('down', [-2, 1, 3])
def test_default_scroll_keeps_current_pointer_and_preserves_native_wheel_units(
        devices, scaled_window_controller, monkeypatch, down):
    monkeypatch.setattr(inputs.pyautogui.platformModule, '_position', lambda: (500, 600))
    monkeypatch.setattr(inputs.pyautogui.platformModule, '_size', lambda: (3840, 2160))

    scaled_window_controller.scroll(down)

    devices.move.assert_not_called()
    event = devices.native.mouse_event.call_args.args
    assert event[0] == inputs.win32con.MOUSEEVENTF_WHEEL and event[3] == -120 * down
    assert (event[1].value, event[2].value) == (65536 * 500 // 3840 + 1, 65536 * 600 // 2160 + 1)


def test_explicit_scroll_position_is_converted_once(devices, scaled_window_controller, monkeypatch):
    monkeypatch.setattr(inputs.pyautogui.platformModule, '_position', lambda: (500, 600))
    monkeypatch.setattr(inputs.pyautogui.platformModule, '_size', lambda: (3840, 2160))

    scaled_window_controller.scroll(1, pos=Point(300, 100))

    devices.move.assert_called_once_with(700, 400)
    event = devices.native.mouse_event.call_args.args
    assert event[0] == inputs.win32con.MOUSEEVENTF_WHEEL and event[3] == -120
    assert (event[1].value, event[2].value) == (65536 * 700 // 3840 + 1, 65536 * 400 // 2160 + 1)


def test_scroll_helper_accepts_current_pointer_without_a_position(devices, monkeypatch):
    monkeypatch.setattr(inputs.pyautogui.platformModule, '_position', lambda: (500, 600))
    monkeypatch.setattr(inputs.pyautogui.platformModule, '_size', lambda: (3840, 2160))

    inputs.win_scroll(1)

    devices.move.assert_not_called()
    assert devices.native.mouse_event.call_args.args[3] == -120


def test_mouse_down_fails_before_press_without_releasing_external_button(devices):
    devices.down.side_effect = inputs.pyautogui.FailSafeException('mouse-down failsafe')

    with pytest.raises(inputs.pyautogui.FailSafeException, match='mouse-down failsafe'):
        inputs.win_click(Point(100, 80))

    devices.up.assert_not_called()
    devices.native.mouse_event.assert_not_called()


def test_drag_mouse_down_fails_without_releasing_external_button(devices):
    devices.down.side_effect = inputs.pyautogui.FailSafeException('drag mouse-down failsafe')

    with pytest.raises(inputs.pyautogui.FailSafeException, match='drag mouse-down failsafe'):
        inputs.drag_mouse(Point(100, 80), Point(300, 100))

    devices.up.assert_not_called()
    devices.native.mouse_event.assert_not_called()


def test_alt_down_fails_without_releasing_an_unowned_key(devices):
    controller = object.__new__(inputs.PcControllerBase)
    controller.game_win = SimpleNamespace(game2win_pos=lambda point: point)
    keyboard = SimpleNamespace(press=Mock(side_effect=RuntimeError('alt down failed')), release=Mock())
    controller.keyboard_controller = SimpleNamespace(keyboard=keyboard)

    with pytest.raises(RuntimeError, match='alt down failed'):
        controller._foreground_click(Point(100, 80), pc_alt=True)

    keyboard.release.assert_not_called()
    devices.down.assert_not_called()
