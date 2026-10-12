"""Mixed portals captured during the live task-force navigation failure."""
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from onedragon.yolo.detect_utils import DetectClass, DetectObjectResult, DetectFrameResult
from zzz_od.application.hollow_zero.lost_void.context.lost_void_context import LostVoidContext
from zzz_od.application.hollow_zero.lost_void.operation.lost_void_move_by_det import LostVoidMoveByDet, MoveTargetWrapper, LostVoidStuckState
from zzz_od.application.hollow_zero.lost_void.operation.lost_void_run_level import LostVoidRunLevel
from zzz_od.application.hollow_zero.lost_void.lost_void_challenge_config import LostVoidRegionType


def target(x, name):
    return DetectObjectResult([x,240,x+45,285], .9, DetectClass(5,name))


def test_mixed_challenge_store_remains_navigable_after_store_visit():
    lost = object.__new__(LostVoidContext)
    lost.had_interacted_ophelia_on_current_level = False
    lost.challenge_config = SimpleNamespace(region_type_priority=['挑战-无伤','邦布商店'])
    op = object.__new__(LostVoidMoveByDet)
    op.ctx = SimpleNamespace(lost_void=lost)
    op.ignore_entry_list = ['邦布商店']
    op.last_target_result = None
    frame = DetectFrameResult(np.zeros((1080,1920,3),np.uint8),
        [target(1515,'0005-挑战-无伤'),target(1565,'0010-邦布商店')],100)
    result = op.get_entry_target(frame)
    assert result is not None and result.merge_parent is None
    assert result.target_name_list == ['挑战-无伤','邦布商店']
    assert result.leftest_target_name == '挑战-无伤'
    assert (result.entire_rect.x1,result.entire_rect.x2) == (1515,1610)


def test_completed_shop_does_not_hide_standalone_portal_from_level_navigation(monkeypatch):
    import zzz_od.application.hollow_zero.lost_void.operation.lost_void_run_level as source
    frame = DetectFrameResult(np.zeros((1080,1920,3),np.uint8),
        [target(1000, '0010-邦布商店')], 100)
    detector = SimpleNamespace(is_frame_with_all=lambda _: (False, False, True))
    lost = SimpleNamespace(in_normal_world=lambda _: True,
        check_battle_encounter=lambda *_: False, priority_updated=True,
        detector=detector, detect_to_go=Mock(return_value=frame))
    op = object.__new__(LostVoidRunLevel)
    op.ctx = SimpleNamespace(lost_void=lost)
    op.last_screenshot, op.last_screenshot_time = frame.raw_image, 100
    op.operation_start_time = 99
    op.boss_pre_battle = False
    op.attempt_start_time = 0
    op.region_type = LostVoidRegionType.COMBAT_RESONIUM
    op.had_been_list = ['邦布商店']
    op.stuck_state = LostVoidStuckState()
    op._after_round_wait = lambda **_: None
    movement = Mock(return_value=SimpleNamespace(execute=lambda: SimpleNamespace(
        success=True, status=LostVoidMoveByDet.STATUS_ARRIVAL, data='邦布商店')))
    monkeypatch.setattr(source, 'LostVoidMoveByDet', movement)
    result = op.non_battle_check()
    assert result.is_success and result.status == 'xxxx-入口'
    assert lost.detect_to_go.call_args.kwargs.get('ignore_list') is None
    assert movement.call_args.kwargs.get('ignore_entry_list') is None


def test_three_adjacent_icons_merge_once_without_cycles_or_duplicates():
    items = [MoveTargetWrapper(target(100+i*50,f'{i:04d}-区域{i}')) for i in range(3)]
    for first in items:
        for second in items:
            if first is not second:
                first.merge_another_target(second)
    roots = [x for x in items if x.merge_parent is None]
    assert len(roots) == 1
    assert roots[0].target_name_list == ['区域0','区域1','区域2']
    assert roots[0].entire_rect.x2 == 245
    assert not roots[0].merge_another_target(roots[0])


