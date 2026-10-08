"""Warning routing reaches configured input; all devices are recording doubles."""
import threading
import time

import pytest
from onedragon.base.conditional_operation.operation_def import OperationDef
from onedragon.base.conditional_operation.state_recorder import StateRecord
from zzz_od.auto_battle.atomic_op.realtime_response import WARNING_CODES
from zzz_od.auto_battle.auto_battle_agent_context import TeamInfo
from test_skill_release import skills
from test_runtime_interactions import initialized_assistant, task_factory


def response(battle, warning, *, explicit=False, hud=True, age=0):
    now = time.time()
    records = [StateRecord(warning, now-age),
               StateRecord('自定义-实时闪避事件', now-age, value=WARNING_CODES[warning])]
    if hud:
        records.append(StateRecord('按键可用-普通攻击', now))
    battle.state_record_service.batch_update_states(records)
    definition = {'op_name': '实时战斗响应'}
    if explicit:
        definition['data'] = [warning]
    return battle.atomic_op_factory.get_atomic_op(OperationDef(definition))


@pytest.mark.parametrize('backend', ['keyboard', 'xbox', 'ds4'])
@pytest.mark.parametrize('warning,action', [
    ('闪避识别-黄光', 'switch_next'), ('闪避识别-红光', 'dodge'), ('闪避识别-声音', 'dodge')])
def test_warning_routes_to_assist_or_dodge_and_counter(skills, monkeypatch, backend, warning, action):
    # 这里只验证预警路由；系统调度延迟不能让测试事件超过 250 ms 有效期。
    # 过期预警由下面的 stale 场景单独验证。
    captured_at = time.time()
    monkeypatch.setattr(time, 'time', lambda: captured_at)
    battle, ctx, recorder = skills
    keys = ctx.game_config.get_action_keys(backend)
    monkeypatch.setattr(ctx.controller, 'action_keys', keys)
    # A new/unrecognized portrait still occupies the next physical slot.
    battle.agent_context.team_info = TeamInfo(['克拉蕾', None, '丽娜'])
    before = list(battle.agent_context.team_info.agent_list)
    response(battle, warning).execute()
    assert [ev for ev in recorder.events if ev[0] == 'tap'] == [
        ('tap', keys[action]), ('tap', keys['normal_attack'])]
    after = battle.agent_context.team_info.agent_list
    assert after == (before[1:]+before[:1] if action == 'switch_next' else before)


@pytest.mark.parametrize('blocked_by', ['solo', '切人-冷却', '格挡-破碎'])
def test_yellow_falls_back_to_dodge_when_assist_unavailable(skills, blocked_by):
    battle, ctx, recorder = skills
    op = response(battle, '闪避识别-黄光')
    if blocked_by == 'solo':
        battle.agent_context.team_info = TeamInfo(['安比'])
    else:
        battle.state_record_service.update_state(StateRecord(blocked_by, time.time(), value=1))
    op.execute()
    keys = ctx.game_config.get_action_keys('keyboard')
    assert [ev for ev in recorder.events if ev[0] == 'tap'] == [
        ('tap', keys['dodge']), ('tap', keys['normal_attack'])]


@pytest.mark.parametrize('explicit', [False, True])
@pytest.mark.parametrize('invalid', ['stale', 'no_hud', 'guard'])
def test_invalid_cue_or_phase_never_inputs_or_predicts_switch(skills, monkeypatch, explicit, invalid):
    battle, ctx, recorder = skills
    before = list(battle.agent_context.team_info.agent_list)
    op = response(battle, '闪避识别-黄光', explicit=explicit,
                  hud=invalid != 'no_hud', age=1 if invalid == 'stale' else 0)
    if invalid == 'guard':
        monkeypatch.setattr(ctx.controller, 'battle_input_guard', lambda: False)
    op.execute()
    assert not recorder.events
    assert battle.agent_context.team_info.agent_list == before


def test_latest_red_code_does_not_reuse_recent_yellow(skills):
    battle, ctx, recorder = skills
    response(battle, '闪避识别-黄光')
    response(battle, '闪避识别-红光').execute()
    keys = ctx.game_config.get_action_keys('keyboard')
    assert ('tap', keys['dodge']) in recorder.events
    assert ('tap', keys['switch_next']) not in recorder.events


