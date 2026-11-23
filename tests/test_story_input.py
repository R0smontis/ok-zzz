"""All story actions use physical mouse input without changing other tasks' input mode."""
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from onedragon.base.controller import pc_controller_base as mouse
from onedragon.base.controller.input_guard import debug_control_owned
from onedragon.base.geometry.point import Point
from src.navigation.dialogue import send_story_action
from zzz_od.application.commission_assistant.story_dialogue import StoryAction
from zzz_od.controller.zzz_controller import ZzzController

HWND = 101


@pytest.fixture
def scene(monkeypatch):
    controller = ZzzController.__new__(ZzzController)
    controller.background_mode = True
    controller.message_mode = False
    controller._game_input_mode = 'gamepad'
    controller.battle_input_guard = lambda: False
    controller.battle_action_guard = None
    controller.btn_controller = Mock()
    controller.game_win = SimpleNamespace(
        get_hwnd=Mock(return_value=HWND), is_win_valid=True, is_win_active=True,
        game2win_pos=lambda point: Point(40 + point.x * 2, 100 + point.y * 2))
    window = controller.game_win
    window.active = Mock(side_effect=lambda: setattr(window, 'is_win_active', True))
    cursor = [(0, 0)]
    move = Mock(side_effect=lambda x, y, **_: cursor.__setitem__(0, (x, y)))
    down, up = Mock(), Mock()
    monkeypatch.setattr(mouse.pyautogui, 'moveTo', move)
    monkeypatch.setattr(mouse.pyautogui, 'position', lambda: cursor[0])
    monkeypatch.setattr(mouse.pyautogui, 'mouseDown', down)
    monkeypatch.setattr(mouse.pyautogui, 'mouseUp', up)
    monkeypatch.setattr(mouse.time, 'sleep', lambda _: None)
    return SimpleNamespace(ctx=SimpleNamespace(controller=controller), controller=controller,
                           screen=np.zeros((1080, 1920, 3), np.uint8),
                           move=move, down=down, up=up, window=window, cursor=cursor)


def deliver(scene, action, allowed=lambda: True):
    return send_story_action(scene.ctx, scene.screen, action, expected_hwnd=HWND,
                             input_allowed=allowed)


@pytest.mark.parametrize('background,message', [(False, False), (True, False), (False, True)])
@pytest.mark.parametrize('kind', ['advance', 'option', 'skip', 'confirm_skip', 'menu', 'auto'])
def test_every_story_action_uses_mouse_without_reconfiguring_other_tasks(scene, background, message, kind):
    scene.controller.background_mode = background
    scene.controller.message_mode = message
    pad = scene.controller.btn_controller
    scene.controller.action_keys = keys = {'normal_attack': 'xbox_x'}
    action = StoryAction(kind, Point(960, 620), '继续')
    assert deliver(scene, action)
    scene.move.assert_called_once_with(1960, 1340, _pause=False)
    scene.down.assert_called_once_with(button=mouse.pyautogui.PRIMARY, _pause=False)
    scene.up.assert_called_once_with(button=mouse.pyautogui.PRIMARY)
    assert scene.controller.background_mode is background
    assert scene.controller.message_mode is message
    assert scene.controller.btn_controller is pad and scene.controller.action_keys is keys
    assert scene.controller._game_input_mode == 'keyboard_mouse'
    assert not pad.method_calls
    assert not scene.controller.btn_press('xbox_x', .12)  # Combat's guard is still enforced.
    assert not pad.method_calls


def test_background_story_activates_window_then_uses_a_fresh_frame(scene):
    scene.window.is_win_active = False
    action = StoryAction('skip', Point(1750, 70), '跳过剧情')
    assert not deliver(scene, action)
    scene.window.active.assert_called_once_with()
    scene.move.assert_not_called()
    scene.down.assert_not_called()
    assert deliver(scene, action)
    scene.down.assert_called_once()


