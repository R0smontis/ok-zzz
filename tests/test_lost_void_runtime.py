"""迷失之地真实启动接线与遭遇战斗回归，不操作真实游戏。"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from zzz_od.context.zzz_context import ZContext
from zzz_od.application.hollow_zero.lost_void.lost_void_app import LostVoidApp
from zzz_od.application.hollow_zero.lost_void.context.lost_void_context import LostVoidContext
from zzz_od.application.hollow_zero.lost_void.context.lost_void_detector import LostVoidDetector
from zzz_od.application.hollow_zero.lost_void.operation.lost_void_move_by_det import LostVoidMoveByDet
from zzz_od.application.hollow_zero.lost_void.operation.lost_void_run_level import LostVoidRunLevel
from zzz_od.application.hollow_zero.lost_void.lost_void_challenge_config import LostVoidRegionType
from zzz_od.auto_battle.auto_battle_state_record_service import AutoBattleStateRecordService
from onedragon.base.conditional_operation.state_recorder import StateRecord
from onedragon.base.operation.operation_round_result import OperationRoundResultEnum as R
from zzz_od.game_data.agent import CommonAgentStateEnum


def test_real_lost_void_startup_resources_and_model():
    from src.lost_void_check import check_lost_void_runtime
    result = check_lost_void_runtime(Path(__file__).resolve().parents[1])
    assert result['startup_nodes'] == ['检测游戏窗口', '初始化加载', '识别初始画面']
    assert result['navigation_nodes'] == 'passed' and result['blank_inference'] == 'passed'
    assert result['artifacts'] > 100 and result['strategies'] > 0 and result['classes'] >= 14
    assert result['game_input'] == 'none'
    assert result['weekly_plan_after_bounty'] == 'passed'
    assert result['return_world_minimap'] == 'passed'
    assert result['mission_selection_verified'] == 'passed'
    assert result['gamepad_mode_recovery'] == 'passed'


def test_context_window_readiness_delegates_without_activation():
    ctx = object.__new__(ZContext)
    ctx.controller = None
    assert not ctx.is_game_window_ready
    ctx.controller = SimpleNamespace(is_game_window_ready=True, active_window=Mock())
    assert ctx.is_game_window_ready
    ctx.controller.is_game_window_ready = False
    assert not ctx.is_game_window_ready
    ctx.controller.active_window.assert_not_called()


def test_context_lost_void_is_lazy_and_cached():
    ctx = object.__new__(ZContext)
    assert 'lost_void' not in ctx.__dict__
    assert isinstance(ctx.lost_void, LostVoidContext)
    assert ctx.lost_void is ctx.lost_void and ctx.lost_void.ctx is ctx


def test_init_error_keeps_diagnostic_reason():
    app = object.__new__(LostVoidApp)
    app.config = SimpleNamespace(mission_name='战线肃清', challenge_config='默认-成就模式')
    app.run_record = SimpleNamespace(is_finished_by_day=False)
    app.ctx = SimpleNamespace(lost_void=SimpleNamespace(
        init_before_run=Mock(side_effect=FileNotFoundError('测试：缺少迷失之地模型'))))
    app._after_round_wait = lambda **_kwargs: None
    result = app.init_for_lost_void()
    assert result.is_fail and '缺少迷失之地模型' in result.status


@pytest.fixture
def encounter(monkeypatch):
    battle = SimpleNamespace(auto_op=object(), state_record_service=AutoBattleStateRecordService(),
        is_normal_attack_btn_available=Mock(return_value=True),
        agent_context=SimpleNamespace(check_agent_related=Mock()),
        dodge_context=SimpleNamespace(check_dodge_flash=Mock()))
    ctx = SimpleNamespace(auto_battle_context=battle,
        screen_loader=SimpleNamespace(get_area=Mock(return_value=object())))
    detect = Mock(return_value=None)
    ocr = Mock(return_value=False)
    monkeypatch.setattr('zzz_od.auto_battle.battle_presence.detect_battle_presence', detect)
    monkeypatch.setattr('zzz_od.application.hollow_zero.lost_void.context.lost_void_context.screen_utils.find_by_ocr', ocr)
    return LostVoidContext(ctx), battle, detect, ocr


def test_missing_attack_hud_skips_enemy_flash_agent_and_ocr(encounter):
    lost, battle, detect, ocr = encounter
    battle.is_normal_attack_btn_available.return_value = False
    assert not lost.check_battle_encounter(np.zeros((1080, 1920, 3), np.uint8), 100)
    detect.assert_not_called()
    ocr.assert_not_called()
    battle.agent_context.check_agent_related.assert_not_called()
    battle.dodge_context.check_dodge_flash.assert_not_called()


@pytest.mark.parametrize('evidence', ['敌人血条', '敌人方向箭头'])
def test_visible_enemy_can_trigger_before_operator_is_loaded(encounter, evidence):
    lost, battle, detect, _ocr = encounter
    battle.auto_op = None
    detect.return_value = evidence
    assert lost.check_battle_encounter(np.zeros((1080, 1920, 3), np.uint8), 100)


@pytest.mark.parametrize('layout', [CommonAgentStateEnum.LIFE_DEDUCTION_21,
                                  CommonAgentStateEnum.LIFE_DEDUCTION_31])
@pytest.mark.parametrize('record_time', [100,99])
def test_hp_loss_alone_does_not_trigger_combat_in_either_team_layout(encounter, layout, record_time):
    lost, battle, _detect, _ocr = encounter
    battle.state_record_service.batch_update_states([StateRecord(layout.value.state_name, record_time)])
    assert not lost.check_battle_encounter(np.zeros((1080, 1920, 3), np.uint8), 100)


@pytest.mark.parametrize('method', ['turn_at_first', 'move_towards'])
def test_navigation_yields_to_battle_before_detection_and_movement(method):
    op = object.__new__(LostVoidMoveByDet)
    lost = SimpleNamespace(in_normal_world=Mock(return_value=True),
        check_battle_encounter=Mock(return_value=True), detect_to_go=Mock())
    op.ctx = SimpleNamespace(lost_void=lost, controller=SimpleNamespace(stop_moving_forward=Mock()))
    op.last_screenshot, op.last_screenshot_time = object(), 100
    op._after_round_wait = lambda **_kwargs: None
    result = getattr(op, method)()
    assert result.is_success and result.status == LostVoidMoveByDet.STATUS_IN_BATTLE
    lost.detect_to_go.assert_not_called()
    op.ctx.controller.stop_moving_forward.assert_called_once()


def test_level_yields_to_battle_before_interact_or_pathfinding():
    op = object.__new__(LostVoidRunLevel)
    op.ctx = SimpleNamespace(lost_void=SimpleNamespace(in_normal_world=lambda _: True,
        check_battle_encounter=lambda *_args: True, detect_to_go=Mock()))
    op.boss_pre_battle = False
    op.last_screenshot, op.last_screenshot_time = object(), 100
    op._after_round_wait = lambda **_kwargs: None
    result = op.non_battle_check()
    assert result.is_success and result.status == '进入战斗'
    op.ctx.lost_void.detect_to_go.assert_not_called()


@pytest.mark.parametrize('enemy_present', [False, True])
def test_combat_room_does_not_start_attacks_without_current_evidence(enemy_present):
    op = object.__new__(LostVoidRunLevel)
    battle = SimpleNamespace(start_auto_battle=Mock())
    op.ctx = SimpleNamespace(auto_battle_context=battle,
        lost_void=SimpleNamespace(check_battle_encounter=lambda *_args: enemy_present))
    op.last_screenshot, op.last_screenshot_time = object(), 100
    op._after_round_wait = lambda **_kwargs: None
    result = op.init_auto_op()
    assert result.is_success
    if enemy_present:
        battle.start_auto_battle.assert_called_once()
    else:
        assert result.status == '等待战斗信号'
        battle.start_auto_battle.assert_not_called()


@pytest.mark.parametrize('now,enemy,renewed', [(109,False,110),(110,True,120),(110,False,110)])
def test_lost_void_combat_rechecks_only_at_ten_second_boundary(now,enemy,renewed):
    op=object.__new__(LostVoidRunLevel)
    battle=SimpleNamespace(check_battle_state=Mock(return_value=True),stop_auto_battle=Mock())
    encounter=Mock(return_value=enemy)
    op.ctx=SimpleNamespace(auto_battle_context=battle,lost_void=SimpleNamespace(check_battle_encounter=encounter),
        battle_assistant_config=SimpleNamespace(screenshot_interval=.05))
    op.last_screenshot=object()
    op.last_screenshot_time=now
    op.current_frame_in_battle=True
    op.battle_lease_until=110
    op.battle_absent_since=None
    op.last_det_time=now
    op.not_in_battle_times=0
    op._after_round_wait=lambda **_: None
    result=op.in_battle()
    assert encounter.call_count == (now>=110)
    assert op.battle_lease_until==renewed
    if now>=110 and not enemy:
        assert result.result == R.WAIT
        battle.stop_auto_battle.assert_not_called()
        op.last_screenshot_time=110.31
        result=op.in_battle()
        assert result.is_success and result.status=='识别需移动交互'
        battle.stop_auto_battle.assert_called_once()
    else:
        battle.stop_auto_battle.assert_not_called()


def test_temporary_enemy_occlusion_does_not_stop_combat():
    op=object.__new__(LostVoidRunLevel)
    battle=SimpleNamespace(check_battle_state=Mock(return_value=True),stop_auto_battle=Mock())
    encounter=Mock(side_effect=[False,True])
    op.ctx=SimpleNamespace(auto_battle_context=battle,lost_void=SimpleNamespace(check_battle_encounter=encounter),
        battle_assistant_config=SimpleNamespace(screenshot_interval=.05))
    op.last_screenshot=object()
    op.last_screenshot_time=110
    op.current_frame_in_battle=True
    op.battle_lease_until=110
    op.battle_absent_since=None
    op.last_det_time=110
    op.not_in_battle_times=0
    op._after_round_wait=lambda **_: None
    assert op.in_battle().result == R.WAIT
    op.last_screenshot_time=110.1
    assert op.in_battle().result == R.WAIT
    assert op.battle_lease_until==120.1 and op.battle_absent_since is None
    battle.stop_auto_battle.assert_not_called()


@pytest.mark.parametrize('targets,expected', [('0000-感叹号', True),
    (['0000-感叹号', '0001-距离'], True), ('x0000-感叹号x', False), (None, False)])
def test_detector_matches_exact_classes(targets, expected):
    detector = object.__new__(LostVoidDetector)
    frame = SimpleNamespace(results=[SimpleNamespace(detect_class=SimpleNamespace(class_name='0000-感叹号'))])
    assert detector.is_frame_with(frame, targets) is expected


def test_start_room_training_dummy_never_counts_as_an_encounter(encounter):
    import cv2
    from pathlib import Path
    from zzz_od.auto_battle.battle_presence import find_enemy_health_bar
    path = Path(__file__).parent / 'fixtures/lost_void/start_room_training_dummy.png'
    screen = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
    # The dummy's panel is a genuine health-bar match; only room context separates it.
    assert find_enemy_health_bar(screen) is not None
    lost, _battle, detect, _ocr = encounter
    detect.return_value = '敌人血条'
    lost.in_start_room = True
    assert not lost.check_battle_encounter(screen, 100)
    lost.in_start_room = False
    assert lost.check_battle_encounter(screen, 100)


@pytest.mark.parametrize('status,cleared', [(LostVoidRunLevel.STATUS_NEXT_LEVEL, True),
                                            (LostVoidRunLevel.STATUS_COMPLETE, True),
                                            ('代理人阵亡', False)])
def test_start_room_flag_lasts_until_the_first_level_is_left(monkeypatch, status, cleared):
    from zzz_od.application.hollow_zero.lost_void import lost_void_app
    app = object.__new__(LostVoidApp)
    app.ctx = SimpleNamespace(lost_void=SimpleNamespace(in_start_room=True,
        had_interacted_ophelia_on_current_level=True, completed_npc_names={'x'}))
    app.next_region_type = LostVoidRegionType.ENTRY
    app.round_by_op_result = lambda result: result
    monkeypatch.setattr(lost_void_app, 'LostVoidRunLevel', Mock(
        return_value=SimpleNamespace(execute=lambda: SimpleNamespace(success=True, status=status, data=None)),
        STATUS_NEXT_LEVEL=LostVoidRunLevel.STATUS_NEXT_LEVEL, STATUS_COMPLETE=LostVoidRunLevel.STATUS_COMPLETE))
    app.run_level()
    assert app.ctx.lost_void.in_start_room is not cleared
