"""任务 UI 到运行逻辑的回归测试；所有输入均使用替身设备。"""
import copy
import gettext
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from ok import BaseTask, TriggerTask, og
from src.tasks.auto_combat_task import AutoCombatTask, DodgeAssistantTriggerTask
from src.tasks.daily_task import OneDragonDailyTask


@pytest.fixture
def task_factory(monkeypatch):
    tasks = []
    executor = SimpleNamespace(
        scene=None, get_all_tasks=lambda: tasks,
        interaction=SimpleNamespace(on_run=Mock()),
        enqueue_onetime_task=Mock(), remove_onetime_task=Mock(), _wake_executor=Mock(),
        pause=Mock(), start=Mock(), is_executor_thread=lambda: False,
    )
    app = SimpleNamespace(tr=lambda text: text)
    monkeypatch.setattr(BaseTask, 'ensure_capture', lambda self: None)
    monkeypatch.setattr(BaseTask, 'log_info', Mock())
    monkeypatch.setattr(BaseTask, 'log_error', Mock())

    def create(cls, ctx=None):
        task = cls(executor=executor, app=app)
        task.config = copy.deepcopy(task.default_config)
        tasks.append(task)
        if ctx is not None:
            monkeypatch.setattr(og, 'my_app', SimpleNamespace(context=ctx))
        return task
    return create


def battle_context():
    battle = SimpleNamespace(auto_op=None, auto_ultimate_enabled=True,
                             last_check_end_result=None, stop_auto_battle=Mock(),
                             dodge_context=SimpleNamespace(event_listener=None),
                             init_battle_context=Mock(), clear_all_states=Mock(),
                             start_context_async=Mock(),
                             state_record_service=SimpleNamespace(update_state=Mock(), batch_update_states=Mock()),
                             is_normal_attack_btn_available=Mock(return_value=True))
    battle.start_actions = Mock()
    battle.stop_actions = Mock()
    def load(name, sub_dir):
        battle.auto_op = SimpleNamespace(name=name, sub_dir=sub_dir,
                                        start_running_async=battle.start_actions,
                                        stop_running=battle.stop_actions,
                                        _task_lock=threading.Lock(), _stop_running_task=Mock())
    def start(auto_ultimate_enabled=True):
        battle.auto_ultimate_enabled = auto_ultimate_enabled
    battle.init_auto_op = Mock(side_effect=load)
    battle.start_auto_battle = Mock(side_effect=start)
    battle.check_battle_state = Mock(return_value=False)
    controller = SimpleNamespace(init_game_win=Mock(return_value=True),
                                 normalize_frame=lambda frame: frame, battle_input_guard=None,
                                 background_mode=False, game_win=SimpleNamespace(
                                     get_hwnd=lambda: 101, is_win_valid=True, is_win_active=True),
                                 btn_controller=SimpleNamespace(reset=Mock()), is_moving=False)
    return SimpleNamespace(auto_battle_context=battle, controller=controller,
                           init_for_application=Mock())


@pytest.fixture
def initialized_assistant(task_factory, monkeypatch):
    from zzz_od.application.battle_assistant import battle_assistant_input_mode as input_mode
    from zzz_od.auto_battle import battle_presence
    monkeypatch.setattr(input_mode, 'apply_battle_assistant_input_mode', Mock(return_value=(True, 'ok')))
    presence = Mock(return_value=None)
    monkeypatch.setattr(battle_presence, 'detect_battle_presence', presence)
    frames = [np.zeros((1080, 1920, 3), np.uint8)]
    monkeypatch.setattr(BaseTask, 'frame', property(lambda self: frames[0]))
    created = []

    def create(cls=AutoCombatTask):
        ctx = battle_context()
        task = task_factory(cls, ctx)
        task.enable()
        task.run()
        created.append(task)
        return task, ctx, frames, presence

    yield create
    for task in created:
        task.disable()


def test_idle_hud_prepares_detection_without_starting_actions(initialized_assistant):
    task, ctx, _, _ = initialized_assistant()
    for _ in range(4):
        task._last_frame_check = None
        task.run()
    assert task._engine_started and not task._actions_running
    assert not ctx.controller.battle_input_guard()
    ctx.auto_battle_context.start_actions.assert_not_called()
    assert ctx.auto_battle_context.check_battle_state.call_args.kwargs['passive']
    assert task.info['助手状态'] == '等待敌人'