def test_template_fallback_routes_by_newest_cue_not_first_matching_handler(skills):
    battle, ctx, recorder = skills
    yellow_handler = response(battle, '闪避识别-黄光', explicit=True)
    response(battle, '闪避识别-红光')
    yellow_handler.execute()
    keys = ctx.game_config.get_action_keys('keyboard')
    assert ('tap', keys['dodge']) in recorder.events
    assert ('tap', keys['switch_next']) not in recorder.events


@pytest.mark.parametrize('invalid_kind', ['unknown_explicit', 'unknown_code'])
def test_invalid_warning_kind_does_not_issue_input(skills, invalid_kind):
    battle, _, recorder = skills
    op = response(battle, '闪避识别-黄光')
    if invalid_kind == 'unknown_explicit':
        op.warning = '未知提示'
    else:
        battle.state_record_service.update_state(StateRecord(
            '自定义-实时闪避事件', time.time(), value=0))
    op.execute()
    assert not recorder.events


@pytest.mark.parametrize('interrupt', ['stop', 'phase_change'])
def test_response_counter_is_cancelled_by_stop_or_phase_change(skills, monkeypatch, interrupt):
    battle, ctx, recorder = skills
    op = response(battle, '闪避识别-黄光')
    sent = threading.Event()
    original = battle.switch_next
    def switch():
        result = original()
        sent.set()
        return result
    monkeypatch.setattr(battle, 'switch_next', switch)
    worker = threading.Thread(target=op.execute)
    worker.start()
    try:
        assert sent.wait(.5)
        if interrupt == 'stop':
            op.stop()
        else:
            monkeypatch.setattr(ctx.controller, 'battle_action_guard', lambda action: False)
        worker.join(.5)
        assert not worker.is_alive()
        assert ('tap', ctx.game_config.get_action_keys('keyboard')['normal_attack']) not in recorder.events
    finally:
        op.stop()
        worker.join(.5)


@pytest.mark.parametrize('realtime', [False, True])
def test_actual_template_yellow_dispatches_assist_for_unknown_front(skills, realtime):
    battle, ctx, recorder = skills
    battle.init_auto_op('全配队通用')
    battle.agent_context.team_info = TeamInfo([None, '丽娜', '克拉蕾'])
    battle.auto_op.auto_lock_interval = battle.auto_op.auto_turn_interval = -1
    battle.auto_op.start_running_async()
    now = time.time()
    records = [StateRecord('按键可用-普通攻击', now), StateRecord('前台-未识别', now),
               StateRecord('闪避识别-黄光', now)]
    if realtime:
        records.extend([StateRecord('自定义-动作不打断', now+5),
                        StateRecord('自定义-实时闪避事件', now, value=2)])
    battle.state_record_service.batch_update_states(records)
    key = ctx.game_config.get_action_keys('keyboard')['switch_next']
    deadline = time.monotonic()+.5
    while ('tap', key) not in recorder.events and time.monotonic() < deadline:
        time.sleep(.005)
    battle.auto_op.stop_running()
    assert ('tap', key) in recorder.events
    assert ('tap', ctx.game_config.get_action_keys('keyboard')['dodge']) not in recorder.events


@pytest.mark.parametrize('warning,code', list(WARNING_CODES.items()))
def test_task_publishes_exact_warning_kind(initialized_assistant, warning, code):
    task, ctx, _, _ = initialized_assistant()
    assert task._on_dodge_event(warning, time.time())
    records = ctx.auto_battle_context.state_record_service.batch_update_states.call_args.args[0]
    encoded = next(r for r in records if r.state_name == '自定义-实时闪避事件')
    assert encoded.value == code
    assert warning in [r.state_name for r in records]


def test_audio_after_visual_is_suppressed_even_after_empty_frame(initialized_assistant, monkeypatch):
    from src.tasks.auto_combat_task import DodgeAssistantTriggerTask
    task, ctx, _, _ = initialized_assistant(DodgeAssistantTriggerTask)
    clock = [time.time()]
    monkeypatch.setattr(time, 'time', lambda: clock[0])
    assert task._on_dodge_event('闪避识别-黄光', clock[0])
    clock[0] += .1
    assert not task._on_dodge_event(None, clock[0])
    clock[0] += .2
    assert not task._on_dodge_event('闪避识别-声音', clock[0])
    ctx.auto_battle_context.state_record_service.update_state.assert_called_once()
    clock[0] += .1
    assert task._on_dodge_event('闪避识别-声音', clock[0])


