"""Recorded missed starts, partial parties and bounded generic attacks."""
import json
import time
from pathlib import Path
from unittest.mock import Mock

import cv2
import numpy as np
import pytest

from onedragon.base.conditional_operation.state_recorder import StateRecord
from zzz_od.auto_battle.auto_battle_agent_context import TeamInfo
from zzz_od.auto_battle.auto_battle_context import AutoBattleContext
from zzz_od.auto_battle.auto_battle_state import BattleStateEnum
from zzz_od.auto_battle.battle_presence import detect_battle_presence, has_enemy_health_bar, has_chain_timer

FIXTURES = Path(__file__).parent / 'fixtures/combat_recording'


def recorded_crop(name, x, y):
    rgb = cv2.cvtColor(cv2.imread(str(FIXTURES / name)), cv2.COLOR_BGR2RGB)
    frame = np.zeros((1080, 1920, 3), np.uint8)
    frame[y:y+rgb.shape[0], x:x+rgb.shape[1]] = rgb
    return frame


@pytest.mark.parametrize('name', ['75.png', '76.png', '80.png'])
def test_filled_daze_panel_from_latest_recording_is_enemy_evidence(name):
    rgb = cv2.cvtColor(cv2.imread(str(FIXTURES.parent / 'latest_filled_daze' / name)), cv2.COLOR_BGR2RGB)
    frame = np.zeros((1080, 1920, 3), np.uint8)
    frame[300:650, 500:1250] = rgb
    assert has_enemy_health_bar(frame)
    # Recognition reads the panel cap, not the color of the nearby badge.
    for color in [(0, 0, 0), (0, 255, 120), (255, 80, 200)]:
        altered = frame.copy()
        # The captured panels' badges are right of their two-row cap.
        if name == '75.png':
            altered[370:445, 820:905] = color
        assert has_enemy_health_bar(altered)


@pytest.mark.parametrize('color', [(0, 0, 0), (0, 200, 255), (120, 255, 40), (255, 20, 30)])
def test_enemy_badge_color_and_absence_do_not_affect_detection(color):
    frame = recorded_crop('near_enemy.png', 830, 370)
    # Remove the entire badge, then replace it with unrelated colors.
    frame[370:460, 980:1100] = color
    assert has_enemy_health_bar(frame)


@pytest.mark.parametrize('name,x,y', [('user_low_health.png', 918, 395),
                                    ('empty_health_daze.png', 680, 385)])
def test_user_low_or_empty_health_panel_detected_without_attribute_badge(name, x, y):
    frame = recorded_crop(name, x, y)
    # Both attribute badges are entirely outside the structural left cap.
    if name.startswith('user'):
        frame[:, 1040:] = 0
    if name.startswith('empty'):
        frame[385:447, 840:925] = 0
    assert has_enemy_health_bar(frame)


def test_real_pink_chain_timer_reopens_combat_without_input(ctx, monkeypatch):
    battle = AutoBattleContext(ctx)
    battle.init_screen_area()
    frame = recorded_crop('chain_latest.png', 450, 820)
    monkeypatch.setattr(battle, 'is_normal_attack_btn_available', lambda _: False)
    monkeypatch.setattr(battle.ctx.cv_service, 'run_pipeline', Mock(
        side_effect=AssertionError('legacy orange pipeline is unnecessary')))
    assert has_chain_timer(frame)
    assert detect_battle_presence(frame, battle) == '连携技'
    battle.state_record_service.update_state = Mock()
    assert battle._check_chain_bar(frame, time.time())
    assert battle.state_record_service.update_state.call_args.args[0].state_name == '连携技-准备'
    # A colored progress strip without chain portraits is insufficient.
    frame[820:950, :607] = 0
    frame[820:950, 1314:] = 0
    assert detect_battle_presence(frame, battle) is None


def test_unknown_party_slot_is_preserved_through_real_avatar_matching(ctx):
    battle = AutoBattleContext(ctx)
    battle.init_screen_area()
    agent = battle.agent_context
    agent.team_info = TeamInfo()
    frame = recorded_crop('unknown_front_team.png', 65, 30)
    # This historical crop contains Roxy, now registered. Occlude only the
    # front avatar to keep testing a truly unreadable slot.
    rect = agent.area_agent_3_1.rect
    frame[rect.y1:rect.y2, rect.x1:rect.x2] = 0
    detected = agent._check_agent_in_parallel(frame)
    assert len(detected) == 3
    assert len([a for a, _ in detected if a]) == 2
    agent.team_info.update_agent_list(detected, [], [], [], time.time())
    assert len(agent._check_agent_in_parallel(frame)) == 3