def test_enemy_disappearance_is_ignored_until_ten_second_burst_expires(initialized_assistant):
    import time
    task, ctx, _, presence = initialized_assistant()
    presence.return_value = '锁定敌人'
    task._last_frame_check = None
    task.run()
    old_guard = task._make_input_guard()
    assert old_guard() and task._actions_running
    assert task._input_until - time.monotonic() == pytest.approx(10, abs=0.1)
    checked = presence.call_count
    presence.return_value = None
    task._last_frame_check = None
    task.run()
    assert old_guard() and task._actions_running
    assert presence.call_count == checked
    ctx.auto_battle_context.stop_actions.assert_not_called()
    task._input_until = time.monotonic() - 1
    task._last_frame_check = None
    task.run()
    assert not old_guard() and not task._actions_running
    ctx.auto_battle_context.stop_actions.assert_called_once()
    ctx.controller.btn_controller.reset.assert_called_once()
    # Models remain loaded; the next enemy starts a new, independently gated sequence.
    presence.return_value = '敌人血条'
    task._last_frame_check = None
    task.run()
    assert task._input_allowed() and not old_guard()
    assert ctx.auto_battle_context.start_actions.call_count == 2
    ctx.auto_battle_context.init_auto_op.assert_called_once()


def test_burst_rechecks_once_at_deadline_and_opens_another_ten_seconds(initialized_assistant, monkeypatch):
    import time
    task, ctx, _, presence = initialized_assistant()
    task._watchdog_stop.set()  # Control time deterministically in this test.
    clock = [1000.0]
    monkeypatch.setattr(time, 'monotonic', lambda: clock[0])
    presence.return_value = '敌人血条'
    task._last_frame_check = None
    task.run()
    old_guard = task._make_input_guard()
    checked = presence.call_count
    assert task._input_until == 1010
    for timestamp in (1000.02, 1001, 1005, 1009.99):
        clock[0] = timestamp
        task.run()
        assert task._input_allowed()
    assert presence.call_count == checked
    assert task._input_until == 1010
    clock[0] = 1010
    assert not task._input_allowed()
    task._last_frame_check = None
    task.run()
    assert presence.call_count == checked + 1
    assert task._input_until == 1020
    assert task._input_allowed() and not old_guard()
    assert ctx.auto_battle_context.start_actions.call_count == 2
    ctx.controller.btn_controller.reset.assert_called_once()


def test_combat_warning_does_not_shorten_or_extend_existing_burst(initialized_assistant, monkeypatch):
    import time
    task, _, _, presence = initialized_assistant()
    task._watchdog_stop.set()
    clock = [1000.0]
    monkeypatch.setattr(time, 'monotonic', lambda: clock[0])
    presence.return_value = '敌人血条'
    task._last_frame_check = None
    task.run()
    clock[0] = 1009.0
    task._last_frame_check = None
    task.run()
    assert task._on_dodge_event('闪避识别-黄光', time.time())
    assert task._input_until == 1010.0
    assert task._input_allowed()


def test_combat_burst_watchdog_stops_without_waiting_for_next_enemy_scan(initialized_assistant):
    import time
    task, ctx, _, presence = initialized_assistant()
    presence.return_value = '敌人血条'
    task._last_frame_check = None
    task.run()
    checked = presence.call_count
    task._input_until = time.monotonic() - 0.01
    deadline = time.monotonic() + 0.5
    while task._actions_running and time.monotonic() < deadline:
        threading.Event().wait(0.01)
    assert not task._actions_running and not task._input_allowed()
    assert presence.call_count == checked
    ctx.controller.btn_controller.reset.assert_called_once()


def test_capture_loss_releases_input_immediately(initialized_assistant):
    task, ctx, frames, presence = initialized_assistant()
    presence.return_value = '敌人血条'
    task._last_frame_check = None
    task.run()
    frames[0] = None
    task.run()
    assert not task._input_allowed() and not task._actions_running
    ctx.controller.btn_controller.reset.assert_called_once()


def test_dodge_idle_and_stale_events_do_not_allow_input(initialized_assistant):
    import time
    task, ctx, _, _ = initialized_assistant(DodgeAssistantTriggerTask)
    assert ctx.auto_battle_context.auto_op.event_only
    assert not task._input_allowed()
    now = time.time()
    assert not task._on_dodge_event(None, now)
    assert not task._on_dodge_event('闪避识别-红光', now - 1)
    assert not task._on_dodge_event('闪避识别-黄光', task._session_started - 0.01)
    ctx.auto_battle_context.state_record_service.update_state.assert_not_called()
    task.disable()
    assert not task._on_dodge_event('闪避识别-声音', time.time())
    assert ctx.controller.battle_input_guard is None


@pytest.mark.parametrize('event', ['闪避识别-红光', '闪避识别-黄光', '闪避识别-声音'])
def test_fresh_dodge_event_opens_bounded_response(initialized_assistant, event):
    import time
    task, ctx, _, _ = initialized_assistant(DodgeAssistantTriggerTask)
    assert task._on_dodge_event(event, time.time())
    assert task._input_allowed()
    record = ctx.auto_battle_context.state_record_service.update_state.call_args.args[0]
    assert record.state_name == event
    # Expiration denies further presses, including already queued worker operations.
    guard = task._make_input_guard()
    task._input_until = time.monotonic() - 1
    assert not guard()
    task._suspend_actions()
    ctx.controller.btn_controller.reset.assert_called_once()