def test_failed_activation_never_clicks_another_window(scene):
    scene.window.is_win_active = False
    scene.window.active = Mock(return_value=False)
    assert not deliver(scene, StoryAction('advance', Point(960, 900), '继续对话'))
    scene.down.assert_not_called()
    scene.move.assert_not_called()


@pytest.mark.parametrize('reason', ['cancelled', 'debug_control', 'wrong_window', 'closed_window'])
def test_invalid_story_input_never_moves_mouse_or_activates_game(scene, reason):
    allowed = lambda: reason != 'cancelled'
    scene.window.is_win_active = False
    if reason == 'wrong_window':
        scene.window.get_hwnd.return_value += 1
    elif reason == 'closed_window':
        scene.window.is_win_valid = False
    elif reason == 'debug_control':
        debug_control_owned.set()
    try:
        assert not deliver(scene, StoryAction('skip', Point(1750, 70), '跳过剧情'), allowed)
        scene.move.assert_not_called()
        scene.down.assert_not_called()
        scene.window.active.assert_not_called()
    finally:
        debug_control_owned.clear()


@pytest.mark.parametrize('change', ['cancel', 'focus', 'handle', 'coordinates', 'controller'])
def test_state_is_rechecked_after_mouse_movement_before_press(scene, change):
    allowed = [True]

    def interrupted_move(x, y, **_):
        scene.cursor[0] = (x, y)
        if change == 'cancel':
            allowed[0] = False
        elif change == 'focus':
            scene.window.is_win_active = False
        elif change == 'handle':
            scene.window.get_hwnd.return_value += 1
        elif change == 'coordinates':
            scene.window.game2win_pos = lambda point: Point(point.x, point.y)
        else:
            scene.ctx.controller = None

    scene.move.side_effect = interrupted_move
    assert not deliver(scene, StoryAction('skip', Point(1750, 70), '跳过剧情'), lambda: allowed[0])
    scene.move.assert_called_once()
    scene.down.assert_not_called()
    scene.up.assert_not_called()


@pytest.mark.parametrize('interruption', ['moved', 'safety_corner'])
def test_story_resumes_after_manual_pointer_interruption(scene, interruption):
    move = scene.move.side_effect

    def interrupt(*_args, **_kwargs):
        if interruption == 'safety_corner':
            raise mouse.pyautogui.FailSafeException('manual abort corner')
        scene.cursor[0] = (20, 30)

    action = StoryAction('advance', Point(960, 900), '继续对话')
    scene.move.side_effect = interrupt
    assert not deliver(scene, action)
    scene.down.assert_not_called()
    scene.move.side_effect = move
    assert deliver(scene, action)
    scene.down.assert_called_once()
    scene.up.assert_called_once()

@pytest.mark.parametrize('text', ['购买道具', '确认解锁', '消耗材料', '兑换奖励', '拆解驱动盘'])
def test_sensitive_choice_never_activates_or_clicks(scene, text):
    scene.window.is_win_active = False
    assert not deliver(scene, StoryAction('option', Point(1600, 700), text))
    scene.window.active.assert_not_called()
    scene.move.assert_not_called()
    scene.down.assert_not_called()


def test_no_verified_action_means_no_focus_or_input(scene):
    scene.window.is_win_active = False
    assert not deliver(scene, None)
    assert not deliver(scene, StoryAction('unknown', Point(960, 900), '未知'))
    assert not deliver(scene, StoryAction('skip', Point(1920, 1080), '跳过剧情'))
    scene.window.active.assert_not_called()
    scene.move.assert_not_called()
    scene.down.assert_not_called()


def test_mouse_exception_releases_button_without_touching_pad(scene, monkeypatch):
    monkeypatch.setattr(mouse.time, 'sleep', Mock(side_effect=RuntimeError('interrupted')))
    with pytest.raises(RuntimeError, match='interrupted'):
        deliver(scene, StoryAction('advance', Point(960, 900), '继续对话'))
    scene.down.assert_called_once()
    scene.up.assert_called_once()
    assert not scene.controller.btn_controller.method_calls
