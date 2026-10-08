"""Skill recognition, real DSL dispatch and recorded keyboard/gamepad inputs."""
import time
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest

from onedragon.base.conditional_operation.operation_def import OperationDef
from onedragon.base.conditional_operation.state_recorder import StateRecord
from onedragon.base.controller.input_guard import execution_input_guard
from zzz_od.auto_battle.auto_battle_context import AutoBattleContext
from zzz_od.auto_battle.auto_battle_agent_context import TeamInfo, AgentInfo
from zzz_od.game_data.agent import AgentEnum


@pytest.fixture
def skills(ctx, stubbed_controller, monkeypatch):
    context, recorder = stubbed_controller
    battle = AutoBattleContext(context)
    monkeypatch.setitem(context.__dict__, '_auto_battle_context', battle)
    monkeypatch.setattr(context.controller, 'battle_input_guard', None)
    monkeypatch.setattr(context.controller, 'background_mode', False)
    battle.init_screen_area()
    battle.agent_context.team_info = TeamInfo(['安比', '妮可', '比利'])
    yield battle, context, recorder
    if battle.auto_op is not None:
        battle.auto_op.stop_running()
        battle.auto_op.dispose()
    recorder.reset()


@pytest.mark.parametrize('backend', ['keyboard', 'xbox', 'ds4'])
@pytest.mark.parametrize('action', ['chain_left', 'chain_right', 'chain_cancel', 'special_attack', 'ultimate'])
def test_dsl_skill_buttons_use_configured_device_keys(skills, monkeypatch, backend, action):
    battle, context, recorder = skills
    monkeypatch.setattr(context.controller, 'action_keys', context.game_config.get_action_keys(backend))
    op_names = {'chain_left': '连携技-左', 'chain_right': '连携技-右',
                'chain_cancel': '连携技-取消', 'special_attack': '特殊攻击', 'ultimate': '终结技'}
    operation = battle.atomic_op_factory.get_atomic_op(OperationDef({'op_name': '按键-' + op_names[action]}))
    operation.execute()
    key = context.game_config.get_action_keys(backend)[action]
    assert ('tap', key) in recorder.events


@pytest.mark.parametrize('side,names,expected', [
    ('left', ['妮可', '比利'], '妮可'), ('right', ['妮可', '比利'], '比利'),
    ('left', ['邦布', '比利'], '比利'), ('right', ['妮可', '邦布'], '妮可'),
])
def test_chain_selection_updates_actual_selected_character(skills, side, names, expected):
    battle, _, _ = skills
    now = time.time()
    battle.state_record_service.batch_update_states([
        StateRecord(f'连携技-{i+1}-{name}', now) for i, name in enumerate(names)])
    getattr(battle, 'chain_' + side)()
    assert battle.agent_context.team_info.agent_list[0].agent.agent_name == expected
    assert battle.state_record_service.get_state_recorder('前台-' + expected).last_record_time > 0


@pytest.mark.parametrize('name,action', [('妮可', 'switch_next'), ('比利', 'switch_prev')])
def test_quick_assist_selects_detected_character_not_a_fixed_direction(skills, name, action):
    battle, context, recorder = skills
    battle.state_record_service.update_state(StateRecord('快速支援-' + name, time.time()))
    battle.quick_assist()
    assert ('tap', context.game_config.get_action_keys('keyboard')[action]) in recorder.events
    assert battle.agent_context.team_info.agent_list[0].agent.agent_name == name


@pytest.mark.parametrize('action', ['chain_left', 'chain_right', 'quick_assist', 'switch_by_name', 'special_attack', 'ultimate'])
def test_blocked_skill_does_not_publish_actions_or_predict_switches(skills, monkeypatch, action):
    battle, context, recorder = skills
    battle.state_record_service.batch_update_states([
        StateRecord('连携技-1-妮可', time.time()), StateRecord('连携技-2-比利', time.time()),
        StateRecord('快速支援-妮可', time.time())])
    publish = Mock(wraps=battle.state_record_service.batch_update_states)
    monkeypatch.setattr(battle.state_record_service, 'batch_update_states', publish)
    monkeypatch.setattr(context.controller, 'battle_input_guard', lambda: False)
    getattr(battle, action)(*(['妮可'] if action == 'switch_by_name' else []))
    assert recorder.events == []
    assert [i.agent.agent_name for i in battle.agent_context.team_info.agent_list] == ['安比', '妮可', '比利']
    publish.assert_not_called()