def test_persistent_flash_is_one_event(initialized_assistant, monkeypatch):
    import time
    task, ctx, _, _ = initialized_assistant(DodgeAssistantTriggerTask)
    clock = [time.time()]
    monkeypatch.setattr(time, 'time', lambda: clock[0])
    assert task._on_dodge_event('闪避识别-红光', clock[0])
    for _ in range(40):
        clock[0] += 0.02
        assert not task._on_dodge_event('闪避识别-红光', clock[0])
    ctx.auto_battle_context.state_record_service.update_state.assert_called_once()
    assert not task._on_dodge_event(None, clock[0])
    clock[0] += 0.12
    assert task._on_dodge_event('闪避识别-红光', clock[0])


def test_warning_can_start_combat_without_visible_health_bar(initialized_assistant):
    import time
    task, ctx, _, _ = initialized_assistant()
    assert task._on_dodge_event('闪避识别-黄光', time.time())
    assert task._actions_running and task._input_allowed()
    ctx.auto_battle_context.start_actions.assert_called_once()


def test_watchdog_releases_held_input_when_frames_stop(initialized_assistant):
    import time
    task, ctx, _, _ = initialized_assistant(DodgeAssistantTriggerTask)
    assert task._on_dodge_event('闪避识别-红光', time.time())
    task._last_frame_seen = time.monotonic() - 2
    deadline = time.monotonic() + 0.5
    while task._actions_running and time.monotonic() < deadline:
        threading.Event().wait(0.01)
    assert not task._actions_running
    ctx.controller.btn_controller.reset.assert_called_once()


def test_controller_guard_blocks_buttons_turn_and_stale_workers(monkeypatch):
    from zzz_od.controller.zzz_controller import ZzzController
    from zzz_od.controller.zzz_pc_controller import ZPcController
    from onedragon.base.controller.input_guard import execution_input_guard
    controller = ZzzController.__new__(ZzzController)
    allowed = [False]
    controller.battle_input_guard = lambda: allowed[0]
    controller.btn_controller = SimpleNamespace(release=Mock())
    taps, presses, turns = Mock(), Mock(), Mock()
    monkeypatch.setattr(ZPcController, 'btn_tap', taps)
    monkeypatch.setattr(ZPcController, 'btn_press', presses)
    monkeypatch.setattr(ZPcController, 'move_mouse_relative', turns)
    controller.btn_tap('attack')
    controller.btn_press('dodge', 0.2)
    controller.move_mouse_relative(100, 0)
    controller.btn_release('attack')
    taps.assert_not_called()
    presses.assert_not_called()
    turns.assert_not_called()
    controller.btn_controller.release.assert_called_once_with('attack')
    allowed[0] = True
    controller.btn_tap('attack')
    taps.assert_called_once_with('attack')
    token = execution_input_guard.set(lambda: False)
    try:
        # Even after a new session enables input, an old worker remains blocked.
        controller.btn_press('dodge')
        controller.move_mouse_relative(50, 0)
    finally:
        execution_input_guard.reset(token)
    presses.assert_not_called()
    turns.assert_not_called()


def test_real_dodge_template_is_idle_then_reacts_once(ctx, stubbed_controller, task_factory, monkeypatch):
    import time
    from zzz_od.application.battle_assistant import battle_assistant_input_mode as input_mode
    context, recorder = stubbed_controller
    battle = context.auto_battle_context
    monkeypatch.setattr(input_mode, 'apply_battle_assistant_input_mode', Mock(return_value=(True, 'ok')))
    monkeypatch.setattr(context, 'init_for_application', Mock())
    monkeypatch.setattr(context.controller, 'init_game_win', Mock(return_value=True))
    monkeypatch.setattr(context.controller, 'background_mode', False)
    monkeypatch.setattr(type(context.controller.game_win), 'get_hwnd', lambda self: 101)
    monkeypatch.setattr(type(context.controller.game_win), 'is_win_valid', property(lambda self: True))
    monkeypatch.setattr(type(context.controller.game_win), 'is_win_active', property(lambda self: True))
    monkeypatch.setattr(battle, 'start_context_async', Mock())
    monkeypatch.setattr(battle, 'is_normal_attack_btn_available', Mock(return_value=True))
    monkeypatch.setattr(battle, 'check_battle_state', Mock(return_value=True))
    classified = SimpleNamespace(class_idx=0)
    battle.init_auto_op('闪避', sub_dir='dodge')
    monkeypatch.setattr(battle.dodge_context._flash_model, 'run', Mock(return_value=classified))
    monkeypatch.setattr(BaseTask, 'frame', property(lambda self: np.zeros((1080, 1920, 3), np.uint8)))
    task = task_factory(DodgeAssistantTriggerTask, context)
    task.enable()
    try:
        task.run()
        # A real parsed DSL with real asynchronous dispatch, using a recording device.
        time.sleep(0.08)
        assert not battle.dodge_context.check_dodge_flash(task.frame, time.time())
        assert recorder.events == []
        time.sleep(0.03)
        classified.class_idx = 2
        assert battle.dodge_context.check_dodge_flash(task.frame, time.time())
        deadline = time.monotonic() + 0.15
        while not recorder.events and time.monotonic() < deadline:
            time.sleep(0.005)
        dodge = context.game_config.get_action_keys('keyboard')['dodge']
        assert ('tap', dodge) in recorder.events
        time.sleep(0.03)
        assert not battle.dodge_context.check_dodge_flash(task.frame, time.time())
        task._suspend_actions()
        task._last_frame_seen = time.monotonic()
        time.sleep(0.25)
        assert recorder.events == []
    finally:
        task.disable()