@pytest.mark.parametrize('warning', ['闪避识别-红光','闪避识别-黄光'])
def test_recorded_single_frame_flicker_does_not_repeat_defensive_response(initialized_assistant,monkeypatch,warning):
    from src.tasks.auto_combat_task import DodgeAssistantTriggerTask
    task,ctx,_,_=initialized_assistant(DodgeAssistantTriggerTask)
    task._watchdog_stop.set()
    clock=[time.time()]
    base=clock[0]
    monkeypatch.setattr(time,'time',lambda:clock[0])
    # The 14:17 recording has one 32-47 ms empty frame inside a flash.
    sequence=[(0,warning),(.047,warning),(.078,warning),(.109,warning),
              (.156,warning),(.187,warning),(.218,None),(.25,warning),(.297,None)]
    accepted=[]
    for t,event in sequence:
        clock[0]=base+t
        accepted.append(task._on_dodge_event(event,clock[0]))
    assert sum(accepted)==1
    ctx.auto_battle_context.state_record_service.update_state.assert_called_once()
    clock[0]=base+.45
    assert task._on_dodge_event(warning,clock[0])  # A genuinely separated attack re-arms.


def test_dungeon_yellow_interrupts_character_template_without_preliminary_dodge(skills):
    battle, ctx, recorder = skills
    battle.init_auto_op('全配队通用')
    battle.auto_op.auto_lock_interval = battle.auto_op.auto_turn_interval = -1
    battle.auto_op.start_running_async()
    now = time.time()
    battle.state_record_service.batch_update_states([
        StateRecord('按键可用-普通攻击', now),
        StateRecord('前台-安比', now),
        StateRecord('自定义-动作不打断', now+5),
    ])
    assert battle.dodge_context._publish_warning('闪避识别-黄光', now)
    keys = ctx.game_config.get_action_keys('keyboard')
    deadline = time.monotonic()+.5
    while ('tap', keys['switch_next']) not in recorder.events and time.monotonic() < deadline:
        time.sleep(.005)
    battle.auto_op.stop_running()
    assert ('tap', keys['switch_next']) in recorder.events
    assert ('tap', keys['dodge']) not in recorder.events


def test_dungeon_warning_deduplicates_continuous_flash_and_its_audio(skills, monkeypatch):
    from types import SimpleNamespace
    battle, _, _ = skills
    battle.auto_op = SimpleNamespace(is_running=True, _sub_dir=['auto_battle'],
                                    stop_running=lambda: None, dispose=lambda: None)
    clock = [time.time()]
    monkeypatch.setattr(time, 'time', lambda: clock[0])
    base = clock[0]
    for delta, event, accepted in [(0, '闪避识别-黄光', True),
        (.047, '闪避识别-黄光', False), (.1, None, False),
        (.14, '闪避识别-黄光', False), (.2, '闪避识别-声音', False),
        (.3, None, False), (.4, '闪避识别-黄光', True)]:
        clock[0] = base+delta
        battle.state_record_service.update_state(StateRecord('按键可用-普通攻击', clock[0]))
        assert battle.dodge_context._publish_warning(event, clock[0]) is accepted


@pytest.mark.parametrize('case', ['no_hud', 'stale', 'stopped', 'disabled', 'dodge_template'])
def test_dungeon_warning_respects_readiness_and_realtime_preference(skills, case):
    from types import SimpleNamespace
    battle, _, recorder = skills
    battle.auto_op = SimpleNamespace(is_running=case != 'stopped',
        _sub_dir=['dodge' if case == 'dodge_template' else 'auto_battle'],
        stop_running=lambda: None, dispose=lambda: None)
    battle.realtime_dodge_enabled_provider = lambda: case != 'disabled'
    now = time.time()
    if case != 'no_hud':
        battle.state_record_service.update_state(StateRecord('按键可用-普通攻击', now))
    accepted = battle.dodge_context._publish_warning('闪避识别-红光', now-(1 if case == 'stale' else 0))
    assert accepted is (case not in ('no_hud', 'stale'))
    assert battle.state_record_service.get_state_recorder('自定义-实时闪避事件').last_record_time == -1
    assert not recorder.events
