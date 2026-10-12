"""回归录制中反复打开同一武备菜单、未离开 NPC 的问题。"""
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from onedragon.base.operation.operation_base import OperationResult
from onedragon.base.operation.operation_round_result import OperationRoundResultEnum
from zzz_od.application.hollow_zero.lost_void.lost_void_challenge_config import LostVoidRegionType
from zzz_od.application.hollow_zero.lost_void.operation.lost_void_run_level import LostVoidRunLevel
from zzz_od.application.hollow_zero.lost_void.operation.interact.lost_void_interact_target_const import (
    LostVoidInteractTarget, LostVoidInteractNPC)


@pytest.fixture
def room(monkeypatch):
    import zzz_od.application.hollow_zero.lost_void.operation.lost_void_run_level as source
    monkeypatch.setattr(source.time, 'sleep', lambda *_: None)
    op = object.__new__(LostVoidRunLevel)
    op.region_type = LostVoidRegionType.ENTRY
    op.interact_target = LostVoidInteractTarget('感叹号', '感叹号', is_exclamation=True)
    op.locked_interact_target = None
    op.interacted_target_key_list, op.had_been_list = [], []
    op.repeated_interact_counts = {}
    op.entry_gear_name_list, op.entry_gear_repeat_times = [], 0
    op.entry_gear_interact_done, op.entry_door_block_times, op.attempt_start_time = False, 0, 0
    op.stuck_state = source.LostVoidStuckState()
    op.ao_fei_li_ya_talked, op.boss_pre_battle, op.interact_attempted = False, False, False
    op.last_screenshot, op.last_screenshot_time = np.zeros((1080,1920,3), np.uint8), 100
    op.ctx = SimpleNamespace(controller=Mock(background_mode=False), game_config=SimpleNamespace(background_gamepad_type='xbox'), lost_void=SimpleNamespace(
        in_normal_world=Mock(return_value=True), had_interacted_ophelia_on_current_level=False,
        detect_to_go=Mock(), detector=SimpleNamespace(is_frame_with=Mock(return_value=False))))
    op._after_round_wait = lambda **_: None
    op.check_and_update_current_screen = Mock(return_value='迷失之地-武备选择')
    choose = Mock(return_value=SimpleNamespace(execute=lambda: OperationResult(True, '携带并返回')))
    monkeypatch.setattr(source, 'LostVoidChooseGear', choose)
    return op, choose


def test_completed_gear_menu_identifies_npc_even_when_name_ocr_missed(room):
    op, choose = room
    assert op.handle_interact().result == OperationRoundResultEnum.WAIT
    assert op.locked_interact_target.name == LostVoidInteractNPC.AO_FEI_LI_YA.value
    assert op.after_interact().is_success
    assert op.ctx.lost_void.had_interacted_ophelia_on_current_level
    assert '感叹号:奥菲莉亚' in op.interacted_target_key_list
    op.ctx.controller.move_s.assert_called_once_with(press=True, press_time=2, release=True)
    choose.assert_called_once()


def test_repeated_gear_menu_is_judged_by_gear_names_and_counted(room):
    # 上游 #2735：入口层把已完成画面的首个武备名交给武备选择，由它判重并退出。
    op, choose = room
    op.ao_fei_li_ya_talked = True
    op.entry_gear_name_list.append('[携游]敕令玄幡')
    choose.STATUS_REPEATED = '重复武备选择'
    choose.return_value = SimpleNamespace(execute=lambda: OperationResult(True, '重复武备选择'))
    assert op.handle_interact().result == OperationRoundResultEnum.WAIT
    assert choose.call_args.kwargs['completed_name_list'] is op.entry_gear_name_list
    assert op.entry_gear_repeat_times == 1 and op.entry_gear_interact_done


def test_gear_menu_outside_entry_does_not_share_completed_names(room):
    op, choose = room
    op.region_type = LostVoidRegionType.COMBAT_RESONIUM
    assert op.handle_interact().result == OperationRoundResultEnum.WAIT
    assert choose.call_args.kwargs['completed_name_list'] is None