def test_old_executor_completion_cannot_change_new_session_count():
    from concurrent.futures import Future
    from onedragon.base.conditional_operation.operator import ConditionalOperator
    from onedragon.thread.atomic_int import AtomicInt
    op = ConditionalOperator.__new__(ConditionalOperator)
    op._task_lock = threading.Lock()
    op._run_generation = 5
    op.running_executor_cnt = AtomicInt()
    op.running_executor_cnt.set(1)
    finished = Future()
    finished.set_result(True)
    op._on_task_done(finished, generation=3)
    assert op.running_executor_cnt.get() == 1
    op._on_task_done(finished, generation=5)
    assert op.running_executor_cnt.get() == 0


@pytest.fixture
def dialogue_task(task_factory, monkeypatch):
    from src.tasks.dialogue_task import AutoDialogueTriggerTask
    from zzz_od.application.commission_assistant.dialogue_detector import DialogueAction
    from onedragon.base.geometry.point import Point
    ctx = SimpleNamespace(init=Mock(), controller=SimpleNamespace(
        init_game_win=Mock(return_value=True), normalize_frame=lambda f: f,
        game_win=SimpleNamespace(is_win_active=True, is_win_valid=True,
                                 get_hwnd=Mock(return_value=101)),
        click_dialogue_event=Mock(return_value=True)))
    task = task_factory(AutoDialogueTriggerTask, ctx)
    task._detector_ctx = ctx
    task._detector = SimpleNamespace(detect=Mock(return_value=None))
    frame = [np.zeros((1080, 1920, 3), np.uint8)]
    monkeypatch.setattr(BaseTask, 'frame', property(lambda self: frame[0]))
    task.enable()
    yield task, ctx, frame, DialogueAction('skip', Point(1750, 70), '跳过剧情')
    task.disable()


def test_dialogue_trigger_is_idle_and_sends_one_click_per_current_event(dialogue_task):
    task, ctx, _, action = dialogue_task
    task.run()
    ctx.controller.click_dialogue_event.assert_not_called()
    task._detector.detect.return_value = action
    task._last_check = None
    task.run()
    ctx.controller.click_dialogue_event.assert_called_once_with(
        action.point, expected_hwnd=101, allow_background=False)
    task._last_check = None
    task.run()
    assert ctx.controller.click_dialogue_event.call_count == 1  # Current event still obeys debounce.
    task._detector.detect.return_value = None
    task._last_click = None
    task._last_check = None
    task.run()
    assert ctx.controller.click_dialogue_event.call_count == 1
    assert task.info['助手状态'] == '等待对话'


def test_dialogue_trigger_discards_disabled_or_old_ocr_result(dialogue_task):
    task, ctx, _, action = dialogue_task
    def detect(*args, **kwargs):
        task.disable()
        task.enable()
        return action
    task._detector.detect.side_effect = detect
    task.run()
    ctx.controller.click_dialogue_event.assert_not_called()


def test_dialogue_trigger_discards_slow_result(dialogue_task, monkeypatch):
    import time
    task, ctx, _, action = dialogue_task
    clock = [1000.0]
    monkeypatch.setattr(time, 'monotonic', lambda: clock[0])
    def detect(*args, **kwargs):
        clock[0] += 0.6
        return action
    task._detector.detect.side_effect = detect
    task.run()
    ctx.controller.click_dialogue_event.assert_not_called()
    assert '过期' in task.info['助手状态']


@pytest.mark.parametrize('change', ['selected_window', 'closed_window', 'controller'])
def test_dialogue_discards_result_when_input_target_changes(dialogue_task, change):
    task, ctx, _, action = dialogue_task
    original = ctx.controller

    def detect(*args, **kwargs):
        if change == 'selected_window':
            original.game_win.get_hwnd.return_value = 202
        elif change == 'closed_window':
            original.game_win.is_win_valid = False
        else:
            ctx.controller = copy.copy(original)
        return action

    task._detector.detect.side_effect = detect
    task._menu_until = float('inf')
    task.run()
    original.click_dialogue_event.assert_not_called()
    assert task._menu_until == 0