def test_old_worker_guard_blocks_state_mutation_after_a_new_session(skills):
    battle, _, recorder = skills
    token = execution_input_guard.set(lambda: False)
    try:
        battle.chain_left()
        battle.special_attack()
    finally:
        execution_input_guard.reset(token)
    assert recorder.events == []
    assert battle.state_record_service.get_state_recorder('按键-特殊攻击').last_record_time <= 0


@pytest.mark.parametrize('legacy', [False, True])
def test_ultimate_toggle_blocks_all_dsl_styles_but_allows_release(skills, legacy):
    battle, context, recorder = skills
    battle.auto_ultimate_enabled = False
    name = '按键-终结技-按下' if legacy else '按键-终结技'
    battle.atomic_op_factory.get_atomic_op(OperationDef({'op_name': name, 'press': 0.1})).execute()
    assert recorder.events == []
    battle.ultimate(release=True)
    assert ('release', context.game_config.get_action_keys('keyboard')['ultimate']) in recorder.events
    battle.auto_ultimate_enabled = True
    battle.ultimate()
    assert ('tap', context.game_config.get_action_keys('keyboard')['ultimate']) in recorder.events


def test_releases_remain_available_when_input_is_suspended(skills, monkeypatch):
    battle, context, recorder = skills
    monkeypatch.setattr(context.controller, 'battle_input_guard', lambda: False)
    battle.special_attack(release=True)
    battle.chain_left(False, None, True)
    assert all(action == 'release' for action, key in recorder.events)
    assert len(recorder.events) == 2


def test_existing_chain_avatar_templates_match_without_mocking_cv(skills):
    battle, context, _ = skills
    template = context.template_loader.get_template('battle', 'avatar_chain_anby')
    assert template is not None and template.raw is not None
    source = cv2.copyMakeBorder(template.raw, 2, 2, 2, 2, cv2.BORDER_CONSTANT)
    assert battle._match_chain_agent_in(source, [(AgentEnum.ANBY.value, None)]) is AgentEnum.ANBY.value


def test_ultimate_ready_survives_temporarily_unrecognized_character(skills):
    battle, _, _ = skills
    battle.agent_context.team_info.agent_list = [AgentInfo(None, ultimate_ready=True, special_ready=True)]
    battle.auto_op = SimpleNamespace(is_running=True, stop_running=Mock(), dispose=Mock())
    records = battle.agent_context._get_agent_state_records(time.time())
    assert any(r.state_name == '按键可用-终结技' and not r.is_clear for r in records)
    assert any(r.state_name == '按键可用-特殊攻击' and not r.is_clear for r in records)
    assert any(r.state_name == '自定义-终结技被强制释放' for r in records)


@pytest.mark.parametrize('skill', ['chain_left', 'chain_right', 'quick_assist', 'special_attack', 'ultimate'])
def test_real_common_battle_template_releases_skills_from_state_events(skills, skill):
    battle, context, recorder = skills
    battle.init_auto_op('全配队通用')
    battle.agent_context.team_info = TeamInfo(['安比', '妮可', '比利'])
    # Keep periodic camera/lock tasks out of this skill dispatch test.
    battle.auto_op.auto_lock_interval = -1
    battle.auto_op.auto_turn_interval = -1
    battle.auto_op.start_running_async()
    now = time.time()
    if skill.startswith('chain_'):
        names = ['妮可', '比利'] if skill == 'chain_left' else ['比利', '妮可']
        records = [StateRecord(f'连携技-{i+1}-{name}', now) for i, name in enumerate(names)]
        records += [StateRecord(f'连携技-{i+1}-' + ('支援' if name == '妮可' else '强攻'), now)
                    for i, name in enumerate(names)]
        records.append(StateRecord('按键可用-连携技', now))
        key_action = skill
    elif skill == 'quick_assist':
        records = [StateRecord('快速支援-妮可', now), StateRecord('按键可用-快速支援', now)]
        key_action = 'switch_next'
    else:
        # The generic fallback handles an as-yet-unidentified front character.
        records = [StateRecord('前台-能量', now, 100),
                   StateRecord('按键可用-' + ('特殊攻击' if skill == 'special_attack' else '终结技'), now)]
        key_action = skill
    battle.state_record_service.batch_update_states(records)
    key = context.game_config.get_action_keys('keyboard')[key_action]
    deadline = time.monotonic() + 2
    while not any(event == ('tap', key) for event in recorder.events) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert ('tap', key) in recorder.events, (skill, recorder.events)