def test_acknowledged_room_restart_resets_deadline_and_interaction_memory(monkeypatch):
    import zzz_od.application.hollow_zero.lost_void.operation.lost_void_run_level as source
    op = object.__new__(LostVoidRunLevel)
    op.ctx = SimpleNamespace(lost_void=SimpleNamespace(completed_npc_names={'奥菲莉亚'},
        had_interacted_ophelia_on_current_level=True))
    op.restart_count = 0
    op.operation_start_time = 1
    op.nothing_times = 49
    op.had_been_list = ['邦布商店']
    op.interacted_target_key_list = ['感叹号:奥菲莉亚']
    op.repeated_interact_counts = {'奥菲莉亚':3}
    op.locked_interact_target = object()
    op.ao_fei_li_ya_talked = True
    op.entry_gear_name_list = ['[携游]敕令玄幡']
    op.entry_gear_repeat_times, op.entry_gear_interact_done, op.entry_door_block_times = 2, True, 3
    op.region_type = LostVoidRegionType.BOSS
    op._after_round_wait = lambda **_: None
    monkeypatch.setattr(source.time,'time',lambda:1000)
    monkeypatch.setattr(source,'RestartInBattle',Mock(return_value=SimpleNamespace(
        execute=lambda:SimpleNamespace(success=True))))
    assert op.handle_find_target_fail().status == '准备重试'
    assert op.attempt_start_time == 1000 and op.operation_start_time == 1
    assert not op.entry_gear_name_list and op.entry_gear_repeat_times == 0 and op.entry_door_block_times == 0
    assert op.restart_count == 1 and op.boss_pre_battle
    assert not op.had_been_list and not op.interacted_target_key_list and not op.repeated_interact_counts
    assert not op.ctx.lost_void.completed_npc_names
    assert not op.ctx.lost_void.had_interacted_ophelia_on_current_level


def test_failed_restart_keeps_original_deadline(monkeypatch):
    import zzz_od.application.hollow_zero.lost_void.operation.lost_void_run_level as source
    op = object.__new__(LostVoidRunLevel)
    op.ctx = object()
    op.restart_count = 0
    op.region_type = LostVoidRegionType.BOSS
    op.attempt_start_time = 5
    op._after_round_wait = lambda **_: None
    monkeypatch.setattr(source,'RestartInBattle',Mock(return_value=SimpleNamespace(
        execute=lambda:SimpleNamespace(success=False,status='未核验重新开始'))))
    assert op.handle_find_target_fail().is_fail
    assert op.attempt_start_time == 5


def test_static_chosen_target_triggers_escape_despite_peripheral_flicker(monkeypatch):
    import zzz_od.application.hollow_zero.lost_void.operation.lost_void_move_by_det as source
    op=object.__new__(LostVoidMoveByDet)
    op.ctx=SimpleNamespace(controller=Mock())
    op._after_round_wait=lambda **_:None
    op.stuck_state=LostVoidStuckState()
    op.last_target_result=MoveTargetWrapper(target(900,'0003-战斗-武备'))
    op._reset_stuck_status()
    clock=[100]
    monkeypatch.setattr(source.time,'time',lambda:clock[0])
    for i in range(7):
        clock[0]=100+i
        chosen=target(900+i%2,'0003-战斗-武备')
        objects=[chosen]+([target(1400,'0012-战斗-道中危机')] if i%2 else [])
        frame=DetectFrameResult(np.zeros((1080,1920,3),np.uint8),objects,clock[0])
        result=op.check_stuck(frame,MoveTargetWrapper(chosen))
        if i<6:assert result is None
    assert result.status == '尝试脱困'
    assert op.stuck_state.stuck_times == 1
    op.ctx.controller.stop_moving_forward.assert_called_once()


def test_approaching_target_does_not_trigger_static_escape(monkeypatch):
    import zzz_od.application.hollow_zero.lost_void.operation.lost_void_move_by_det as source
    op=object.__new__(LostVoidMoveByDet)
    op.ctx=SimpleNamespace(controller=Mock())
    op.stuck_state=LostVoidStuckState()
    op.last_target_result=MoveTargetWrapper(target(900,'0003-战斗-武备'))
    op._reset_stuck_status()
    clock=[100]
    monkeypatch.setattr(source.time,'time',lambda:clock[0])
    for i in range(20):
        clock[0]=100+i
        chosen=target(900+20*i,'0003-战斗-武备')
        frame=DetectFrameResult(np.zeros((1080,1920,3),np.uint8),[chosen],clock[0])
        assert op.check_stuck(frame,MoveTargetWrapper(chosen)) is None
    assert op.stuck_state.stuck_times == 0
    op.ctx.controller.stop_moving_forward.assert_not_called()
