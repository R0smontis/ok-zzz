"""后台任务只操作绑定窗口；不向桌面发送输入。"""
import threading
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest
import win32con

from onedragon.base.geometry.point import Point
from src.controls.window_input import WindowMessageInput
from test_runtime_interactions import task_factory


@pytest.fixture
def backend(monkeypatch):
    import src.controls.window_input as source
    from onedragon.base.controller import pc_controller_base as controller
    posts, selected = [], [101]
    window = SimpleNamespace(get_hwnd=lambda: selected[0], is_win_valid=True, init_win=Mock(),
        get_scaled_game_pos=lambda p: Point(p.x*2, p.y*2), active=Mock(side_effect=AssertionError('抢前台')))
    for obj, name in ((source.win32api, 'SetCursorPos'), (source.win32gui, 'SetForegroundWindow'),
                      (controller.pyautogui, 'moveTo'), (controller.pyautogui, 'mouseDown'),
                      (controller.pyautogui, 'scroll')):
        monkeypatch.setattr(obj, name, Mock(side_effect=AssertionError('物理输入')))
    monkeypatch.setattr(source.win32gui, 'PostMessage', lambda *args: posts.append(args))
    monkeypatch.setattr(source.win32gui, 'ClientToScreen', lambda hwnd, p: (p[0]-300, p[1]+100))
    return WindowMessageInput(window), posts, selected


def test_click_drag_scroll_hover_and_text_do_not_use_desktop(backend):
    device, posts, _ = backend
    assert device.click(Point(20, 30), duration=0)
    assert (101, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, device.pack(40, 60)) in posts
    assert posts[-1] == (101, win32con.WM_LBUTTONUP, 0, device.pack(40, 60))
    for button, number, flag in [('x1', 1, 0x20), ('x2', 2, 0x40)]:
        assert device.click(Point(20, 30), duration=0, button=button)
        assert posts[-2][1:3] == (0x020b, (number << 16) | flag)
        assert posts[-1][1:3] == (0x020c, number << 16)
        assert device.press('mouse_' + button, press_time=0)
        assert posts[-1][1:3] == (0x020c, number << 16)
    assert device.drag(Point(20, 30), Point(50, 60), duration=0)
    assert posts[-1][-1] == device.pack(100, 120)
    assert device.scroll(1, Point(20, 30))
    assert posts[-1] == (101, win32con.WM_MOUSEWHEEL, ((-120)&0xffff)<<16, device.pack(-260, 160))
    assert device.move(Point(80, 90))
    text = '测试😀'
    assert device.input_text(text, interval=0)
    units = [int.from_bytes(text.encode('utf-16-le')[i:i+2], 'little') for i in range(0, len(text.encode('utf-16-le')), 2)]
    assert [p[2] for p in posts if p[1] == win32con.WM_CHAR] == units
    device.window.active.assert_not_called()


def test_restarted_window_aborts_and_releases_original_target(backend, monkeypatch):
    import src.controls.window_input as source
    device, posts, selected = backend
    def post(*args):
        posts.append(args)
        if args[1] == win32con.WM_LBUTTONDOWN:
            selected[0] = 202
    monkeypatch.setattr(source.win32gui, 'PostMessage', post)
    assert not device.drag(Point(20, 30), Point(50, 60), .1)
    assert posts[-1][0:2] == (101, win32con.WM_LBUTTONUP)
    assert not any(p[0] == 202 for p in posts)


def test_stop_cancels_long_key_and_releases_mouse(backend):
    device, posts, _ = backend
    device.press('mouse_left')
    worker = threading.Thread(target=lambda: device.press('w', press_time=5))
    worker.start()
    # 键按下之后再发停止，不依赖固定 sleep。
    for _ in range(1000):
        if any(p[1] == win32con.WM_KEYDOWN for p in posts):
            break
        threading.Event().wait(.001)
    device.reset()
    worker.join(.5)
    assert not worker.is_alive()
    assert any(p[1] == win32con.WM_KEYUP and p[3] & (1 << 31) for p in posts)
    assert any(p[1] == win32con.WM_LBUTTONUP for p in posts)
    assert not device._held


def test_controller_routes_every_menu_operation_to_messages(backend):
    from onedragon.base.controller.pc_controller_base import PcControllerBase
    device, posts, _ = backend
    controller = PcControllerBase.__new__(PcControllerBase)
    controller.background_mode, controller.message_mode = True, False
    controller.window_input, controller.game_win = device, device.window
    controller.keyboard_controller = Mock()
    controller.click(Point(20,30), press_time=0)
    controller.drag_to(Point(50,60), Point(20,30), duration=0)
    controller.scroll(1, Point(20,30))
    controller.mouse_move(Point(20,30))
    controller.input_str('abc', interval=0)
    controller.keyboard_tap('space')
    controller.keyboard_press('w', 0)
    controller.delete_all_input()
    controller.active_window()
    assert posts and controller.keyboard_controller.mock_calls == []