def test_dialogue_in_background_mode_uses_only_window_messages(dialogue_task, monkeypatch):
    import src.controls.interaction as interaction
    task, ctx, _, action = dialogue_task
    monkeypatch.setattr(interaction, 'background_mode_selected', lambda: True)
    ctx.controller.game_win.is_win_active = False
    task._detector.detect.return_value = action
    task.run()
    ctx.controller.click_dialogue_event.assert_called_once_with(
        action.point, expected_hwnd=101, allow_background=True)


def test_dialogue_result_age_includes_frame_capture(dialogue_task, monkeypatch):
    import time
    task, ctx, frames, action = dialogue_task
    clock = [1000.0]
    monkeypatch.setattr(time, 'monotonic', lambda: clock[0])
    def capture(self):
        clock[0] += 0.6
        return frames[0]
    monkeypatch.setattr(BaseTask, 'frame', property(capture))
    task._detector.detect.return_value = action
    task.run()
    ctx.controller.click_dialogue_event.assert_not_called()


@pytest.mark.parametrize('reason', ['capture', 'background', 'other_task'])
def test_dialogue_trigger_never_clicks_without_usable_foreground_frame(dialogue_task, task_factory, reason):
    task, ctx, frames, action = dialogue_task
    task._detector.detect.return_value = action
    if reason == 'capture':
        frames[0] = None
    elif reason == 'background':
        ctx.controller.game_win.is_win_active = False
    else:
        other = task_factory(OneDragonDailyTask)
        other.running = True
    task.run()
    ctx.controller.click_dialogue_event.assert_not_called()
    task._detector.detect.assert_not_called()


def test_dialogue_trigger_discards_result_after_settings_change_or_pause(dialogue_task):
    task, ctx, _, action = dialogue_task
    def settings_change(*args, **kwargs):
        task.config['对话选项'] = '第一个'
        return action
    task._detector.detect.side_effect = settings_change
    task.run()
    ctx.controller.click_dialogue_event.assert_not_called()
    task._last_check = None
    def pause(*args, **kwargs):
        task._on_executor_paused(True)
        return action
    task._detector.detect.side_effect = pause
    task.run()
    ctx.controller.click_dialogue_event.assert_not_called()


@pytest.mark.parametrize('key, value', [('识别间隔秒', 0), ('识别间隔秒', 'bad'),
                                     ('对话点击间隔秒', float('nan')), ('对话点击间隔秒', 4)])
def test_dialogue_trigger_rejects_invalid_intervals(dialogue_task, key, value):
    task, _, _, _ = dialogue_task
    assert task.validate_config(key, value)


def test_daily_selection_names_and_single_save(task_factory, tmp_path, monkeypatch):
    from onedragon.base.operation.application.application_group_config import ApplicationGroupConfig
    from onedragon.utils import os_utils
    monkeypatch.setattr(os_utils, 'get_path_under_work_dir', lambda *parts: str(tmp_path))
    group = ApplicationGroupConfig(0, 'one_dragon')
    group.update_full_app_list(['email', 'coffee', 'charge_plan'])
    real_save = group.save
    group.save = Mock(wraps=real_save)
    ctx = SimpleNamespace(current_instance_idx=0, run_context=SimpleNamespace(
        get_group_config=lambda **_: group,
        get_group_app_ids=lambda **_: [(item.app_id, item.enabled) for item in group.app_list]))
    task = task_factory(OneDragonDailyTask, ctx)
    task.config['启用应用'] = ['邮件', '体力刷本']
    task._sync_group_config()
    assert {item.app_id for item in group.app_list if item.enabled} == {'email', 'charge_plan'}
    assert group.save.call_count == 1
    reloaded = ApplicationGroupConfig(0, 'one_dragon')
    assert {item.app_id for item in reloaded._all_apps if item.enabled} == {'email', 'charge_plan'}


def test_trigger_enable_defers_loading_and_is_exclusive(task_factory):
    ctx = battle_context()
    combat = task_factory(AutoCombatTask, ctx)
    dodge = task_factory(DodgeAssistantTriggerTask)
    combat.enable()
    ctx.init_for_application.assert_not_called()
    dodge.enable()
    assert dodge.enabled and not combat.enabled
    assert combat.config['_enabled'] is False
    combat.executor.interaction.on_run.assert_not_called()


def test_focus_loss_blocks_queued_input_and_releases_held_keys(initialized_assistant):
    import time
    task, ctx, _, presence = initialized_assistant()
    presence.return_value = '敌人血条'
    task._last_frame_check = None
    task.run()
    assert task._input_allowed()
    old_guard = task._make_input_guard()
    ctx.controller.game_win.is_win_active = False
    assert not old_guard()
    assert not task._on_dodge_event('闪避识别-红光', time.time())
    task.run()
    assert not task._actions_running
    ctx.controller.btn_controller.reset.assert_called_once()
    assert '前台' in task.info['助手状态']
    ctx.controller.game_win.is_win_active = True
    task._last_frame_check = None
    task.run()
    assert task._input_allowed() and not old_guard()