def test_entry_repeat_target_steers_before_pressing_interact(room, monkeypatch):
    import zzz_od.application.hollow_zero.lost_void.operation.lost_void_run_level as source
    op, _choose = room
    target = LostVoidInteractTarget('奥菲莉亚', '感叹号', is_npc=True)
    op.interacted_target_key_list = ['感叹号:奥菲莉亚']
    op.ctx.screen_loader = SimpleNamespace(get_area=lambda *_: SimpleNamespace(rect=SimpleNamespace(x1=0)))
    op.ctx.ocr = SimpleNamespace(crop_and_run_ocr=lambda *_: {'奥菲莉亚': SimpleNamespace(max=None)})
    op.round_by_find_area = Mock(return_value=op.round_success('交互'))
    op.screenshot = Mock()
    op._steer_towards_other_interact_icon = Mock()
    monkeypatch.setattr(source, 'match_interact_target', lambda *_: target)
    result = op.try_interact()
    assert result.result == OperationRoundResultEnum.WAIT
    op.ctx.controller.interact.assert_not_called()
    op._steer_towards_other_interact_icon.assert_called_once_with(None)
    assert op.entry_door_block_times == 1


def test_known_other_npc_is_not_overwritten_as_ophelia(room):
    op,choose=room
    target=LostVoidInteractTarget('蕾','感叹号',is_npc=True)
    op.locked_interact_target=target
    op.ctx.lost_void.had_interacted_ophelia_on_current_level=True
    assert op.handle_interact().result == OperationRoundResultEnum.WAIT
    assert op.locked_interact_target is target
    choose.assert_called_once()


def test_loading_reward_routes_to_interaction_not_repeat_stop():
    entries=LostVoidRunLevel.handle_interact.operation_edge_annotation
    assert any(e.node_from_name=='等待加载' and e.status=='识别正在交互' for e in entries)
    stop_entries=LostVoidRunLevel.stop_repeated_interact.operation_edge_annotation
    assert len(stop_entries)==1
    assert stop_entries[0].node_from_name=='尝试交互'
    assert not stop_entries[0].success


@pytest.mark.parametrize('name,expected_count', [('奥菲莉亚',1),('蕾',2)])
def test_completed_npc_filter_keeps_other_exclamation_marks(name,expected_count):
    from zzz_od.application.hollow_zero.lost_void.context.lost_void_context import LostVoidContext
    from zzz_od.application.hollow_zero.lost_void.context.lost_void_detector import LostVoidDetector
    from onedragon.yolo.detect_utils import DetectFrameResult, DetectObjectResult, DetectClass
    from onedragon.base.geometry.point import Point
    screen=np.zeros((1080,1920,3),np.uint8)
    mark=DetectClass(0,LostVoidDetector.CLASS_INTERACT)
    left=DetectObjectResult([270,150,320,220],.9,mark)
    right=DetectObjectResult([1020,110,1100,205],.9,mark)
    frame=DetectFrameResult(screen,[left,right],100)
    context=object.__new__(LostVoidContext)
    context.completed_npc_names={'奥菲莉亚'}
    context.ctx=SimpleNamespace(lost_void=SimpleNamespace(detector=SimpleNamespace(run=Mock(return_value=frame))),
        ocr_service=SimpleNamespace(get_ocr_result_list=Mock(return_value=[SimpleNamespace(data=name,center=Point(1060,235))])))
    filtered=context.detect_to_go(screen,100)
    assert len(filtered.results)==expected_count
    assert filtered.results[0] is left
    assert len(frame.results)==2  # 原始推理结果仍保留供调试。


def test_large_neighbor_mark_cannot_acknowledge_arrival_at_small_selected_mark():
    from zzz_od.application.hollow_zero.lost_void.operation.lost_void_move_by_det import LostVoidMoveByDet, MoveTargetWrapper
    from zzz_od.application.hollow_zero.lost_void.context.lost_void_detector import LostVoidDetector
    from onedragon.yolo.detect_utils import DetectFrameResult, DetectObjectResult, DetectClass
    mark=DetectClass(0,LostVoidDetector.CLASS_INTERACT)
    left=DetectObjectResult([270,150,320,220],.9,mark)
    right=DetectObjectResult([1020,110,1120,230],.9,mark)
    frame=DetectFrameResult(np.zeros((1080,1920,3),np.uint8),[left,right],100)
    op=object.__new__(LostVoidMoveByDet)
    op.stop_when_interact=True
    op.allow_arrival_by_interact_btn=False
    op.round_by_find_area=Mock(return_value=SimpleNamespace(is_success=True))
    op.get_move_target=Mock(return_value=MoveTargetWrapper(left))
    assert not op.check_interact_stop(frame.raw_image,frame)
    op.get_move_target.return_value=MoveTargetWrapper(right)
    assert op.check_interact_stop(frame.raw_image,frame)
