import threading
import time
from unittest.mock import Mock

import pytest
from onedragon.base.conditional_operation.operation_def import OperationDef
from onedragon.base.conditional_operation.state_recorder import StateRecord
from zzz_od.auto_battle.auto_battle_context import AutoBattleContext
from zzz_od.auto_battle.atomic_op.btn_common import AtomicBtnCommon


@pytest.fixture
def generic(stubbed_controller, monkeypatch):
    ctx, recorder = stubbed_controller
    battle = AutoBattleContext(ctx)
    monkeypatch.setitem(ctx.__dict__, '_auto_battle_context', battle)
    battle.init_screen_area()
    op = battle.atomic_op_factory.get_atomic_op(OperationDef({'op_name': '通用战斗'}))
    return battle, ctx, recorder, op


@pytest.mark.parametrize('ready,enabled,expected', [
    ('终结技', True, 'ultimate'), ('特殊攻击', True, 'special_attack'),
    ('终结技', False, 'normal_attack'), ('', True, 'normal_attack')])
def test_generic_uses_fresh_ready_buttons_and_respects_ultimate_toggle(generic, ready, enabled, expected):
    battle, ctx, recorder, op = generic
    battle.auto_ultimate_enabled = enabled
    records = [StateRecord('按键可用-普通攻击', time.time())]
    if ready:
        records.append(StateRecord('按键可用-'+ready, time.time()))
    battle.state_record_service.batch_update_states(records)
    op.execute()
    assert ('tap', ctx.game_config.get_action_keys('keyboard')[expected]) in recorder.events


def test_generic_cooldowns_allow_output_between_skills(generic):
    battle, ctx, recorder, op = generic
    for _ in range(3):
        battle.state_record_service.batch_update_states([StateRecord('按键可用-'+s, time.time())
            for s in ('普通攻击', '终结技', '特殊攻击')])
        op.execute()
    keys = ctx.game_config.get_action_keys('keyboard')
    assert [('tap', keys[a]) for a in ('ultimate', 'special_attack', 'normal_attack')] == recorder.events


def test_generic_does_nothing_without_attack_hud_or_when_guarded(generic, monkeypatch):
    battle, ctx, recorder, op = generic
    op.execute()
    assert not recorder.events
    battle.state_record_service.update_state(StateRecord('按键可用-普通攻击', time.time()))
    monkeypatch.setattr(ctx.controller, 'battle_action_guard', lambda action: False)
    op.execute()
    assert not recorder.events


def test_known_role_without_template_uses_normal_scene_fallback(generic):
    battle, _, _, _ = generic
    battle.init_auto_op('通用操作')
    now=time.time()
    battle.state_record_service.batch_update_states([
        StateRecord('前台-丽娜', now), StateRecord('按键可用-普通攻击', now)])
    execution = battle.auto_op.normal_scene.match_execution(now)
    assert execution is not None and execution.op_list[0].op_name == '通用战斗'
    battle.auto_op.dispose()


def test_realtime_dodge_interrupts_template_suppression(generic):
    battle, ctx, recorder, _ = generic
    battle.init_auto_op('全配队通用')
    battle.auto_op.auto_lock_interval=battle.auto_op.auto_turn_interval=-1
    battle.auto_op.start_running_async()
    try:
        now=time.time()
        battle.state_record_service.batch_update_states([
            StateRecord('按键可用-普通攻击', now), StateRecord('前台-克拉蕾', now),
            StateRecord('自定义-动作不打断', now+5),
            StateRecord('闪避识别-红光', now), StateRecord('自定义-实时闪避事件', now, value=1)])
        key=ctx.game_config.get_action_keys('keyboard')['dodge']
        limit=time.monotonic()+.5
        while ('tap',key) not in recorder.events and time.monotonic()<limit:
            time.sleep(.005)
        assert ('tap', key) in recorder.events
    finally:
        battle.auto_op.stop_running()


def test_actual_dodge_consumes_red_reaction_once(generic):
    battle, _, _, _=generic
    battle.state_record_service.update_state(StateRecord('自定义-红光闪避', time.time()))
    battle.dodge()
    assert battle.state_record_service.get_state_recorder('自定义-红光闪避').last_record_time == 0


def test_atomic_button_delay_is_interruptible_and_reusable():
    ctx=Mock()
    op=AtomicBtnCommon(ctx, OperationDef({'op_name':'按键-普通攻击', 'pre_delay': 2}))
    worker=threading.Thread(target=op.execute)
    worker.start()
    time.sleep(.03)
    op.stop()
    worker.join(.2)
    assert not worker.is_alive()
    ctx.normal_attack.assert_not_called()
    op.pre_delay=0
    op.execute()
    ctx.normal_attack.assert_called_once()


def test_completed_indefinite_press_is_released_when_executor_stops():
    from onedragon.base.conditional_operation.operation_executor import OperationExecutor
    op=Mock(async_op=True)
    executor=OperationExecutor([op],time.time())
    assert executor.run_async().result(timeout=1)
    assert not executor.running
    assert executor.stop()
    op.stop.assert_called_once()


def test_chain_gate_reaches_controller_but_blocks_other_controls(generic,monkeypatch):
    battle,ctx,recorder,_=generic
    monkeypatch.setattr(ctx.controller,'battle_action_guard',lambda action:action=='chain_left')
    battle.normal_attack()
    battle.ultimate()
    ctx.controller.move_mouse_relative(100,0)
    assert not recorder.events
    battle.chain_left()
    assert ('tap',ctx.game_config.get_action_keys('keyboard')['chain_left']) in recorder.events