def test_background_gamepad_keeps_detection_without_foreground(initialized_assistant):
    task, ctx, _, presence = initialized_assistant()
    ctx.controller.background_mode = True
    ctx.controller.game_win.is_win_active = False
    presence.return_value = '敌人血条'
    task._last_frame_check = None
    task.run()
    assert task._actions_running and task._input_allowed()
    ctx.controller.game_win.get_hwnd = lambda: 202
    assert not task._input_allowed()  # A queued old frame cannot control a new window.


def test_dialogue_enable_never_activates_game(dialogue_task):
    task, _, _, _ = dialogue_task
    task.executor.interaction.on_run.assert_not_called()


def test_combat_options_restart_and_stop_on_end(task_factory, monkeypatch):
    from zzz_od.auto_battle import battle_presence
    monkeypatch.setattr(battle_presence, 'detect_battle_presence', Mock(return_value='敌人血条'))
    from zzz_od.application.battle_assistant import battle_assistant_input_mode as input_mode
    monkeypatch.setattr(input_mode, 'apply_battle_assistant_input_mode',
                        Mock(return_value=(True, 'ok')))
    monkeypatch.setattr(BaseTask, 'frame', property(lambda self: np.zeros((4, 4, 3), np.uint8)))
    ctx = battle_context()
    task = task_factory(AutoCombatTask, ctx)
    task.enable()
    task.config['自动终结技'] = False
    task.run()
    assert ctx.auto_battle_context.auto_ultimate_enabled is False
    task.config['战斗配置'] = '专属配队-艾莲'
    task.run()
    assert ctx.auto_battle_context.start_actions.call_count == 2
    ctx.auto_battle_context.stop_auto_battle.assert_called_once()
    task.config['战斗结束停止'] = True
    task._last_frame_check = None
    ctx.auto_battle_context.last_check_end_result = '普通战斗-完成'
    battle_presence.detect_battle_presence.return_value = None
    task.run()
    assert not task.enabled
    assert ctx.auto_battle_context.check_battle_state.call_args.kwargs['check_battle_end_normal_result']
    task.run()
    assert ctx.auto_battle_context.start_actions.call_count == 2


def test_trigger_does_not_stop_another_apps_operator(task_factory):
    ctx = battle_context()
    task = task_factory(AutoCombatTask, ctx)
    old_op = SimpleNamespace(stop_running=Mock())
    task._engine_op = old_op
    ctx.auto_battle_context.auto_op = object()
    task._stop_engine()
    ctx.auto_battle_context.stop_auto_battle.assert_not_called()
    old_op.stop_running.assert_called_once()
    assert old_op.execution_allowed is None


def test_cancel_during_engine_loading_never_starts_input(task_factory, monkeypatch):
    from zzz_od.application.battle_assistant import battle_assistant_input_mode as input_mode
    monkeypatch.setattr(input_mode, 'apply_battle_assistant_input_mode',
                        Mock(return_value=(True, 'ok')))
    ctx = battle_context()
    task = task_factory(AutoCombatTask, ctx)
    task.enable()
    ctx.auto_battle_context.init_auto_op.side_effect = lambda *args, **kwargs: task.disable()
    assert not task._start_engine('全配队通用')
    ctx.auto_battle_context.start_auto_battle.assert_not_called()


def test_global_pause_stops_battle_and_leaves_enabled(task_factory):
    ctx = battle_context()
    task = task_factory(AutoCombatTask, ctx)
    task._engine_op = ctx.auto_battle_context.auto_op = SimpleNamespace()
    task.enable()
    task._on_executor_paused(True)
    ctx.auto_battle_context.stop_auto_battle.assert_called_once()
    assert task.enabled and not task._engine_started


@pytest.mark.parametrize('interval', [0, -0.1, 2, float('nan'), float('inf'), 'bad'])
def test_invalid_interval_returns_ui_error(task_factory, interval):
    task = task_factory(DodgeAssistantTriggerTask)
    valid, message = task.validate('截图间隔秒', interval)
    assert not valid and message


def test_dodge_interval_throttles(task_factory, monkeypatch):
    import ok.task.task as framework
    task = task_factory(DodgeAssistantTriggerTask)
    task._enabled = True
    task.config['截图间隔秒'] = 0.2
    monkeypatch.setattr(framework.time, 'time', lambda: 10)
    assert task.should_trigger()
    assert not task.should_trigger()
    assert task.trigger_interval == 0.2