def test_three_person_hud_recovers_an_existing_single_person_cache(ctx):
    battle = AutoBattleContext(ctx)
    battle.init_screen_area()
    agent = battle.agent_context
    agent.team_info = TeamInfo(['丽娜'])
    frame = recorded_crop('unknown_front_team.png', 65, 30)
    rect = agent.area_agent_3_1.rect
    frame[rect.y1:rect.y2, rect.x1:rect.x2] = 0
    detected = agent._check_agent_in_parallel(frame)
    assert len(detected) == 3
    assert len([a for a, _ in detected if a]) == 2
    assert agent.team_info.should_check_all_agents


def test_animation_cannot_collapse_previously_verified_three_slot_layout(ctx):
    battle = AutoBattleContext(ctx)
    battle.init_screen_area()
    agent = battle.agent_context
    frame = recorded_crop('unknown_front_team.png', 65, 30)
    assert len(agent._check_agent_in_parallel(frame)) == 3
    blank = np.zeros_like(frame)
    assert len(agent._check_agent_in_parallel(blank)) == 3
    agent.init_battle_agent_context()
    assert len(agent._check_agent_in_parallel(blank)) == 1


def test_unknown_names_and_switches_preserve_physical_party_order():
    team = TeamInfo(['克拉蕾', '未收录的角色', '丽娜'])
    assert [a.agent.agent_name if a.agent else None for a in team.agent_list] == ['克拉蕾', None, '丽娜']
    team.switch_next_agent(1)
    assert [a.agent.agent_name if a.agent else None for a in team.agent_list] == [None, '丽娜', '克拉蕾']
    team.switch_prev_agent(2)
    assert [a.agent.agent_name if a.agent else None for a in team.agent_list] == ['克拉蕾', None, '丽娜']


def test_partial_team_keeps_full_candidate_search():
    team = TeamInfo(['克拉蕾', '未收录的角色', '丽娜'])
    team.should_check_all_agents = True
    current = [(a.agent, None) for a in team.agent_list]
    for i in range(10):
        team.update_agent_list(current, [], [], [], i+1)
    assert team.should_check_all_agents


def test_entirely_unknown_party_retains_common_ready_states():
    team=TeamInfo()
    assert team.update_agent_list([(None,None)]*3,[70,20,10],[1,0,0],[1,0,0],1)
    assert len(team.agent_list)==3 and team.should_check_all_agents
    assert team.agent_list[0].special_ready and team.agent_list[0].ultimate_ready
    # A temporary miss must not erase an established known party.
    known=TeamInfo(['克拉蕾','丽娜'])
    assert not known.update_agent_list([(None,None)]*2,[70,20],[1,0],[1,0],1)
    assert known.agent_list[0].agent.agent_name=='克拉蕾'


def test_unknown_front_clears_stale_role_states():
    from zzz_od.auto_battle.auto_battle_state_record_service import AutoBattleStateRecordService
    service = AutoBattleStateRecordService()
    service.batch_update_states([StateRecord('前台-克拉蕾', 100), StateRecord('前台-强攻', 100)])
    service.update_state(StateRecord(BattleStateEnum.STATUS_UNKNOWN_FRONT.value, 101))
    assert service.get_state_recorder('前台-克拉蕾').last_record_time == 0
    assert service.get_state_recorder('前台-强攻').last_record_time == 0
    service.update_state(StateRecord('前台-丽娜', 102))
    assert service.get_state_recorder(BattleStateEnum.STATUS_UNKNOWN_FRONT.value).last_record_time == 0


def test_unknown_role_basic_attack_respects_combat_gate(ctx, stubbed_controller, monkeypatch):
    context, recorder = stubbed_controller
    battle = AutoBattleContext(context)
    monkeypatch.setitem(context.__dict__, '_auto_battle_context', battle)
    allowed = [False]
    monkeypatch.setattr(context.controller, 'battle_input_guard', lambda: allowed[0])
    battle.init_screen_area()
    battle.init_auto_op('全配队通用')
    op = battle.auto_op
    op.auto_lock_interval = op.auto_turn_interval = -1
    op.execution_allowed = lambda: allowed[0]
    attack = ('tap', context.game_config.get_action_keys('keyboard')['normal_attack'])
    try:
        op.start_running_async()
        now = time.time()
        battle.state_record_service.batch_update_states([
            StateRecord('前台-未识别', now), StateRecord('按键可用-普通攻击', now)])
        time.sleep(.08)
        assert attack not in recorder.events
        allowed[0] = True
        deadline = time.monotonic()+1
        while attack not in recorder.events and time.monotonic()<deadline:
            now = time.time()
            battle.state_record_service.batch_update_states([
                StateRecord('前台-未识别', now), StateRecord('按键可用-普通攻击', now)])
            time.sleep(.01)
        assert attack in recorder.events
        allowed[0] = False
        time.sleep(.03)
        count = recorder.events.count(attack)
        time.sleep(.18)
        assert recorder.events.count(attack) == count
    finally:
        op.stop_running()
        op.dispose()
