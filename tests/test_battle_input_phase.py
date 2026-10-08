import time
from unittest.mock import Mock

import pytest
from test_runtime_interactions import initialized_assistant, task_factory
from src.tasks.auto_combat_task import DodgeAssistantTriggerTask


def test_no_attack_hud_skips_enemy_scan_and_combat_recognition(initialized_assistant):
    task, ctx, _, presence = initialized_assistant()
    battle = ctx.auto_battle_context
    presence.reset_mock()
    battle.is_normal_attack_btn_available.return_value = False
    task._last_frame_check = None
    task.run()
    presence.assert_not_called()
    args = battle.check_battle_state.call_args.kwargs
    assert not args['attack_hud_visible'] and not args['chain_ui_visible']
    assert args['passive'] and not task._input_allowed()
    assert not task._on_dodge_event('闪避识别-黄光', time.time())


def test_animation_pauses_input_then_resumes_original_deadline(initialized_assistant):
    task, ctx, _, presence = initialized_assistant()
    task._watchdog_stop.set()
    presence.return_value = '敌人血条'
    task._last_frame_check = None
    task.run()
    deadline, old_guard = task._input_until, task._make_input_guard()
    checked, cleared = presence.call_count, ctx.auto_battle_context.clear_all_states.call_count
    ctx.auto_battle_context.is_normal_attack_btn_available.return_value = False
    task._last_frame_check = None
    task.run()
    assert task._actions_running and task._ui_paused and not old_guard()
    assert not task._input_allowed() and task._input_until == deadline
    ctx.controller.btn_controller.reset.assert_called_once()
    assert presence.call_count == checked
    ctx.auto_battle_context.is_normal_attack_btn_available.return_value = True
    task._last_frame_check = None
    task.run()
    assert task._input_allowed() and not task._ui_paused and not old_guard()
    assert task._input_until == deadline and presence.call_count == checked
    assert ctx.auto_battle_context.clear_all_states.call_count == cleared


def test_chain_screen_only_permits_chain_actions(initialized_assistant, monkeypatch):
    from zzz_od.auto_battle import battle_presence
    task, ctx, _, presence = initialized_assistant()
    ctx.auto_battle_context.is_normal_attack_btn_available.return_value = False
    monkeypatch.setattr(battle_presence, 'has_chain_timer', lambda frame: True)
    monkeypatch.setattr(battle_presence, 'detect_chain_presence', lambda *a, **kw: '连携技')
    checked = presence.call_count
    task._last_frame_check = None
    task.run()
    assert task._input_phase == 'chain' and task._input_allowed()
    assert all(task._action_allowed(a) for a in ('chain_left', 'chain_right', 'chain_cancel'))
    assert all(not task._action_allowed(a) for a in ('normal_attack','ultimate','dodge','turn','switch_next'))
    assert presence.call_count == checked


def test_immediate_burst_continuation_retains_role_states(initialized_assistant):
    task, ctx, _, presence = initialized_assistant()
    task._watchdog_stop.set()
    presence.return_value = '敌人血条'
    task._last_frame_check = None
    task.run()
    cleared = ctx.auto_battle_context.clear_all_states.call_count
    task._input_until = time.monotonic()-.001
    task._last_frame_check = None
    task.run()
    assert task._actions_running
    assert ctx.auto_battle_context.clear_all_states.call_count == cleared


def test_dodge_rejects_late_flash_after_attack_button_disappears(initialized_assistant):
    task, ctx, _, _ = initialized_assistant(DodgeAssistantTriggerTask)
    ctx.auto_battle_context.is_normal_attack_btn_available.return_value = False
    task._last_frame_check = None
    task.run()
    assert not task._on_dodge_event('闪避识别-红光', time.time())
    assert not task._input_allowed()


def test_arrow_requires_continuous_evidence_not_one_particle_frame(initialized_assistant, monkeypatch):
    task, _, _, presence = initialized_assistant()
    task._watchdog_stop.set()
    clock=[time.monotonic()]
    monkeypatch.setattr(time,'monotonic',lambda:clock[0])
    presence.return_value='敌人方向箭头'
    # Stay below 120ms; cumulative .04+.08 lands exactly on a floating boundary.
    for delta in (0,.04,.04):
        clock[0]+=delta
        task._last_frame_check=None
        task.run()
        assert not task._actions_running
    clock[0]+=.05
    task._last_frame_check=None
    task.run()
    assert task._actions_running


def test_enemy_scan_does_not_block_fresh_warning_callback(initialized_assistant):
    import threading
    task, ctx, _, presence=initialized_assistant()
    task._watchdog_stop.set()
    entered,done=threading.Event(),threading.Event()
    accepted=[]
    def warn():
        entered.wait(1)
        accepted.append(task._on_dodge_event('闪避识别-红光',time.time()))
        done.set()
    worker=threading.Thread(target=warn)
    worker.start()
    def detect(*args):
        entered.set()
        assert done.wait(.3), 'enemy scan held the lifecycle lock'
        return None
    presence.side_effect=detect
    task._last_frame_check=None
    task.run()
    worker.join(1)
    assert accepted==[True] and task._actions_running


def test_no_hud_skips_all_combat_models_and_clears_ready_skills(ctx, monkeypatch):
    import numpy as np
    from onedragon.base.conditional_operation.state_recorder import StateRecord
    from zzz_od.auto_battle.auto_battle_context import AutoBattleContext
    battle=AutoBattleContext(ctx)
    methods=[(battle.dodge_context,'check_dodge_audio'),(battle.dodge_context,'check_dodge_flash'),
             (battle.agent_context,'check_agent_related'),(battle.target_context,'run_all_checks'),
             (battle,'check_quick_assist'),(battle,'check_switch_backup'),(battle,'check_chain_attack')]
    checks=[]
    for obj,name in methods:
        mock=Mock();monkeypatch.setattr(obj,name,mock);checks.append(mock)
    battle.state_record_service.batch_update_states([StateRecord('按键可用-'+s,time.time())
                                                    for s in ('普通攻击','特殊攻击','终结技')])
    battle.check_battle_state(np.zeros((1080,1920,3),np.uint8),time.time(),sync=True,
                             attack_hud_visible=False,chain_ui_visible=False)
    for check in checks:check.assert_not_called()
    for state in ('普通攻击','特殊攻击','终结技'):
        assert battle.state_record_service.get_state_recorder('按键可用-'+state).last_record_time==0