def test_app_json_invalid_input_leaves_config_intact(task_factory):
    from src.tasks.app_tasks import App_SuibianTemple
    from onedragon.base.config.yaml_operator import YamlOperator
    cfg = YamlOperator()
    cfg.data = {'old': True}
    cfg.save = Mock()
    ctx = SimpleNamespace(current_instance_idx=0,
                          run_context=SimpleNamespace(get_config=lambda *args, **kwargs: cfg))
    task = task_factory(App_SuibianTemple, ctx)
    task.config['pawnshop_crest_priority'] = 'invalid'
    with pytest.raises(ValueError, match='JSON'):
        task.apply_options()
    assert cfg.data == {'old': True}
    cfg.save.assert_not_called()
    # 编辑器允许临时不完整的草稿，运行前再拒绝错误，避免每次按键弹窗。
    assert task.validate('pawnshop_crest_priority', 'invalid')[0] is True
    with pytest.raises(ValueError, match='数组'):
        task._parse_option('pawnshop_crest_priority', '{}')


def test_app_options_commit_once(task_factory):
    from src.tasks.app_tasks import App_CommissionAssistant
    from onedragon.base.config.yaml_operator import YamlOperator
    cfg = YamlOperator()
    cfg.save = Mock()
    ctx = SimpleNamespace(current_instance_idx=0,
                          run_context=SimpleNamespace(get_config=lambda *args, **kwargs: cfg))
    task = task_factory(App_CommissionAssistant, ctx)
    task.apply_options()
    cfg.save.assert_called_once()
    assert cfg.get('dialog_click_interval') == task.config['dialog_click_interval']


def test_generated_json_defaults_are_valid(task_factory):
    import src.tasks.app_tasks as app_tasks
    from zzz_od.application.app_options_data import APP_OPTIONS
    for metadata in APP_OPTIONS:
        if not any(option['type'] == 'json' for option in metadata.get('options', [])):
            continue
        cls = next(cls for cls in vars(app_tasks).values()
                   if isinstance(cls, type) and getattr(cls, 'app_id', None) == metadata['app_id'])
        task = task_factory(cls)
        for option in metadata['options']:
            parsed = task._parse_option(option['key'], task.config[option['key']])
            if option['type'] == 'json':
                assert isinstance(parsed, (dict, list))


def test_audio_template_initialization_does_not_queue_duplicates(monkeypatch):
    from concurrent.futures import Future
    from zzz_od.auto_battle import auto_battle_dodge_context as module
    context = module.AutoBattleDodgeContext.__new__(module.AutoBattleDodgeContext)
    context._audio_template = None
    context._audio_template_lock = threading.Lock()
    context._audio_template_future = None
    submit = Mock(return_value=Future())
    monkeypatch.setattr(module._dodge_check_executor, 'submit', submit)
    context.init_battle_dodge_context()
    context.init_battle_dodge_context()
    assert submit.call_count == 1


def test_option_labels_and_dynamic_dropdown(task_factory):
    from src.tasks.app_tasks import App_IntelBoard
    from src.tasks.app_option_ui import OPTION_LABELS
    from zzz_od.application.app_options_data import APP_OPTIONS
    keys = {o['key'] for app in APP_OPTIONS for o in app.get('options', [])}
    assert keys <= OPTION_LABELS.keys()
    translations = gettext.translation('ok', 'i18n', languages=['zh_CN'])
    assert all(translations.gettext(key) == OPTION_LABELS[key] for key in keys)
    task = task_factory(App_IntelBoard)
    task.post_init()
    assert '专属配队-艾莲' in task.config_type['auto_battle_config']['options']
    assert task.config_type['结束后']['sub_configs'] == {'关机': ['关机延迟秒']}


@pytest.mark.parametrize('shape', [(720, 1280), (1080, 1920), (1440, 2560)])
def test_injected_frame_uses_standard_coordinates(shape):
    from zzz_od.controller.zzz_controller import ZzzController
    controller = ZzzController.__new__(ZzzController)
    controller.standard_width, controller.standard_height = 1920, 1080
    frame = np.zeros((*shape, 3), np.uint8)
    frame[:] = (10, 40, 230)  # BGR red from ok-script.
    controller.frame_provider = lambda: (123, frame)
    timestamp, normalized = controller.screenshot()
    assert timestamp == 123 and normalized.shape == (1080, 1920, 3)
    assert tuple(normalized[200, 200]) == (230, 40, 10)
    assert tuple(frame[0, 0]) == (10, 40, 230)  # Source remains BGR.


def test_empty_selected_frame_stops_input_and_independent_skips_provider(monkeypatch):
    from zzz_od.controller.zzz_controller import ZzzController, ZPcController
    controller = ZzzController.__new__(ZzzController)
    controller.standard_width, controller.standard_height = 1920, 1080
    controller.frame_provider = Mock(return_value=(0, None))
    controller.cancel_inputs = Mock()
    fallback = Mock(return_value=(1, 'fallback'))
    monkeypatch.setattr(ZPcController, 'screenshot', fallback)
    with pytest.raises(RuntimeError, match='截图不可用'):
        controller.screenshot()
    controller.cancel_inputs.assert_called_once()
    fallback.assert_not_called()
    controller.screenshot(independent=True)
    assert controller.frame_provider.call_count == 1
    assert fallback.call_args.kwargs['independent']


