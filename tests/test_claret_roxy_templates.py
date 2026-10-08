"""Role dispatch, resource recognition and interruptible input; no game inputs."""
from pathlib import Path
import time
from unittest.mock import Mock

import cv2
import numpy as np
import pytest
import yaml

from onedragon.base.conditional_operation.loader import ConditionalOperatorLoader
from onedragon.base.conditional_operation.operation_executor import OperationExecutor
from onedragon.base.conditional_operation.state_recorder import StateRecord
from zzz_od.auto_battle.auto_battle_context import AutoBattleContext
from zzz_od.auto_battle.auto_battle_agent_context import CheckAgentState, TeamInfo
from zzz_od.game_data.agent import AgentEnum, AgentTypeEnum, DmgTypeEnum


@pytest.fixture
def battle(stubbed_controller, monkeypatch):
    ctx,recorder=stubbed_controller
    b=AutoBattleContext(ctx)
    monkeypatch.setitem(ctx.__dict__,'_auto_battle_context',b)
    monkeypatch.setattr(ctx.controller,'battle_input_guard',None)
    monkeypatch.setattr(ctx.controller,'battle_action_guard',None)
    monkeypatch.setattr(ctx.controller,'background_mode',False)
    b.init_screen_area()
    b.init_auto_op('全配队通用')
    b.agent_context.team_info=TeamInfo(['克拉蕾','洛克茜','丽娜'])
    b.auto_op.auto_lock_interval=b.auto_op.auto_turn_interval=-1
    yield b,ctx,recorder
    b.auto_op.stop_running()
    b.auto_op.dispose()


def record(b,role,extra=(),hud=True):
    now=time.time()
    states=[StateRecord('前台-'+role,now)]
    if hud:states.append(StateRecord('按键可用-普通攻击',now))
    states.extend(StateRecord(name,now-age,value) for name,value,age in extra)
    b.state_record_service.batch_update_states(states)
    return now


@pytest.mark.parametrize('role', ['克拉蕾','洛克茜'])
def test_dedicated_role_produces_no_operation_without_attack_hud(battle,role):
    b,_,_=battle
    now=record(b,role,hud=False)
    assert b.auto_op.normal_scene.match_execution(now) is None


@pytest.mark.parametrize('energy,age,ready,charge',[
    (89,0,True,False),(90,0,True,True),(120,0,True,True),
    (90,.6,True,False),(90,0,False,False)])
def test_roxy_charge_requires_fresh_sufficient_energy_and_special(battle,energy,age,ready,charge):
    b,_,_=battle
    extra=[('洛克茜-能量',energy,age)]
    if ready:extra.append(('洛克茜-特殊技可用',None,0))
    now=record(b,'洛克茜',extra)
    info=b.auto_op.normal_scene.match_execution(now)
    assert ('洛克茜长E充能' in info.expr_display) is charge


@pytest.mark.parametrize('form,expected',[
    (None,'克拉蕾强化特殊技进入铭刻'),(50,'克拉蕾积痕与长E毁伤循环')])
def test_claret_enters_or_cycles_from_observed_form(battle,form,expected):
    b,_,_=battle
    extra=[('克拉蕾-特殊技可用',None,0)]
    if form is not None:extra.append(('克拉蕾-猩红铭刻',form,0))
    now=record(b,'克拉蕾',extra)
    assert expected in b.auto_op.normal_scene.match_execution(now).expr_display


@pytest.mark.parametrize('role',['克拉蕾','洛克茜'])
@pytest.mark.parametrize('enabled',[True,False])
def test_role_ultimate_toggle_skips_whole_branch(battle,role,enabled):
    b,_,_=battle
    extra=[(role+'-终结技可用',None,0),('自定义-终结技被强制释放',None,0)]
    if enabled:extra.append(('自定义-自动终结技启用',None,0))
    now=record(b,role,extra)
    ops=b.auto_op.normal_scene.match_execution(now).op_list
    has_ultimate=any(op.op_name=='按键-终结技' for op in ops)
    assert has_ultimate is enabled
    if not enabled:
        assert not any(getattr(op,'state_name','')==f'自定义-{role}-终结技尝试' for op in ops)