@pytest.mark.parametrize('background', [True, False])
def test_application_inputs_follow_switch_never_activate_and_release_after_error(background):
    import src.controls.application_input as policy
    controller = SimpleNamespace(background_mode=False, cancel_inputs=Mock())
    ctx = SimpleNamespace(controller=controller)
    calls = []
    def init(activate=True):
        calls.append(activate)
        controller.background_mode = background  # The controller reads the start page switch.
    ctx.init_controller = init
    task = SimpleNamespace(ctx=ctx, log_info=Mock(), log_error=Mock(), info={})
    with pytest.raises(ValueError, match='任务失败'):
        with policy.application_inputs(task):
            assert task.info['任务交互方式'] == ('后台模式' if background else '前台模式')
            raise ValueError('任务失败')
    assert calls == [False]
    controller.cancel_inputs.assert_called_once()


def test_background_mode_without_virtual_gamepad_stops_instead_of_falling_back():
    import src.controls.application_input as policy
    from src.controls.interaction import BACKGROUND_UNAVAILABLE
    controller = SimpleNamespace(background_mode=False, cancel_inputs=Mock())
    def init(activate=True):
        raise RuntimeError(BACKGROUND_UNAVAILABLE)
    ctx = SimpleNamespace(controller=controller, init_controller=init)
    task = SimpleNamespace(ctx=ctx, log_info=Mock(), log_error=Mock(), info={})
    body = Mock()
    with pytest.raises(RuntimeError, match='ViGEmBus'):
        with policy.application_inputs(task):
            body()
    body.assert_not_called()
    task.log_error.assert_called_once_with(BACKGROUND_UNAVAILABLE, notify=True)
    controller.cancel_inputs.assert_called_once()


@pytest.mark.parametrize('ours,game,blocked', [(False, True, True), (True, True, False), (False, False, False)])
def test_elevated_game_stops_application_before_any_input(monkeypatch, ours, game, blocked):
    import win32gui
    import src.controls.application_input as policy
    import src.controls.window_input as source
    monkeypatch.setattr(source, '_process_elevated', lambda pid=None: game if pid else ours)
    assert source.input_blocked_by_elevation(win32gui.GetDesktopWindow()) is blocked
    monkeypatch.setattr(source, 'input_blocked_by_elevation', lambda hwnd: blocked)
    controller = SimpleNamespace(background_mode=True, cancel_inputs=Mock(),
                                 game_win=SimpleNamespace(get_hwnd=lambda: 101))
    ctx = SimpleNamespace(controller=controller, init_controller=lambda activate: None)
    task = SimpleNamespace(ctx=ctx, log_info=Mock(), log_error=Mock(), info={})
    body = Mock()
    if blocked:
        with pytest.raises(PermissionError, match='管理员'):
            with policy.application_inputs(task):
                body()
        body.assert_not_called()
        assert task.info['执行结果'] == '需要管理员权限'
    else:
        with policy.application_inputs(task):
            body()
        body.assert_called_once()
    controller.cancel_inputs.assert_called_once()


@pytest.mark.parametrize('background', [True, False])
def test_only_foreground_mode_runs_focus_stealing_hook_on_enable(task_factory, monkeypatch, background):
    import src.controls.interaction as interaction
    from src.tasks.app_tasks import App_LostVoid
    monkeypatch.setattr(interaction, 'background_mode_selected', lambda: background)
    task = task_factory(App_LostVoid)
    task.enable()
    assert task.enabled
    assert task.executor.interaction.on_run.called is not background


def test_gamepad_mode_switch_nudges_once_without_net_camera_movement(monkeypatch):
    # Live 2026-10-12: in keyboard/mouse mode the game only switched its prompts on the first
    # View press; the map opened on the second. A stick nudge does the switch instead.
    from onedragon.base.controller import pc_controller_base
    from onedragon.base.controller.pc_controller_base import PcControllerBase
    monkeypatch.setattr(pc_controller_base.time, 'sleep', lambda _: None)
    controller = PcControllerBase.__new__(PcControllerBase)
    controller._game_input_mode = 'keyboard_mouse'
    controller.btn_controller = Mock()
    controller._ensure_gamepad_mode()
    assert controller._game_input_mode == 'gamepad'
    nudge = PcControllerBase.GAMEPAD_SWITCH_NUDGE_SECONDS
    assert controller.btn_controller.press.call_args_list == [
        call('xbox_rs_up', press_time=nudge), call('xbox_rs_down', press_time=nudge)]
    controller.btn_controller.tap.assert_not_called()
    controller._ensure_gamepad_mode()
    assert controller.btn_controller.press.call_count == 2


def test_enabling_background_mode_forgets_known_gamepad_mode(monkeypatch):
    from onedragon.base.controller import pc_controller_base
    from onedragon.base.controller.pc_controller_base import PcControllerBase
    monkeypatch.setattr(pc_controller_base.pc_button_utils, 'is_vgamepad_installed', lambda: True)
    controller = PcControllerBase.__new__(PcControllerBase)
    controller._game_input_mode = 'gamepad'
    controller.enable_xbox = Mock()
    controller.enable_background_mode('xbox')
    assert controller.background_mode
    assert controller._game_input_mode != 'gamepad'  # The user may have played with keyboard/mouse.


def test_real_windows_receiver_accepts_background_messages():
    from src.controls.background_input_check import check_background_input
    result = check_background_input()
    assert result['native_receiver'] == 'passed'
    assert result['game_input'] == 'none'