def test_selected_capture_error_never_falls_back_to_desktop(monkeypatch):
    from zzz_od.controller.zzz_controller import ZzzController, ZPcController
    controller = ZzzController.__new__(ZzzController)
    controller.frame_provider = Mock(side_effect=RuntimeError('连续12秒无法取得游戏画面'))
    fallback = Mock()
    monkeypatch.setattr(ZPcController, 'screenshot', fallback)
    with pytest.raises(RuntimeError, match='连续12秒'):
        controller.screenshot()
    fallback.assert_not_called()


@pytest.mark.parametrize('key', ['w', 'mouse_left'])
def test_reset_interrupts_timed_hold(monkeypatch, key):
    from onedragon.base.controller.pc_button import keyboard_mouse_controller as module
    keyboard, mouse = Mock(), Mock()
    monkeypatch.setattr(module.keyboard, 'Controller', lambda: keyboard)
    monkeypatch.setattr(module.mouse, 'Controller', lambda: mouse)
    controller = module.KeyboardMouseController()
    pressed = threading.Event()
    device = mouse if key.startswith('mouse_') else keyboard
    device.press.side_effect = lambda real_key: pressed.set()
    thread = threading.Thread(target=controller.press, args=(key, 5))
    thread.start()
    try:
        assert pressed.wait(1)
        controller.reset()
        thread.join(1)
        assert not thread.is_alive()
        device.release.assert_called_once()
        assert not controller._pressed_keys
    finally:
        controller.reset()
        thread.join(6)


def test_device_switch_releases_previous_controller():
    from onedragon.base.controller.pc_controller_base import PcControllerBase
    controller = PcControllerBase.__new__(PcControllerBase)
    old = controller.btn_controller = Mock()
    controller.keyboard_controller = Mock()
    controller.enable_keyboard()
    old.reset.assert_called_once()
    controller.enable_keyboard()
    assert old.reset.call_count == 1


def test_onetime_pause_resume_stop_bridges_to_game(task_factory):
    from onedragon.base.operation.application.application_run_context import ApplicationRunContext
    ctx = SimpleNamespace(controller=None)
    ctx.run_context = ApplicationRunContext(ctx)
    task = task_factory(OneDragonDailyTask, ctx)
    task.running = True
    ctx.run_context.start_running()
    task.pause()
    assert ctx.run_context.is_context_pause
    task.unpause()
    assert ctx.run_context.is_context_running
    task.disable()
    assert ctx.run_context.is_context_stop


@pytest.mark.parametrize('raise_after_stop', [False, True])
def test_user_stop_result_is_preserved(monkeypatch, raise_after_stop):
    from onedragon.base.operation.application.application_run_context import (
        ApplicationRunContext, RunFinishReason,
    )
    ctx = SimpleNamespace(controller=None, current_instance_idx=0)
    run = ApplicationRunContext(ctx)
    def execute():
        run.stop_running()
        if raise_after_stop:
            raise RuntimeError('operation interrupted')
        return SimpleNamespace(success=True)
    app = SimpleNamespace(op_name='test', execute=execute)
    monkeypatch.setattr(run, 'get_application', lambda *args: app)
    assert run.run_application('test').finish_reason == RunFinishReason.STOPPED


def test_dialogue_interval_is_left_to_the_framework_trigger(dialogue_task, monkeypatch):
    """识别间隔由框架 should_trigger 统一节流；run() 不再用第二个时钟吞掉整拍。"""
    import time as time_module
    task, _, _, action = dialogue_task
    task._detector.detect.return_value = action
    clock = [1000.0]
    monkeypatch.setattr(time_module, 'monotonic', lambda: clock[0])
    task.run()
    assert task._detector.detect.call_count == 1
    task._last_click = None  # 只关掉点击去抖；时钟未前进
    task.run()
    assert task._detector.detect.call_count == 2


def test_missing_config_name_falls_back_to_the_task_default(task_factory, monkeypatch):
    """闪避配置缺失时回退到本任务的默认值（曾经错误地回退成「全配队通用」）。"""
    from src.tasks.auto_combat_task import DodgeAssistantTriggerTask
    task = task_factory(DodgeAssistantTriggerTask)
    task.config.pop('闪避配置', None)
    started = []
    monkeypatch.setattr(task, '_start_engine', lambda name: started.append(name) or True)
    monkeypatch.setattr(task, '_window_input_allowed', lambda: False)
    task._enabled = True
    task.run()
    assert started == ['闪避']