@pytest.mark.parametrize('role',['克拉蕾','洛克茜'])
@pytest.mark.parametrize('already_dodged',[False,True])
def test_counter_dodges_once_then_attacks(battle,role,already_dodged):
    b,ctx,recorder=battle
    extra=[('自定义-红光闪避',None,0)]
    if already_dodged:extra.append(('按键-闪避',None,0))
    now=record(b,role,extra)
    info=b.auto_op.normal_scene.match_execution(now)
    executor=OperationExecutor(info.op_list,now)
    assert executor.run_async().result(timeout=2)
    keys=ctx.game_config.get_action_keys('keyboard')
    dodge=('tap',keys['dodge']); attack=('tap',keys['normal_attack'])
    assert recorder.events.count(dodge)==(0 if already_dodged else 1)
    assert attack in recorder.events
    if not already_dodged:assert recorder.events.index(dodge)<recorder.events.index(attack)


def test_roxy_returns_to_observed_claret_and_not_unseen_teammate(battle):
    b,_,_=battle
    now=record(b,'洛克茜',[('洛克茜-能量',20,0)])
    assert '洛克茜交棒克拉蕾' not in b.auto_op.normal_scene.match_execution(now).expr_display
    b.state_record_service.update_state(StateRecord('后台-克拉蕾',now))
    assert '洛克茜交棒克拉蕾' in b.auto_op.normal_scene.match_execution(now).expr_display


@pytest.mark.parametrize('stunned',[False,True])
def test_roxy_entry_does_not_steal_stun_damage_window(battle,stunned):
    b,_,_=battle
    extra=[('后台-洛克茜',None,0),('洛克茜-能量',100,0)]
    if stunned:extra.append(('自定义-失衡时间',None,0))
    now=record(b,'克拉蕾',extra)
    assert ('洛克茜能量足够时切入充能' in b.auto_op.normal_scene.match_execution(now).expr_display) is not stunned


@pytest.mark.parametrize('value,clear',[(0,True),(-1,None),(20,False)])
def test_observed_zero_clears_claret_form_but_unreadable_does_not(battle,monkeypatch,value,clear):
    from zzz_od.auto_battle.auto_battle_agent_context import _agent_state_check_method
    b,_,_=battle
    state=next(s for s in AgentEnum.CLARET.value.state_list if s.state_name=='克拉蕾-猩红铭刻')
    monkeypatch.setitem(_agent_state_check_method,state.check_way,lambda **kwargs:value)
    result=b.agent_context._check_agent_state(np.zeros((10,10,3),np.uint8),time.time(),CheckAgentState(state,3,1))
    if clear is None:assert result is None
    else:assert result.is_clear is clear


def test_real_warning_interrupts_roxy_charge_and_releases_e(battle):
    b,ctx,recorder=battle
    record(b,'洛克茜',[('洛克茜-能量',100,0),('洛克茜-特殊技可用',None,0)])
    b.auto_op.start_running_async()
    keys=ctx.game_config.get_action_keys('keyboard')
    e=keys['special_attack']
    deadline=time.monotonic()+1
    while ('press',e) not in recorder.events and time.monotonic()<deadline:time.sleep(.005)
    assert ('press',e) in recorder.events
    press_index=recorder.events.index(('press',e))
    now=time.time()
    b.state_record_service.batch_update_states([
        StateRecord('按键可用-普通攻击',now),StateRecord('闪避识别-红光',now),
        StateRecord('自定义-实时闪避事件',now,value=1)])
    deadline=time.monotonic()+.7
    while ('tap',keys['dodge']) not in recorder.events and time.monotonic()<deadline:time.sleep(.005)
    b.auto_op.stop_running()
    assert ('tap',keys['dodge']) in recorder.events
    assert ('release',e) in recorder.events[press_index+1:]
    assert b.state_record_service.get_state_recorder('自定义-洛克茜-出场结束').last_record_time<=0


def test_roxy_registration_and_all_avatar_assets(battle):
    b,ctx,_=battle
    assert AgentEnum.ROXY.value.agent_type==AgentTypeEnum.STUN
    assert AgentEnum.ROXY.value.dmg_type==DmgTypeEnum.WIND
    for category,name in [('battle','avatar_1_roxy'),('battle','avatar_2_roxy'),
                          ('battle','avatar_chain_roxy'),('battle','avatar_quick_roxy'),
                          ('hollow','avatar_roxy'),('predefined_team','avatar_roxy')]:
        raw=cv2.imread(str(Path('assets/template')/category/name/'raw.png'))
        mask=cv2.imread(str(Path('assets/template')/category/name/'mask.png'))
        assert raw is not None and mask is not None and raw.shape==mask.shape
        assert np.count_nonzero(mask)>0
    raw=cv2.cvtColor(cv2.imread('assets/template/battle/avatar_1_roxy/raw.png'),cv2.COLOR_BGR2RGB)
    agent,_=b.agent_context._match_agent_in(raw,True,[(AgentEnum.ROXY.value,'roxy'),(AgentEnum.CLARET.value,'claret')])
    assert agent==AgentEnum.ROXY.value


def test_every_bundled_entry_loads_and_dedicated_entry_is_selectable(battle):
    b,_,_=battle
    for path in Path('config/auto_battle').glob('*.sample.yml'):
        b.init_auto_op(path.name.removesuffix('.sample.yml'))
    b.init_auto_op('专属配队-克拉蕾-洛克茜')
    assert ['克拉蕾','洛克茜'] in b.auto_op.team_list
    now=record(b,'洛克茜',[('洛克茜-能量',100,0),('洛克茜-特殊技可用',None,0)])
    assert '洛克茜长E充能' in b.auto_op.normal_scene.match_execution(now).expr_display


def test_real_recorded_party_now_recognizes_roxy_in_back_slot(battle):
    from test_combat_activation import recorded_crop
    b,_,_=battle
    b.agent_context.team_info=TeamInfo()
    detected=b.agent_context._check_agent_in_parallel(recorded_crop('unknown_front_team.png',65,30))
    assert len(detected)==3 and all(agent is not None for agent,_ in detected)
    assert [agent.agent_name for agent,_ in detected]==['丽娜','克拉蕾','洛克茜']
    assert detected[2][0]==AgentEnum.ROXY.value


@pytest.mark.parametrize('team,expected',[
    (['克拉蕾','洛克茜','丽娜'],'switch_next'),
    (['克拉蕾','丽娜','洛克茜'],'switch_prev')])
def test_named_switch_obeys_actual_party_order(battle,team,expected):
    b,ctx,recorder=battle
    b.agent_context.team_info=TeamInfo(team)
    now=record(b,'克拉蕾',[('后台-洛克茜',None,0),('洛克茜-能量',100,0)])
    executor=OperationExecutor(b.auto_op.normal_scene.match_execution(now).op_list,now)
    assert executor.run_async().result(timeout=1)
    assert ('tap',ctx.game_config.get_action_keys('keyboard')[expected]) in recorder.events


def test_ultimate_gate_is_cleared_when_disabled_or_leaving_hud(battle,monkeypatch):
    b,_,_=battle
    for obj,name in [(b.dodge_context,'check_dodge_audio'),(b.dodge_context,'check_dodge_flash'),
                     (b.agent_context,'check_agent_related'),(b.target_context,'run_all_checks'),
                     (b,'check_quick_assist'),(b,'check_switch_backup')]:monkeypatch.setattr(obj,name,Mock())
    screen=np.zeros((1080,1920,3),np.uint8)
    for enabled,hud,expected in [(True,True,True),(False,True,False),(True,True,True),(True,False,False)]:
        b.auto_ultimate_enabled=enabled
        b.check_battle_state(screen,time.time(),sync=True,attack_hud_visible=hud,chain_ui_visible=False)
        assert (b.state_record_service.get_state_recorder('自定义-自动终结技启用').last_record_time>0) is expected
