"""后台菜单必须从新画面核验效果，不能用消息投递次数代替游戏状态。"""
from types import SimpleNamespace
from unittest.mock import Mock
from pathlib import Path
import json

import cv2
import numpy as np
import pytest

from onedragon.base.geometry.rectangle import Rect
from onedragon.base.operation.operation_round_result import OperationRoundResultEnum as R
from zzz_od.application.hollow_zero.lost_void.mission_screen import collection_tab, focused_gear, focused_card, battle_result, dialogue_visible, failed_grade
from zzz_od.application.hollow_zero.lost_void.operation.interact.lost_void_choose_common import LostVoidChooseCommon
from zzz_od.application.hollow_zero.lost_void.operation.interact.lost_void_choose_gear import LostVoidChooseGear
from zzz_od.application.hollow_zero.lost_void.operation.update_priority_operation import UpdatePriorityOperation
from zzz_od.operation.deploy import Deploy
from zzz_od.application.hollow_zero.lost_void.operation.lost_void_run_level import LostVoidRunLevel
from zzz_od.application.hollow_zero.lost_void.operation.interact.lost_void_route_change import LostVoidRouteChange
from zzz_od.application.hollow_zero.lost_void.operation.interact.lost_void_bangboo_store import LostVoidBangbooStore
from zzz_od.application.hollow_zero.lost_void.operation.interact.lost_void_lottery import LostVoidLottery
from zzz_od.operation.challenge_mission.restart_in_battle import RestartInBattle
from zzz_od.operation.challenge_mission.exit_in_battle import ExitInBattle


@pytest.mark.parametrize('text,result,pressed', [('开始3/3',R.SUCCESS,True),
    ('开始0/3',R.SUCCESS,False),('开始',R.RETRY,False),('开始4/3',R.RETRY,False)])
def test_background_lottery_reads_full_button_and_requires_valid_count(text,result,pressed):
    op=operation(LostVoidLottery)
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=Mock(return_value=[SimpleNamespace(data=text)]))
    assert op.click_start().result == result
    assert op.ctx.controller.btn_press.called == pressed
    if pressed:
        op.ctx.controller.btn_press.assert_called_once_with('xbox_a',press_time=.12)
    rect=op.ctx.ocr_service.get_ocr_result_list.call_args.kwargs['rect']
    assert rect.x1 <= 804 and rect.x2 >= 1120


def test_background_lottery_rejects_repeated_start_without_count_change():
    op=operation(LostVoidLottery)
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=lambda **_: [SimpleNamespace(data='开始3/3')])
    for _ in range(3):
        assert op.click_start().is_success
    assert op.click_start().is_fail
    assert op.ctx.controller.btn_press.call_count == 3


def test_background_lottery_waits_for_world_after_back_and_bounds_retries():
    op=operation(LostVoidLottery)
    for _ in range(3):
        assert op.back_to_world().result == R.WAIT
    assert op.back_to_world().is_fail
    op.ctx.lost_void.in_normal_world.return_value=True
    assert op.back_to_world().is_success
    assert op.ctx.controller.btn_press.call_count == 3
    assert all(call.args == ('xbox_b',) for call in op.ctx.controller.btn_press.call_args_list)


@pytest.mark.parametrize('confirmed', [False,True])
def test_lottery_reward_only_finishes_on_verified_return_after_confirmation(confirmed):
    op=operation(LostVoidChooseCommon)
    op._pad_confirm_requests=int(confirmed)
    op.return_screen_name='迷失之地-抽奖机'
    op.check_and_update_current_screen=Mock(return_value='迷失之地-抽奖机')
    result=op._choose_with_pad()
    assert result.is_success == confirmed
    op.ctx.controller.btn_press.assert_not_called()


def test_restart_recognizes_actual_gamepad_footer_without_old_button_coordinates():
    op=operation(RestartInBattle)
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=lambda **_: [
        SimpleNamespace(data=name) for name in ('重新开始','退出战斗','选择','返回')])
    assert op.check_screen().is_success
    op.ctx.controller.btn_press.assert_not_called()


def test_restart_opens_menu_once_only_with_attack_hud():
    op=operation(RestartInBattle)
    op._menu_texts=lambda: set()
    op.ctx.auto_battle_context=SimpleNamespace(is_normal_attack_btn_available=Mock(return_value=False))
    assert op.check_screen().result == R.RETRY
    op.ctx.controller.btn_press.assert_not_called()
    op.ctx.auto_battle_context.is_normal_attack_btn_available.return_value=True
    for _ in range(3):
        assert op.check_screen().result == R.RETRY
    op.ctx.controller.btn_press.assert_called_once_with('xbox_start',press_time=.12)


def test_restart_waits_for_confirmation_before_advancing():
    op=operation(RestartInBattle)
    op._menu_texts=lambda: {'重新开始','退出战斗'}
    op.round_by_find_area=Mock(return_value=op.round_retry())
    assert op.click_exit_battle().result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_x',press_time=.12)
    op.round_by_find_area.return_value=op.round_success()
    assert op.click_exit_battle().is_success
    assert op.ctx.controller.btn_press.call_count == 1


def test_restart_confirmation_is_not_repeated_and_requires_closed_popup():
    op=operation(RestartInBattle)
    op.last_screenshot[607:650,1038:1224]=(255,230,0)
    op.round_by_find_area=Mock(return_value=op.round_success())
    assert op.click_confirm().result == R.WAIT
    assert op.click_confirm().result == R.RETRY
    op.ctx.controller.btn_press.assert_called_once_with('xbox_a',press_time=.12)
    op.round_by_find_area.return_value=op.round_retry()
    assert op.click_confirm().is_success


def test_restart_moves_focus_without_confirming_cancel_button():
    op=operation(RestartInBattle)
    op.last_screenshot[607:650,700:900]=(255,230,0)
    op.round_by_find_area=Mock(return_value=op.round_success())
    assert op.click_confirm().result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_dpad_right',press_time=.12)
    op.last_screenshot[:]=0
    assert op.click_confirm().result == R.RETRY
    assert op.ctx.controller.btn_press.call_count == 1


def test_lost_void_resumes_from_paused_battle_with_bounded_back_input():
    from zzz_od.application.hollow_zero.lost_void.lost_void_app import LostVoidApp
    op=operation(LostVoidApp)
    op.lost_void_debug=False
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=lambda **_: [
        SimpleNamespace(data=name) for name in ('重新开始','退出战斗')])
    for _ in range(3):
        assert op.check_initial_screen().result == R.WAIT
    assert op.check_initial_screen().is_fail
    assert op.ctx.controller.btn_press.call_count == 3


def operation(cls):
    op = object.__new__(cls)
    op.last_screenshot = np.zeros((1080,1920,3), np.uint8)
    op._after_round_wait = lambda **_: None
    op.ctx = SimpleNamespace(controller=Mock(background_mode=True),
        game_config=SimpleNamespace(background_gamepad_type='xbox', get_gamepad_action_keys=lambda: {'minimap':['xbox_back']}),
        lost_void=SimpleNamespace(in_normal_world=Mock(return_value=False), priority_updated=True,
            challenge_config=SimpleNamespace(artifact_priority_new=True, artifact_priority_in_battle=[]), get_artifact_by_priority=Mock(return_value=[])))
    if cls is LostVoidChooseGear:
        op.completed_name_list, op.first_slot_gear_name = None, None
    if cls is LostVoidChooseCommon:
        op.to_choose_num=1
        op.to_choose_artifact=op.to_choose_gear=False
        op._pad_reward_confirm=False
    return op


def lottery_fixture(op):
    path=Path(__file__).parent/'fixtures/lost_void/lottery_delayed.png'
    op.last_screenshot=cv2.cvtColor(cv2.imread(str(path)),cv2.COLOR_BGR2RGB)
    data=json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
    rows=[SimpleNamespace(data=row['text'],center=Rect(row['rect'][0],row['rect'][1],
        row['rect'][0]+row['rect'][2],row['rect'][1]+row['rect'][3]).center) for row in data['result']['ocr']]
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=Mock(return_value=rows))
    return rows


@pytest.mark.parametrize('missing',[None,'preview','start','count','invalid_count','button'])
def test_real_controller_lottery_requires_preview_count_and_visible_button(missing):
    from zzz_od.application.hollow_zero.lost_void.mission_screen import lottery_counts
    op=operation(LostVoidLottery)
    rows=lottery_fixture(op)
    if missing=='button':op.last_screenshot[:]=0
    elif missing=='preview':rows[:]=[row for row in rows if row.data!='奖励预览']
    elif missing=='start':rows[:]=[row for row in rows if not row.data.startswith('开始')]
    elif missing=='count':rows[-1].data='开始'
    elif missing=='invalid_count':rows[-1].data='开始2/1'
    assert lottery_counts(op.ctx,op.last_screenshot)==((1,1) if missing is None else None)
    op.ctx.controller.btn_press.assert_not_called()


def test_loading_resumes_verified_controller_lottery_without_legacy_screen_match():
    op=operation(LostVoidRunLevel)
    lottery_fixture(op)
    op.check_and_update_current_screen=Mock(return_value=None)
    assert op.wait_loading().status=='识别正在交互'
    op.ctx.controller.btn_press.assert_not_called()


def test_delayed_lottery_reenters_handler_without_marking_npc_complete():
    op=operation(LostVoidRunLevel)
    lottery_fixture(op)
    op.locked_interact_target=SimpleNamespace(name='衰仔')
    op.ctx.lost_void.completed_npc_names=set()
    assert op.after_interact().status=='后续交互'
    assert op.locked_interact_target.name=='衰仔'
    assert op.ctx.lost_void.completed_npc_names==set()


def test_controller_lottery_dispatches_specialized_operation_without_legacy_match(monkeypatch):
    op=operation(LostVoidRunLevel)
    lottery_fixture(op)
    op.check_and_update_current_screen=Mock(return_value=None)
    op.interact_target=None
    op.had_been_list=[]
    child=Mock()
    child.execute.return_value=SimpleNamespace(success=True,status='已核验返回')
    factory=Mock(return_value=child)
    monkeypatch.setattr('zzz_od.application.hollow_zero.lost_void.operation.lost_void_run_level.LostVoidLottery',factory)
    assert op.handle_interact().result==R.WAIT
    factory.assert_called_once_with(op.ctx)
    child.execute.assert_called_once()


def test_lottery_reward_return_is_verified_from_current_controller_layout():
    op=operation(LostVoidChooseCommon)
    lottery_fixture(op)
    op._pad_confirm_requests=1
    op.return_screen_name='迷失之地-抽奖机'
    op.check_and_update_current_screen=Mock(return_value=None)
    assert op._choose_with_pad().is_success
    op.ctx.controller.btn_press.assert_not_called()


def test_lottery_result_returns_to_counted_start_without_legacy_match():
    op=operation(LostVoidLottery)
    lottery_fixture(op)
    op.check_and_update_current_screen=Mock(return_value=None)
    assert op.confirm_after_click().status==op.STATUS_CONTINUE
    op.ctx.controller.btn_press.assert_not_called()


def test_deploy_only_succeeds_after_acknowledged_departure():
    op=operation(Deploy)
    op._deploy_requests=0
    op.round_by_find_area=Mock(return_value=op.round_retry())
    assert op.deploy().result == R.RETRY
    op.ctx.controller.btn_press.assert_not_called()
    op.round_by_find_area.return_value=op.round_success()
    assert op.deploy().result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_start',press_time=.12)
    assert op.deploy().result == R.WAIT
    op.round_by_find_area.return_value=op.round_retry()
    assert op.deploy().is_success


def test_deploy_stops_when_delivery_never_changes_game():
    op=operation(Deploy)
    op._deploy_requests=5
    op.round_by_find_area=Mock(return_value=op.round_success())
    assert op.deploy().is_fail
    op.ctx.controller.btn_press.assert_not_called()


@pytest.mark.parametrize('tab,x', [('地图',390),('藏品',640),('属性',890)])
def test_panel_detects_active_background_instead_of_visible_label(tab,x):
    screen=np.zeros((1080,1920,3),np.uint8)
    screen[25:75,x-80:x+80]=(230,230,0)
    assert collection_tab(screen) == tab
    screen[25:75,310:470]=(230,230,0)
    if tab != '地图':
        assert collection_tab(screen) is None


def test_priority_switch_and_close_require_new_frame(monkeypatch):
    import zzz_od.application.hollow_zero.lost_void.operation.update_priority_operation as source
    op=operation(UpdatePriorityOperation)
    tab=Mock(return_value='地图')
    monkeypatch.setattr(source,'collection_tab',tab)
    assert op.enter_collections().result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_rb',press_time=.12)
    tab.return_value='藏品'
    assert op.enter_collections().is_success
    assert op.close_menu().result == R.WAIT
    op.ctx.lost_void.in_normal_world.return_value=True
    assert op.close_menu().is_success


def test_priority_opens_with_real_menu_action_mapping(monkeypatch):
    import zzz_od.application.hollow_zero.lost_void.operation.update_priority_operation as source
    op=operation(UpdatePriorityOperation)
    monkeypatch.setattr(source,'collection_tab',lambda _: None)
    op.ctx.lost_void.in_normal_world.return_value=True
    assert op.enter_collections().result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_back',press_time=.12)


def test_common_selection_follows_focus_and_waits_for_actual_exit(monkeypatch):
    import zzz_od.application.hollow_zero.lost_void.operation.interact.lost_void_choose_common as source
    op=operation(LostVoidChooseCommon)
    op._pad_target=None
    op._pad_confirm_requests=0
    op.to_choose_num=1
    op.check_and_update_current_screen=Mock(return_value='迷失之地-通用选择')
    item=SimpleNamespace(rect=Rect(1200,255,1530,760), can_choose=True, chosen=False,is_new=True,
        artifact=SimpleNamespace(display_name='新卡牌',level='S'),is_primary_name=True)
    op.get_artifact_pos=Mock(return_value=([item],[]))
    focus=Mock(return_value=Rect(790,255,1130,760))
    monkeypatch.setattr(source,'focused_card',focus)
    assert op.choose_artifact().result == R.WAIT
    assert op.ctx.controller.btn_press.call_args.args[0] == 'xbox_dpad_right'
    focus.return_value=item.rect
    assert op.choose_artifact().result == R.WAIT
    assert op.ctx.controller.btn_press.call_args.args[0] == 'xbox_a'
    assert op.ctx.lost_void.priority_updated
    op.ctx.lost_void.in_normal_world.return_value=True
    assert op.choose_artifact().is_success
    assert not op.ctx.lost_void.priority_updated
    op.ctx.controller.click.assert_not_called()


def test_common_never_confirms_when_focus_unknown(monkeypatch):
    import zzz_od.application.hollow_zero.lost_void.operation.interact.lost_void_choose_common as source
    op=operation(LostVoidChooseCommon)
    op._pad_target=SimpleNamespace(rect=Rect(1200,255,1530,760))
    op._pad_confirm_requests=0
    op.to_choose_num=1
    op.check_and_update_current_screen=Mock(return_value='迷失之地-通用选择')
    op.get_artifact_pos=Mock(return_value=([],[]))
    monkeypatch.setattr(source,'focused_card',lambda _:None)
    assert op.choose_artifact().result == R.WAIT
    op.ctx.controller.btn_press.assert_not_called()


def event_card_fixture():
    path = Path(__file__).parent / 'fixtures/lost_void/single_event_choice.png'
    image = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
    rows = json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
    matches = [SimpleNamespace(data=row['text'], center=Rect(row['rect'][0], row['rect'][1],
        row['rect'][0]+row['rect'][2], row['rect'][1]+row['rect'][3]).center) for row in rows]
    return image, matches


@pytest.mark.parametrize('missing', [None,'请选择1项','确定','放弃','Q HOLLOW','有回报的损失生命值','focus'])
def test_single_event_card_requires_page_structure_from_real_capture(missing):
    from zzz_od.application.hollow_zero.lost_void.mission_screen import single_event_choice
    image, rows = event_card_fixture()
    if missing == 'focus':
        image[:] = 0
    else:
        rows = [row for row in rows if row.data != missing]
    ctx = SimpleNamespace(ocr_service=SimpleNamespace(get_ocr_result_list=Mock(return_value=rows)))
    assert single_event_choice(ctx, image) == (missing is None)


def test_background_single_event_card_confirms_only_verified_selected_card_and_waits_for_exit():
    op = operation(LostVoidChooseCommon)
    image, rows = event_card_fixture()
    op.last_screenshot = image
    op.ctx.ocr_service = SimpleNamespace(get_ocr_result_list=Mock(return_value=rows))
    op.check_and_update_current_screen = Mock(return_value=None)
    op._pad_target, op._pad_confirm_requests = None, 0
    op.to_choose_num = 1
    item = SimpleNamespace(rect=Rect(788,255,1133,760),can_choose=False,chosen=True,is_new=False,
        artifact=SimpleNamespace(display_name='有回报的损失生命值',level='S'),is_primary_name=True)
    op.get_artifact_pos = Mock(return_value=([],[item]))
    assert op._choose_with_pad().result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_a',press_time=.12)
    op.ctx.controller.click.assert_not_called()
    op.ctx.lost_void.in_normal_world.return_value = True
    assert op._choose_with_pad().is_success
    op.ctx.controller.btn_press.assert_called_once()


def black_story_fixture():
    path = Path(__file__).parent / 'fixtures/lost_void/black_story_prompt.png'
    image = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
    data = json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
    rows = [SimpleNamespace(data=row['text'],center=Rect(row['rect'][0],row['rect'][1],
        row['rect'][0]+row['rect'][2],row['rect'][1]+row['rect'][3]).center) for row in data]
    template = cv2.cvtColor(cv2.imread(str(Path(__file__).parents[1]/'assets/template/lost_void/story_confirm_xbox/raw.png')),cv2.COLOR_BGR2RGB)
    return image, rows, template


@pytest.mark.parametrize('missing', [None,'caption','prompt','black_background'])
def test_black_story_requires_caption_and_confirm_prompt_in_black_scene(missing):
    from zzz_od.application.hollow_zero.lost_void.mission_screen import black_story_caption
    image, rows, template = black_story_fixture()
    if missing == 'caption':
        rows = []
    elif missing == 'prompt':
        image[545:640,900:1020] = 0
    elif missing == 'black_background':
        image[:400] = 255
    ctx = SimpleNamespace(ocr_service=SimpleNamespace(get_ocr_result_list=lambda **_:rows),
        template_loader=SimpleNamespace(get_template=lambda *_:SimpleNamespace(raw=template)))
    assert bool(black_story_caption(ctx,image)) == (missing is None)


@pytest.mark.parametrize('gamepad,key', [('xbox','xbox_a'),('ds4','ds4_cross')])
def test_background_black_story_confirmation_is_bounded_and_never_clicks(gamepad,key):
    op = operation(LostVoidRunLevel)
    image, rows, template = black_story_fixture()
    op.last_screenshot = image
    op.ctx.game_config.background_gamepad_type = gamepad
    op.ctx.ocr_service = SimpleNamespace(get_ocr_result_list=lambda **_:rows)
    op.ctx.template_loader = SimpleNamespace(get_template=lambda *_:SimpleNamespace(raw=template))
    op.ctx.screen_loader = SimpleNamespace(get_area=lambda *_:SimpleNamespace(rect=Rect(520,245,1365,770)))
    op.check_and_update_current_screen = Mock(return_value=None)
    op.try_talk = Mock(return_value=None)
    for _ in range(3):
        assert op.handle_interact().status == '确认已核验的黑底事件叙述，等待画面变化'
    assert op.handle_interact().is_fail
    assert op.ctx.controller.btn_press.call_count == 3
    assert all(call.args == (key,) for call in op.ctx.controller.btn_press.call_args_list)
    op.ctx.controller.click.assert_not_called()


def test_background_loading_black_screen_without_story_prompt_sends_no_input():
    op = operation(LostVoidRunLevel)
    op.ctx.screen_loader = SimpleNamespace(get_area=lambda *_:SimpleNamespace(rect=Rect(520,245,1365,770)))
    op.check_and_update_current_screen = Mock(return_value=None)
    op.try_talk = Mock(return_value=None)
    assert op.handle_interact().status == '等待黑屏加载结束，未操作'
    op.ctx.controller.btn_press.assert_not_called()
    op.ctx.controller.click.assert_not_called()


def test_black_story_resume_routes_loading_to_interaction_without_input():
    op = operation(LostVoidRunLevel)
    image, rows, template = black_story_fixture()
    op.last_screenshot = image
    op.ctx.ocr_service = SimpleNamespace(get_ocr_result_list=lambda **_:rows)
    op.ctx.template_loader = SimpleNamespace(get_template=lambda *_:SimpleNamespace(raw=template))
    op.check_and_update_current_screen = Mock(return_value=None)
    assert op.wait_loading().status == '识别正在交互'
    op.ctx.controller.btn_press.assert_not_called()


def test_app_resumes_black_story_instead_of_transporting_to_another_screen():
    from zzz_od.application.hollow_zero.lost_void.lost_void_app import LostVoidApp
    op = operation(LostVoidApp)
    image, rows, template = black_story_fixture()
    op.last_screenshot = image
    op.config = SimpleNamespace(mission_name='特遣调查')
    op.lost_void_debug = False
    op._entry_header = Mock(return_value=None)
    op.round_by_find_area = Mock(return_value=op.round_retry())
    op.ctx.ocr_service = SimpleNamespace(get_ocr_result_list=lambda **_:rows)
    op.ctx.template_loader = SimpleNamespace(get_template=lambda *_:SimpleNamespace(raw=template))
    assert op.check_initial_screen().status == '迷失之地-大世界'
    op.ctx.controller.btn_press.assert_not_called()


def test_slow_return_loading_never_increments_count_before_verified_entrance():
    from zzz_od.application.hollow_zero.lost_void.lost_void_app import LostVoidApp
    op = operation(LostVoidApp)
    op.use_priority_agent = False
    op.run_record = SimpleNamespace(add_complete_times=Mock())
    op._wait_for_lost_void_entry = Mock(side_effect=[op.round_wait('等待画面加载')]*3 + [op.round_success('迷失之地-入口-周期')])
    for _ in range(3):
        assert op.after_complete().result == R.WAIT
        op.run_record.add_complete_times.assert_not_called()
    assert op.after_complete().is_success
    op.run_record.add_complete_times.assert_called_once()


def test_multi_selection_requires_count_ack_and_submits_with_x(monkeypatch):
    import zzz_od.application.hollow_zero.lost_void.operation.interact.lost_void_choose_common as source
    op = operation(LostVoidChooseCommon)
    op._pad_target = None
    op._pad_confirm_requests = 0
    op.to_choose_num = 2
    items = [SimpleNamespace(rect=Rect(x,255,x+330,760),can_choose=True,chosen=False,is_new=True,
        artifact=SimpleNamespace(display_name=str(x),level='S'),is_primary_name=True) for x in (180,600)]
    focus = Mock(return_value=items[0].rect)
    monkeypatch.setattr(source,'focused_card',focus)
    count = Mock(return_value=None)
    op._get_chosen_count_from_confirm_button = count
    assert op._choose_multiple_with_pad(op.last_screenshot,items,[]).result == R.WAIT
    op.ctx.controller.btn_press.assert_not_called()
    count.return_value=0
    assert op._choose_multiple_with_pad(op.last_screenshot,items,[]).result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_a',press_time=.12)
    assert op._choose_multiple_with_pad(op.last_screenshot,items,[]).result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once()
    count.return_value=1
    assert op._choose_multiple_with_pad(op.last_screenshot,items,[]).result == R.WAIT
    assert op.ctx.controller.btn_press.call_args.args[0] == 'xbox_dpad_right'
    focus.return_value=items[1].rect
    assert op._choose_multiple_with_pad(op.last_screenshot,items,[]).result == R.WAIT
    assert op.ctx.controller.btn_press.call_args.args[0] == 'xbox_a'
    count.return_value=2
    assert op._choose_multiple_with_pad(op.last_screenshot,items,[]).result == R.WAIT
    assert op.ctx.controller.btn_press.call_args.args[0] == 'xbox_x'
    op.ctx.controller.click.assert_not_called()


def test_multi_selection_never_toggles_again_when_count_does_not_increase(monkeypatch):
    op = operation(LostVoidChooseCommon)
    op._pad_pending_selection=('卡牌',0)
    op.to_choose_num=2
    op._get_chosen_count_from_confirm_button=Mock(return_value=0)
    for _ in range(3):
        assert op._choose_multiple_with_pad(op.last_screenshot,[],[]).result == R.WAIT
    assert op._choose_multiple_with_pad(op.last_screenshot,[],[]).is_fail
    op.ctx.controller.btn_press.assert_not_called()


def test_multi_focus_excludes_retained_selected_border():
    screen=cv2.cvtColor(cv2.imread(str(Path(__file__).parent/'fixtures/lost_void/multi_selected_and_focused.png')),cv2.COLOR_BGR2RGB)
    assert focused_card(screen).center.x == 756  # Bright focus is distinct from the retained dark border.
    focus=focused_card(screen,excluded_centers=[350])
    assert 730 < focus.center.x < 780


def test_single_selected_card_confirms_without_guessing_filled_green_focus(monkeypatch):
    import zzz_od.application.hollow_zero.lost_void.operation.interact.lost_void_choose_common as source
    op=operation(LostVoidChooseCommon)
    op._pad_target=None
    op._pad_confirm_requests=1
    op.check_and_update_current_screen=Mock(return_value='迷失之地-通用选择')
    item=SimpleNamespace(rect=Rect(790,255,1130,760),chosen=True,
        artifact=SimpleNamespace(display_name='已选卡牌'))
    op.get_artifact_pos=Mock(return_value=([],[item]))
    monkeypatch.setattr(source,'focused_card',lambda _:None)
    assert op.choose_artifact().result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_a',press_time=.12)
    op.ctx.controller.click.assert_not_called()


def test_prism_branch_uses_visible_full_count_without_selected_label(monkeypatch):
    op=operation(LostVoidChooseCommon)
    op.to_choose_gear_branch=True
    op._pad_target=None
    op._pad_confirm_requests=0
    op.check_and_update_current_screen=Mock(return_value='迷失之地-通用选择')
    op.get_artifact_pos=Mock(return_value=([],[]))
    op._get_chosen_count_from_confirm_button=Mock(return_value=1)
    assert op.choose_artifact().result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_a',press_time=.12)


def test_store_purchase_requires_real_balance_change():
    op=operation(LostVoidBangbooStore)
    op.store_type='标识-金币'
    op.ctx.lost_void.challenge_config.store_gold=True
    op._pad_purchase={'name':'商品','balance':1000,'confirms':0,'waits':0}
    op.check_and_update_current_screen=Mock(return_value='迷失之地-邦布商店')
    op.round_by_find_area=Mock(return_value=op.round_retry())
    op._gold_balance=Mock(return_value=1000)
    assert op.buy_artifact_gold().result == R.WAIT
    assert op._pad_purchase is not None
    op.ctx.controller.btn_press.assert_not_called()
    op._gold_balance.return_value=400
    assert op.buy_artifact_gold().result == R.WAIT
    assert op._pad_purchase is None
    assert not op.ctx.lost_void.priority_updated


def test_store_purchase_never_repeats_unacknowledged_buy():
    op=operation(LostVoidBangbooStore)
    op.store_type='标识-金币'
    op.ctx.lost_void.challenge_config.store_gold=True
    op._pad_purchase={'name':'商品','balance':1000,'confirms':0,'waits':4}
    op.check_and_update_current_screen=Mock(return_value='迷失之地-邦布商店')
    op.round_by_find_area=Mock(return_value=op.round_retry())
    op._gold_balance=Mock(return_value=1000)
    assert op.buy_artifact_gold().is_fail
    op.ctx.controller.btn_press.assert_not_called()


def test_store_back_requires_known_menu_then_actual_departure():
    op=operation(LostVoidBangbooStore)
    op.check_and_update_current_screen=Mock(return_value=None)
    assert op.finish().result == R.RETRY
    op.ctx.controller.btn_press.assert_not_called()
    op.check_and_update_current_screen.return_value='迷失之地-邦布商店'
    assert op.finish().result == R.WAIT
    assert op.finish().result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_b',press_time=.12)
    op.check_and_update_current_screen.return_value=None
    assert op.finish().is_success


def test_failed_grade_recognizes_x_without_confusing_regular_card():
    raw=cv2.cvtColor(cv2.imread(str(Path(__file__).parents[1]/'assets/template/lost_void/failed_grade/raw.png')),cv2.COLOR_BGR2RGB)
    ctx=SimpleNamespace(template_loader=SimpleNamespace(get_template=lambda *_: SimpleNamespace(raw=raw)))
    screen=np.zeros((1080,1920,3),np.uint8)
    screen[345:800,690:1250]=raw
    assert failed_grade(ctx,screen)
    fade=cv2.cvtColor(cv2.imread(str(Path(__file__).parent/'fixtures/lost_void/failed_grade_fade.png')),cv2.COLOR_BGR2RGB)
    assert failed_grade(ctx,fade)
    card=cv2.cvtColor(cv2.imread(str(Path(__file__).parent/'fixtures/lost_void/green_quality_card_focus.png')),cv2.COLOR_BGR2RGB)
    assert not failed_grade(ctx,card)


def test_failed_grade_recognizes_rotated_x_from_latest_live_failure():
    templates={}
    for name in ('failed_grade','failed_grade_alt','failed_grade_front'):
        path=Path(__file__).parents[1]/f'assets/template/lost_void/{name}/raw.png'
        templates[name]=SimpleNamespace(raw=cv2.cvtColor(cv2.imread(str(path)),cv2.COLOR_BGR2RGB))
    ctx=SimpleNamespace(template_loader=SimpleNamespace(get_template=lambda _group,name: templates[name]))
    path=Path(__file__).parent/'fixtures/lost_void/failed_grade_rotated.png'
    screen=cv2.cvtColor(cv2.imread(str(path)),cv2.COLOR_BGR2RGB)
    assert failed_grade(ctx,screen)


@pytest.mark.parametrize('fixture', ['failed_grade_fade', 'failed_grade_rotated', 'failed_grade_front'])
@pytest.mark.parametrize('brightness', [1, .6])
def test_actual_failed_settlement_views_and_fade_are_not_a_clear(fixture,brightness):
    from zzz_od.application.hollow_zero.lost_void import mission_screen as source
    templates={name:SimpleNamespace(raw=cv2.cvtColor(cv2.imread(str(
        Path(__file__).parents[1]/f'assets/template/lost_void/{name}/raw.png')),cv2.COLOR_BGR2RGB))
        for name in ('failed_grade','failed_grade_alt','failed_grade_front')}
    ctx=SimpleNamespace(template_loader=SimpleNamespace(get_template=lambda _,name:templates[name]))
    image=cv2.cvtColor(cv2.imread(str(Path(__file__).parent/f'fixtures/lost_void/{fixture}.png')),cv2.COLOR_BGR2RGB)
    image=(image.astype(float)*brightness).astype(np.uint8)
    assert source.failed_grade(ctx,image)
    op=operation(LostVoidRunLevel)
    op.ctx.template_loader=ctx.template_loader
    op.last_screenshot=image
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=lambda **_: [
        SimpleNamespace(data='挑战结果',center=SimpleNamespace(y=210)),
        SimpleNamespace(data='完成',center=SimpleNamespace(y=1000))])
    assert op.wait_loading().status == '挑战失败结算'
    op._background_result_ack=Mock(return_value=op.round_success())
    assert op.handle_fail_exit().is_fail
    assert '不计入通关次数' in op.handle_fail_exit().status


def exit_operation():
    op=operation(ExitInBattle)
    op.wait_screen_name='迷失之地-挑战结果'
    op.wait_area_name='按钮-完成'
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=lambda **_: [])
    op.ctx.auto_battle_context=SimpleNamespace(is_normal_attack_btn_available=Mock(return_value=False))
    return op


def test_exit_closes_actual_map_and_waits_before_opening_pause():
    op=exit_operation()
    op.last_screenshot[25:75,310:470]=(230,230,0)
    for _ in range(3):
        assert op.check_screen().result == R.RETRY
    assert op.check_screen().is_fail
    assert op.ctx.controller.btn_press.call_count == 3
    assert all(call.args == ('xbox_b',) for call in op.ctx.controller.btn_press.call_args_list)
    op.last_screenshot[:]=0
    op.ctx.auto_battle_context.is_normal_attack_btn_available.return_value=True
    for _ in range(3):
        assert op.check_screen().result == R.RETRY
    assert op.ctx.controller.btn_press.call_args.args == ('xbox_start',)
    assert op.ctx.controller.btn_press.call_count == 4


def test_exit_unknown_screen_sends_no_inputs():
    op=exit_operation()
    assert op.check_screen().result == R.RETRY
    op.ctx.controller.btn_press.assert_not_called()


@pytest.mark.parametrize('pad,key',[('xbox','xbox_y'),('ds4','ds4_triangle')])
def test_exit_uses_verified_footer_exit_key_and_requires_popup(pad,key):
    op=exit_operation()
    op.ctx.game_config.background_gamepad_type=pad
    op._menu_texts=lambda: {'重新开始','退出战斗'}
    op.round_by_find_area=Mock(return_value=op.round_retry())
    assert op.check_screen().is_success
    assert op.click_exit_battle().result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with(key,press_time=.12)
    op.round_by_find_area.return_value=op.round_success()
    assert op.click_exit_battle().is_success
    assert op.ctx.controller.btn_press.call_count == 1


def test_exit_confirmation_verifies_focus_and_departure():
    op=exit_operation()
    op.round_by_find_area=Mock(return_value=op.round_success())
    assert op.click_confirm().result == R.RETRY
    op.ctx.controller.btn_press.assert_not_called()
    op.last_screenshot[607:650,700:900]=(255,230,0)
    assert op.click_confirm().result == R.WAIT
    assert op.ctx.controller.btn_press.call_args.args == ('xbox_dpad_right',)
    op.last_screenshot[:]=0
    op.last_screenshot[607:650,1038:1224]=(255,230,0)
    assert op.click_confirm().result == R.WAIT
    assert op.ctx.controller.btn_press.call_args.args == ('xbox_a',)
    assert op.click_confirm().result == R.RETRY
    assert op.ctx.controller.btn_press.call_count == 2
    op.round_by_find_area.return_value=op.round_retry()
    assert op.click_confirm().is_success


def test_exit_recognizes_already_visible_actual_settlement_and_waits_for_it():
    op=exit_operation()
    assert op.wait_at_last().result == R.RETRY
    op.ctx.ocr_service.get_ocr_result_list=lambda **_: [
        SimpleNamespace(data='挑战结果',center=SimpleNamespace(y=210)),
        SimpleNamespace(data='完成',center=SimpleNamespace(y=1000))]
    assert op.check_screen().status == '已到达退出结算'
    assert op.wait_at_last().is_success
    op.ctx.controller.btn_press.assert_not_called()


def test_save_background_failure_does_not_open_map():
    op=operation(LostVoidRunLevel)
    op.ctx.auto_battle_context=SimpleNamespace(stop_auto_battle=Mock())
    op._previous_node=SimpleNamespace(cn='处理寻路失败或阵亡')
    op._previous_round_result=op.round_success('准备最终退出')
    op.save_screenshot=Mock()
    op.round_by_find_and_click_area=Mock()
    assert op.push_error().is_fail
    op.round_by_find_and_click_area.assert_not_called()
    op.save_screenshot.assert_called_once_with(prefix='lost_void_failure')


@pytest.mark.parametrize('header,body,expected', [
    ('悬赏委托完成进度2500/2500周期常规','矩阵行动','迷失之地-入口-周期'),
    ('悬赏委托完成进度2500/2500周期常规','战线肃清特遣调查','迷失之地-入口-常规'),
    ('周期常规','矩阵行动',None)])
def test_result_return_recognizes_gamepad_entry_header_with_two_independent_markers(monkeypatch,header,body,expected):
    from zzz_od.application.hollow_zero.lost_void.lost_void_app import LostVoidApp
    import zzz_od.application.hollow_zero.lost_void.lost_void_app as source
    op=operation(LostVoidApp)
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=Mock(side_effect=[
        [SimpleNamespace(data=header)],[SimpleNamespace(data=body)]]))
    monkeypatch.setattr(source,'menu_matches',lambda *_: {})
    op.round_by_find_and_click_area=Mock(return_value=op.round_retry())
    op.check_and_update_current_screen=Mock(return_value=None)
    result=op._wait_for_lost_void_entry()
    assert result.is_success == (expected is not None)
    if expected:
        assert result.status == expected


def test_initial_cycle_entry_routes_through_bounty_check_without_transport():
    from zzz_od.application.hollow_zero.lost_void.lost_void_app import LostVoidApp
    op=operation(LostVoidApp)
    op.lost_void_debug=False
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=Mock(return_value=[]))
    op.round_by_find_area=Mock(return_value=op.round_retry())
    op._entry_header=Mock(return_value='迷失之地-入口-周期')
    op.check_screen_with_can_go=Mock()
    assert op.check_initial_screen().status == '已在迷失之地入口'
    op.check_screen_with_can_go.assert_not_called()
    op.ctx.controller.btn_press.assert_not_called()


def test_cycle_to_regular_switch_waits_for_new_frame_and_bounds_requests(monkeypatch):
    import zzz_od.application.hollow_zero.lost_void.lost_void_app as source
    op=operation(source.LostVoidApp)
    op.config=SimpleNamespace(mission_name='特遣调查')
    op._entry_header=Mock(return_value='迷失之地-入口-周期')
    monkeypatch.setattr(source,'detail_mission',lambda *_: None)
    for _ in range(3):
        assert op.goto_mission_screen().result == R.WAIT
    assert op.goto_mission_screen().is_fail
    assert op.ctx.controller.btn_press.call_count == 3
    assert all(call.args == ('xbox_rb',) for call in op.ctx.controller.btn_press.call_args_list)
    op.ctx.controller.click.assert_not_called()


def test_failed_result_exits_with_b_and_never_reports_complete(monkeypatch):
    import zzz_od.application.hollow_zero.lost_void.operation.lost_void_run_level as source
    op=operation(LostVoidRunLevel)
    result=Mock(return_value='完成')
    monkeypatch.setattr(source,'battle_result',result)
    grade=Mock(return_value=True)
    monkeypatch.setattr(source,'failed_grade',grade)
    assert op.handle_challenge_result_finish().result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_b',press_time=.12)
    result.return_value=None
    grade.return_value=False
    op.ctx.lost_void.in_normal_world.return_value=True
    outcome=op.handle_challenge_result_finish()
    assert outcome.is_fail
    assert '不计入通关次数' in outcome.status


def test_loading_routes_failed_summary_to_failure_cleanup(monkeypatch):
    import zzz_od.application.hollow_zero.lost_void.operation.lost_void_run_level as source
    op=operation(LostVoidRunLevel)
    monkeypatch.setattr(source,'battle_result',lambda *_:'完成')
    monkeypatch.setattr(source,'failed_grade',lambda *_:True)
    assert op.wait_loading().status == '挑战失败结算'
    op.ctx.controller.btn_press.assert_not_called()


def test_gear_focus_requires_ring_and_rejects_ambiguous_highlights():
    screen=np.zeros((1080,1920,3),np.uint8)
    cv2.circle(screen,(275,990),65,(240,240,0),7)
    assert focused_gear(screen).center.x == 275
    screen[935:1040,220:250]=0  # 图标遮挡导致外框分成多个轮廓，仍能核验同一槽位。
    assert abs(focused_gear(screen).center.x-275) < 3
    cv2.circle(screen,(450,990),65,(240,240,0),7)
    assert focused_gear(screen) is None


def test_equipped_name_must_match_actual_top_slot(monkeypatch):
    import zzz_od.application.hollow_zero.lost_void.operation.interact.lost_void_choose_gear as source
    monkeypatch.setattr(source, 'focused_gear', lambda _: Rect(200, 900, 340, 1040))
    op=operation(LostVoidChooseGear)
    op._gear_availability=Mock(return_value={'usable':True,'unlock':False})
    op._pad_scan={'chosen':SimpleNamespace(ocr_text='[角色]目标武备')}
    op._equip_requests=0
    op._equip_confirmed=False
    matches=Mock(return_value=[SimpleNamespace(data='EMPTY',center=SimpleNamespace(x=960))])
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=matches)
    op.round_by_find_area=Mock(return_value=op.round_success())
    assert op.click_equip().result == R.WAIT
    assert not op._equip_confirmed
    assert op.ctx.lost_void.priority_updated
    matches.return_value=[SimpleNamespace(data='【角色】目标 武备',center=SimpleNamespace(x=960))]
    assert op.click_equip().is_success
    assert op._equip_confirmed
    assert not op.ctx.lost_void.priority_updated


def test_gear_cleanup_does_not_hide_selection_failure():
    op=operation(LostVoidChooseGear)
    op._equip_confirmed=False
    op.ctx.lost_void.in_normal_world.return_value=True
    assert op.click_back().is_fail
    op._equip_confirmed=True
    assert op.click_back().is_success


def test_equipped_name_ignores_preview_level_line():
    op=operation(LostVoidChooseGear)
    op._pad_scan={'chosen':SimpleNamespace(ocr_text='等级1：【绝境】战斗维生包',
        artifact=SimpleNamespace(display_name='[绝境]战斗维生包', category='绝境'))}
    op._equip_requests=1
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=lambda **_: [
        SimpleNamespace(data='[绝境]战斗维生包',center=SimpleNamespace(x=960))])
    assert op.click_equip().is_success
    assert op._equip_confirmed
    op.ctx.controller.btn_press.assert_not_called()


@pytest.mark.parametrize('header,accepted',[('[攜游]救令玄幡',True),('[携游]敕令玄幡',True),('[携游]虚空霓虹',False)])
def test_equipped_header_font_variants_preserve_gear_identity(header,accepted):
    op=operation(LostVoidChooseGear)
    op._pad_scan={'chosen':SimpleNamespace(ocr_text='[携游]敕令玄幡',artifact=SimpleNamespace(display_name='[携游]敕令玄幡',category='携游'))}
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=lambda **_:[SimpleNamespace(data=header,center=SimpleNamespace(x=960))])
    op._gear_availability=Mock(return_value=None)
    op._equip_requests=0
    assert op.click_equip().is_success is accepted
    op.ctx.controller.btn_press.assert_not_called()


def test_real_dark_gear_card_with_protruding_icon_has_correct_focus():
    path=Path(__file__).parent/'fixtures/lost_void/dark_gear_card_focus.png'
    screen=cv2.cvtColor(cv2.imread(str(path)),cv2.COLOR_BGR2RGB)
    focus=focused_card(screen)
    assert focus is not None and focus.x1 == 993 and focus.x2 == 1315


def test_real_locked_gear_is_excluded_when_resources_are_insufficient():
    op=operation(LostVoidChooseGear)
    path=Path(__file__).parent/'fixtures/lost_void/locked_gear_insufficient_resources.png'
    op.last_screenshot=cv2.cvtColor(cv2.imread(str(path)),cv2.COLOR_BGR2RGB)
    focus=focused_gear(op.last_screenshot)
    assert focus is not None and focus.center.x > 1600
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=Mock(side_effect=[
        [SimpleNamespace(data='解锁')], [SimpleNamespace(data='00000100')], [SimpleNamespace(data='150')]]))
    assert op._gear_availability(focus) == {'usable':False, 'unlock':True, 'balance':100, 'cost':150}
    op.ctx.controller.btn_press.assert_not_called()


def test_gear_priority_cannot_choose_unaffordable_new_item():
    op=operation(LostVoidChooseGear)
    available=SimpleNamespace(artifact=SimpleNamespace(display_name='[机敏]机敏蓄能盾'),rect=Rect(100,900,240,1040))
    locked=SimpleNamespace(artifact=SimpleNamespace(display_name='[绝境]浩劫令牌'),rect=Rect(300,900,440,1040))
    op.ctx.lost_void.challenge_config.chase_new_mode=True
    op._pad_scan={'gears':[available,locked], 'levels':[True,False],
                  'availability':[{'usable':True},{'usable':False}]}
    assert op._select_usable_gear().result == R.WAIT
    assert op._pad_scan['chosen'] is available
    assert op.ctx.lost_void.challenge_config.artifact_priority_in_battle == []


@pytest.mark.parametrize('gamepad,key', [('xbox','xbox_y'),('ds4','ds4_triangle')])
def test_affordable_locked_gear_unlocks_before_equipping(monkeypatch,gamepad,key):
    import zzz_od.application.hollow_zero.lost_void.operation.interact.lost_void_choose_gear as source
    monkeypatch.setattr(source, 'focused_gear', lambda _: Rect(200,900,340,1040))
    op=operation(LostVoidChooseGear)
    op.ctx.game_config.background_gamepad_type=gamepad
    op._pad_scan={'chosen':SimpleNamespace(ocr_text='[绝境]浩劫令牌')}
    op._equip_requests=op._unlock_requests=0
    op._equip_confirmed=False
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=lambda **_: [SimpleNamespace(data='EMPTY',center=SimpleNamespace(x=960))])
    op._gear_availability=Mock(return_value={'usable':True,'unlock':True,'cost':100,'balance':100})
    assert op.click_equip().result == R.WAIT
    assert op._equip_requests == 0 and not op._equip_confirmed
    op.ctx.controller.btn_press.assert_called_once_with(key,press_time=.12)
    op._gear_availability.return_value={'usable':True,'unlock':False}
    op.round_by_find_area=Mock(return_value=op.round_success())
    assert op.click_equip().result == R.WAIT
    assert op._equip_requests == 1
    assert op.ctx.controller.btn_press.call_args.args == ('ds4_cross' if gamepad=='ds4' else 'xbox_a',)


def test_unknown_unlock_price_is_not_treated_as_free():
    op=operation(LostVoidChooseGear)
    op._gear_button_enabled=Mock(return_value=False)
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=Mock(side_effect=[
        [SimpleNamespace(data='解锁')],[SimpleNamespace(data='100')],[]]))
    assert not op._gear_availability(Rect(200,900,340,1040))['usable']


def test_real_highlighted_locked_gear_does_not_create_duplicate_slot():
    path=Path(__file__).parent/'fixtures/lost_void/locked_gear_insufficient_resources.png'
    screen=cv2.imread(str(path))
    hsv=cv2.cvtColor(screen[892:1072,190:1740],cv2.COLOR_BGR2HSV)
    mask=cv2.inRange(hsv,np.array([0,0,75]),np.array([180,255,255]))
    mask=cv2.dilate(mask,np.ones((3,3),np.uint8),iterations=2)
    contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    pairs=[(c,(x+190,y+892,x+190+w,y+892+h)) for c in contours
           if 2000<=cv2.contourArea(c)<=100000 for x,y,w,h in [cv2.boundingRect(c)]]
    assert len(pairs) == 11
    slots=LostVoidChooseGear._gear_rect_pairs(SimpleNamespace(get_absolute_rect_pairs=lambda:pairs))
    assert len(slots) == 10
    assert sum(Rect(*p[1]).center.x>1600 for p in slots) == 1


def test_live_gear_artwork_between_slots_is_not_a_navigation_target(ctx):
    # Recorded opening frame: a protruding illustration formed an extra
    # contour between the sixth and seventh selectable circular gears.
    strip=cv2.cvtColor(cv2.imread(str(Path(__file__).parent/'fixtures/lost_void/gear_artwork_between_slots.png')),cv2.COLOR_BGR2RGB)
    screen=np.zeros((1080,1920,3),np.uint8)
    screen[892:1072,190:1740]=strip
    result=ctx.cv_service.run_pipeline('迷失之地-武备列表检测',screen)
    assert len(result.get_absolute_rect_pairs()) == 10
    slots=LostVoidChooseGear._gear_rect_pairs(result)
    assert len(slots) == 9
    assert not any(1160 < Rect(*pair[1]).center.x < 1210 for pair in slots)


def test_already_equipped_gear_with_disabled_button_remains_valid():
    op=operation(LostVoidChooseGear)
    path=Path(__file__).parent/'fixtures/lost_void/already_equipped_gear.png'
    op.last_screenshot=cv2.cvtColor(cv2.imread(str(path)),cv2.COLOR_BGR2RGB)
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=Mock(side_effect=[[],[
        SimpleNamespace(data='【携游】敕令玄幡',center=SimpleNamespace(x=960))]]))
    result=op._gear_availability(focused_gear(op.last_screenshot),'[携游]敕令玄幡')
    assert result == {'usable':True,'unlock':False,'equipped':True}
    op.ctx.controller.btn_press.assert_not_called()


@pytest.mark.parametrize('confirmed',[False,True])
def test_gear_branch_returning_to_shop_requires_prior_confirmation(monkeypatch,confirmed):
    import zzz_od.application.hollow_zero.lost_void.operation.interact.lost_void_choose_common as source
    monkeypatch.setattr(source,'battle_result',lambda *_:None)
    op=operation(LostVoidChooseCommon)
    op._pad_confirm_requests=int(confirmed)
    op.check_and_update_current_screen=Mock(return_value='迷失之地-邦布商店')
    result=op._choose_with_pad()
    assert result.is_success == confirmed
    op.ctx.controller.btn_press.assert_not_called()


def test_green_quality_background_does_not_become_selection_focus():
    path=Path(__file__).parent/'fixtures/lost_void/green_quality_card_focus.png'
    screen=cv2.cvtColor(cv2.imread(str(path)),cv2.COLOR_BGR2RGB)
    focus=focused_card(screen)
    assert focus is not None and focus.center.x == 959


def test_filled_green_multi_choice_card_with_yellow_rim_is_focus():
    path=Path(__file__).parent/'fixtures/lost_void/green_multi_card_focus.png'
    screen=cv2.cvtColor(cv2.imread(str(path)),cv2.COLOR_BGR2RGB)
    focus=focused_card(screen)
    assert focus is not None and 740 < focus.center.x < 780


def test_consecutive_rewards_acknowledge_real_option_change():
    op=operation(LostVoidChooseCommon)
    op._pad_confirm_requests=1
    op._pad_options={'旧武备甲','旧武备乙'}
    op.check_and_update_current_screen=Mock(return_value='迷失之地-通用选择')
    op.get_artifact_pos=Mock(return_value=([SimpleNamespace(artifact=SimpleNamespace(display_name=name)) for name in ('新鸣徽甲','新鸣徽乙')],[]))
    assert op.choose_artifact().is_success
    assert not op.ctx.lost_void.priority_updated
    op.ctx.controller.btn_press.assert_not_called()


def test_multiple_selection_followed_by_focused_single_card_ends_previous_operation():
    op=operation(LostVoidChooseCommon)
    op._pad_confirm_requests=1
    op._pad_options={'[通用]三相战斗陀螺','[通用]三枚玻璃弹珠'}
    op.check_and_update_current_screen=Mock(return_value='迷失之地-通用选择')
    op.get_artifact_pos=Mock(return_value=([],[SimpleNamespace(artifact=SimpleNamespace(display_name='恶害追打之印'))]))
    path=Path(__file__).parent/'fixtures/lost_void/single_card_after_multi.png'
    op.last_screenshot=cv2.cvtColor(cv2.imread(str(path)),cv2.COLOR_BGR2RGB)
    assert op.choose_artifact().is_success
    op.ctx.controller.btn_press.assert_not_called()


def test_one_unknown_option_without_card_focus_does_not_end_previous_selection():
    op=operation(LostVoidChooseCommon)
    op._pad_confirm_requests=1
    op._pad_options={'旧鸣徽甲','旧鸣徽乙'}
    op._pad_target=None
    op.check_and_update_current_screen=Mock(return_value='迷失之地-通用选择')
    op.get_artifact_pos=Mock(return_value=([],[SimpleNamespace(artifact=SimpleNamespace(display_name='新单卡'))]))
    assert op.choose_artifact().result == R.WAIT
    assert op._pad_confirm_requests == 2


@pytest.mark.parametrize('missing', [None,'CARD','名称','确定'])
def test_untitled_card_reward_requires_three_visible_identifiers(missing):
    op=operation(LostVoidChooseCommon)
    values=[('CARD',260),('名称',520),('确定',795)]
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=lambda **_: [
        SimpleNamespace(data=name,center=SimpleNamespace(y=y)) for name,y in values if name != missing])
    assert op._is_single_card_reward(op.last_screenshot) == (missing is None)


def test_unknown_title_does_not_trigger_confirmation():
    op=operation(LostVoidChooseCommon)
    op._pad_confirm_requests=0
    op.to_choose_num=0
    op.check_and_update_current_screen=Mock(return_value='迷失之地-通用选择')
    op.get_artifact_pos=Mock(return_value=([],[]))
    op._is_single_card_reward=Mock(return_value=False)
    assert op.choose_artifact().result == R.RETRY
    op.ctx.controller.btn_press.assert_not_called()


def reward_rows(name='[机敏]防护安全带', quantity='01', confirm=True):
    values=[(name,534),(quantity,714)]
    if confirm:
        values.append(('确定',844))
    return [SimpleNamespace(data=text,center=SimpleNamespace(y=y)) for text,y in values]


def reward_operation():
    op=operation(LostVoidChooseCommon)
    op.to_choose_num=0
    op.to_choose_artifact=True
    op._pad_confirm_requests=2
    op._pad_target=None
    op.check_and_update_current_screen=Mock(return_value='迷失之地-通用选择')
    op.get_artifact_pos=Mock(return_value=([],[]))
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=Mock(return_value=reward_rows()))
    return op


def test_bundle_reward_retries_reset_only_on_verified_card_or_quantity_change():
    op=reward_operation()
    assert op.choose_artifact().result == R.WAIT
    assert op._pad_confirm_requests == 1
    for index in range(5):
        op.ctx.ocr_service.get_ocr_result_list.return_value=reward_rows(name='鸣徽'+str(index))
        assert op.choose_artifact().result == R.WAIT
        assert op._pad_confirm_requests == 1
    op.ctx.ocr_service.get_ocr_result_list.return_value=reward_rows(name='鸣徽4',quantity='02')
    assert op.choose_artifact().result == R.WAIT
    assert op._pad_confirm_requests == 1


def test_same_reward_still_has_bounded_confirmation_attempts():
    op=reward_operation()
    for _ in range(5):
        assert op.choose_artifact().result == R.WAIT
    assert op.choose_artifact().is_fail
    assert op.ctx.controller.btn_press.call_count == 5


@pytest.mark.parametrize('names,confirm', [('',True),('[机敏]防护安全带',False)])
def test_incomplete_reward_page_does_not_reset_retry_limit(names,confirm):
    op=reward_operation()
    op._pad_confirm_requests=3
    op.ctx.ocr_service.get_ocr_result_list.return_value=reward_rows(names,confirm=confirm)
    assert op.choose_artifact().is_fail
    op.ctx.controller.btn_press.assert_not_called()


def test_real_bundled_reward_names_and_confirmation_produce_stable_signature():
    import json
    op=reward_operation()
    data=json.loads((Path(__file__).parent/'fixtures/lost_void/bundled_reward.json').read_text(encoding='utf-8'))
    op.ctx.ocr_service.get_ocr_result_list.return_value=[SimpleNamespace(data=row['text'],
        center=SimpleNamespace(y=row['rect'][1]+row['rect'][3]/2)) for row in data['result']['ocr']]
    assert op._reward_page_signature(op.last_screenshot) == ('藏品','[机敏]防护安全带','01')


@pytest.mark.parametrize('action',['确定','完成'])
def test_result_requires_summary_and_actual_action(action):
    op=operation(LostVoidRunLevel)
    texts=[('总计用时：',490),('完成关卡',550),(action,935)]
    rows=[SimpleNamespace(data=t,center=SimpleNamespace(y=y)) for t,y in texts]
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=lambda **_: rows)
    assert battle_result(op.ctx,op.last_screenshot) == action
    rows.pop(1)
    assert battle_result(op.ctx,op.last_screenshot) is None
    op.ctx.controller.btn_press.assert_not_called()


def test_result_confirmation_requires_acknowledged_departure(monkeypatch):
    import zzz_od.application.hollow_zero.lost_void.operation.lost_void_run_level as source
    op=operation(LostVoidRunLevel)
    result=Mock(return_value='确定')
    monkeypatch.setattr(source,'battle_result',result)
    monkeypatch.setattr(source,'entry_header',lambda *_:None)
    monkeypatch.setattr(source,'menu_matches',lambda *_:{})
    op.check_and_update_current_screen=Mock(return_value=None)
    assert op._background_result_ack('确定').result == R.WAIT
    assert op._background_result_ack('确定').result == R.WAIT
    assert op._background_result_ack('确定').result == R.WAIT
    assert op._background_result_ack('确定').is_fail
    result.return_value=None
    assert op._background_result_ack('确定').result == R.WAIT
    op.ctx.lost_void.in_normal_world.return_value=True
    assert op._background_result_ack('确定').is_success


@pytest.mark.parametrize('wanted', ['完成','确定'])
def test_result_animation_with_missing_button_is_not_departure(monkeypatch,wanted):
    import zzz_od.application.hollow_zero.lost_void.operation.lost_void_run_level as source
    op=operation(LostVoidRunLevel)
    op._result_requests=1
    op.check_and_update_current_screen=Mock(return_value=None)
    monkeypatch.setattr(source,'battle_result',lambda *_:None)
    monkeypatch.setattr(source,'entry_header',lambda *_:None)
    monkeypatch.setattr(source,'menu_matches',lambda *_:{})
    assert op._background_result_ack(wanted).result == R.WAIT
    op.ctx.controller.btn_press.assert_not_called()
    monkeypatch.setattr(source,'entry_header',lambda *_:'迷失之地-入口-常规')
    assert op._background_result_ack(wanted).is_success


def test_after_complete_recovers_visible_final_summary_without_incrementing(monkeypatch):
    import zzz_od.application.hollow_zero.lost_void.lost_void_app as source
    op=operation(source.LostVoidApp)
    op.run_record=SimpleNamespace(add_complete_times=Mock())
    monkeypatch.setattr(source,'battle_result',lambda *_:'完成')
    monkeypatch.setattr(source,'failed_grade',lambda *_:False)
    for _ in range(3):
        assert op.after_complete().result == R.WAIT
    assert op.after_complete().is_fail
    assert op.ctx.controller.btn_press.call_count == 3
    assert op.ctx.controller.btn_press.call_args.args == ('xbox_b',)
    op.run_record.add_complete_times.assert_not_called()


def test_failed_final_summary_cannot_be_recovered_as_success(monkeypatch):
    import zzz_od.application.hollow_zero.lost_void.lost_void_app as source
    op=operation(source.LostVoidApp)
    op.run_record=SimpleNamespace(add_complete_times=Mock())
    monkeypatch.setattr(source,'battle_result',lambda *_:'完成')
    monkeypatch.setattr(source,'failed_grade',lambda *_:True)
    assert op.after_complete().is_fail
    op.ctx.controller.btn_press.assert_not_called()
    op.run_record.add_complete_times.assert_not_called()


def test_dialogue_resume_needs_speaker_and_content():
    op=operation(LostVoidRunLevel)
    rows=[SimpleNamespace(data='玛琳',center=SimpleNamespace(y=815)),
          SimpleNamespace(data='您好，独立调查员阁下。',center=SimpleNamespace(y=928))]
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=lambda **_: rows)
    assert dialogue_visible(op.ctx,op.last_screenshot)
    rows.pop(0)
    assert not dialogue_visible(op.ctx,op.last_screenshot)


def test_route_menu_never_closes_unknown_screen():
    op=operation(LostVoidRouteChange)
    op.round_by_find_area=Mock(return_value=op.round_retry())
    assert op.back_to_world().result == R.RETRY
    op.ctx.controller.btn_press.assert_not_called()
    op.round_by_find_area.return_value=op.round_success()
    assert op.back_to_world().result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_b',press_time=.12)
    assert op.back_to_world().result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once()
    op.round_by_find_area.return_value=op.round_retry()
    assert op.back_to_world().is_success
    op.ctx.lost_void.in_normal_world.return_value=True
    assert op.back_to_world().is_success


def dialogue_option_op():
    op=operation(LostVoidRunLevel)
    path=Path(__file__).parent/'fixtures/lost_void/gamepad_dialogue_options.png'
    op.last_screenshot=cv2.cvtColor(cv2.imread(str(path)),cv2.COLOR_BGR2RGB)
    op.ctx.screen_loader=SimpleNamespace(get_area=lambda *_:SimpleNamespace(rect=Rect(1438,536,1914,830)))
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=Mock(return_value=[
        SimpleNamespace(data='我是我是',center=SimpleNamespace(y=668)),
        SimpleNamespace(data='是...吧？',center=SimpleNamespace(y=745))]))
    op.round_by_find_area=Mock(return_value=op.round_success())
    return op


@pytest.mark.parametrize('pad,key',[('xbox','xbox_a'),('ds4','ds4_cross')])
def test_real_gamepad_dialogue_selected_option_confirms_without_mouse(pad,key):
    op=dialogue_option_op()
    op.ctx.game_config.background_gamepad_type=pad
    assert op.try_talk_options(op.last_screenshot).result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with(key,press_time=.12)
    op.ctx.controller.click.assert_not_called()


def test_dialogue_waits_for_focus_before_confirmation():
    op=dialogue_option_op()
    op.last_screenshot[:]=0
    assert op.try_talk_options(op.last_screenshot).result == R.WAIT
    op.ctx.controller.btn_press.assert_not_called()


def test_recorded_scene_crate_text_does_not_block_dialogue_continue():
    op=dialogue_option_op()
    path=Path(__file__).parent/'fixtures/lost_void/dialogue_scene_text_no_options.png'
    op.last_screenshot=cv2.cvtColor(cv2.imread(str(path)),cv2.COLOR_BGR2RGB)
    op.ctx.ocr_service.get_ocr_result_list.return_value=[
        SimpleNamespace(data='精注章',center=SimpleNamespace(y=803)),
        SimpleNamespace(data='JITIAN',center=SimpleNamespace(y=822))]
    op.round_by_find_area.return_value=op.round_retry()
    assert op.try_talk_options(op.last_screenshot) is None
    op.ctx.controller.btn_press.assert_not_called()
    assert op._talk_pad_requests==0


def test_dialogue_moves_to_first_option_then_requires_new_frame():
    op=dialogue_option_op()
    op.last_screenshot[:]=0
    op.last_screenshot[715:775,1438:1914]=(230,220,0)
    assert op.try_talk_options(op.last_screenshot).result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_dpad_up',press_time=.12)


def test_dialogue_stops_when_confirmed_options_remain_unchanged():
    op=dialogue_option_op()
    for _ in range(3):
        assert op.try_talk_options(op.last_screenshot).result == R.WAIT
    assert op.try_talk_options(op.last_screenshot).is_fail
    assert op.ctx.controller.btn_press.call_count==3
    op.ctx.ocr_service.get_ocr_result_list.return_value=[]
    op.last_screenshot[:]=0
    assert op.try_talk_options(op.last_screenshot) is None
    assert op._talk_pad_requests==0


def test_challenge_popup_requires_visible_button_and_bounds_confirmation():
    op = operation(LostVoidRunLevel)
    op.round_by_find_area = Mock(return_value=op.round_retry())
    op.round_by_find_and_click_area = Mock()
    assert not op._confirm_challenge_popup().is_success
    op.ctx.controller.btn_press.assert_not_called()
    op.round_by_find_area.return_value = op.round_success()
    for _ in range(3):
        assert op._confirm_challenge_popup().is_success
    assert op._confirm_challenge_popup().is_fail
    assert op.ctx.controller.btn_press.call_count == 3
    op.round_by_find_and_click_area.assert_not_called()
    op.round_by_find_area.return_value = op.round_retry()
    op._confirm_challenge_popup()
    op.round_by_find_area.return_value = op.round_success()
    assert op._confirm_challenge_popup().is_success


def connection_fixture(op):
    path=Path(__file__).parent/'fixtures/lost_void/connection_retry.png'
    op.last_screenshot=cv2.cvtColor(cv2.imread(str(path)),cv2.COLOR_BGR2RGB)
    data=json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
    rows=[SimpleNamespace(data=row['text'],center=Rect(row['rect'][0],row['rect'][1],
        row['rect'][0]+row['rect'][2],row['rect'][1]+row['rect'][3]).center) for row in data['result']['ocr']]
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=Mock(return_value=rows))
    return rows


@pytest.mark.parametrize('missing',[None,'服务器连接超时，','重新登录','继续连接','focus'])
def test_connection_retry_requires_actual_dialog_and_selected_retry(missing):
    from zzz_od.application.hollow_zero.lost_void.mission_screen import recover_connection
    op=operation(LostVoidRunLevel)
    rows=connection_fixture(op)
    if missing=='focus':op.last_screenshot[:]=0
    else:op.ctx.ocr_service.get_ocr_result_list.return_value=[row for row in rows if row.data!=missing]
    result=recover_connection(op)
    assert (result is not None)==(missing is None)
    assert op.ctx.controller.btn_press.called==(missing is None)
    op.ctx.controller.click.assert_not_called()


@pytest.mark.parametrize('backend,key',[('xbox','xbox_a'),('ds4','ds4_cross')])
def test_connection_retry_is_bounded_and_resets_after_dialog_departs(backend,key):
    from zzz_od.application.hollow_zero.lost_void.mission_screen import recover_connection
    op=operation(LostVoidRunLevel)
    connection_fixture(op)
    op.ctx.game_config.background_gamepad_type=backend
    for _ in range(3):assert recover_connection(op).result==R.WAIT
    assert recover_connection(op).is_fail
    assert op.ctx.controller.btn_press.call_count==3
    assert all(call.args==(key,) for call in op.ctx.controller.btn_press.call_args_list)
    image=op.last_screenshot
    op.last_screenshot=np.zeros_like(image)
    assert recover_connection(op) is None
    op.last_screenshot=image
    assert recover_connection(op).result==R.WAIT


def test_connection_retry_preempts_initial_screen_routing_without_counting(monkeypatch):
    from zzz_od.application.hollow_zero.lost_void.lost_void_app import LostVoidApp
    op=operation(LostVoidApp)
    connection_fixture(op)
    op.round_by_find_area=Mock()
    op.run_record=SimpleNamespace(add_complete_times=Mock())
    assert op.check_initial_screen().result==R.WAIT
    op.round_by_find_area.assert_not_called()
    op.run_record.add_complete_times.assert_not_called()


def test_connection_recovery_fade_waits_in_initial_node_instead_of_teleporting(monkeypatch):
    import time
    import zzz_od.application.hollow_zero.lost_void.lost_void_app as source
    op=operation(source.LostVoidApp)
    op.lost_void_debug=False
    op.config=SimpleNamespace(mission_name='特遣调查')
    op._connection_wait_until=time.time()+30
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=Mock(return_value=[]))
    op.round_by_find_area=Mock(return_value=op.round_retry())
    op._entry_header=Mock(return_value=None)
    op.check_and_update_current_screen=Mock(return_value=None)
    op.check_screen_with_can_go=Mock(return_value=(None,False))
    op.check_current_can_go=Mock()
    for name in ('detail_mission','battle_result','dialogue_visible','single_event_choice','black_story_caption'):
        monkeypatch.setattr(source,name,lambda *_:None)
    monkeypatch.setattr(source,'menu_matches',lambda *_:{})
    assert op.check_initial_screen().result==R.WAIT
    op.check_current_can_go.assert_not_called()
    op.ctx.controller.btn_press.assert_not_called()


def curse_card_fixture(op):
    path=Path(__file__).parent/'fixtures/lost_void/two_curse_cards.png'
    op.last_screenshot=cv2.cvtColor(cv2.imread(str(path)),cv2.COLOR_BGR2RGB)
    data=json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
    rows=[SimpleNamespace(data=row['text'],center=Rect(row['rect'][0],row['rect'][1],
        row['rect'][0]+row['rect'][2],row['rect'][1]+row['rect'][3]).center) for row in data['result']['ocr']]
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=Mock(return_value=rows))
    return rows


@pytest.mark.parametrize('missing',[None,'title','confirm','label','footer','name','focus'])
def test_real_multi_candidate_card_event_requires_full_structure(missing):
    from zzz_od.application.hollow_zero.lost_void.mission_screen import common_choice
    op=operation(LostVoidRunLevel)
    rows=curse_card_fixture(op)
    predicates={'title':lambda row:row.center.y<205,
        'confirm':lambda row:row.data=='确定',
        'label':lambda row:250<row.center.y<350,
        'footer':lambda row:'HOLLOW' in row.data,
        'name':lambda row:510<row.center.y<555}
    if missing=='focus':op.last_screenshot[:]=0
    elif missing:op.ctx.ocr_service.get_ocr_result_list.return_value=[row for row in rows if not predicates[missing](row)]
    assert common_choice(op.ctx,op.last_screenshot)==(missing is None)
    op.ctx.controller.btn_press.assert_not_called()


def test_late_event_card_returns_to_interaction_without_marking_npc_complete():
    op=operation(LostVoidRunLevel)
    curse_card_fixture(op)
    op.locked_interact_target=SimpleNamespace(name='研究员')
    op.ctx.lost_void.completed_npc_names=set()
    assert op.after_interact().status=='后续交互'
    assert op.locked_interact_target.name=='研究员'
    assert op.ctx.lost_void.completed_npc_names==set()
    op.ctx.controller.btn_press.assert_not_called()


def test_multi_candidate_card_event_confirms_selected_card_without_tab_template():
    op=operation(LostVoidChooseCommon)
    curse_card_fixture(op)
    op.check_and_update_current_screen=Mock(return_value=None)
    op._pad_target=None
    op._pad_confirm_requests=0
    op.to_choose_num=1
    item=SimpleNamespace(rect=Rect(584,255,928,760),can_choose=False,chosen=True,
        artifact=SimpleNamespace(display_name='障目屏知之印'))
    op.get_artifact_pos=Mock(return_value=([],[item]))
    assert op._choose_with_pad().result==R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_a',press_time=.12)
    op.ctx.controller.click.assert_not_called()


def gear_reward_fixture(op):
    path=Path(__file__).parent/'fixtures/lost_void/two_gear_cards.png'
    op.last_screenshot=cv2.cvtColor(cv2.imread(str(path)),cv2.COLOR_BGR2RGB)
    data=json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
    rows=[SimpleNamespace(data=row['text'],center=Rect(row['rect'][0],row['rect'][1],
        row['rect'][0]+row['rect'][2],row['rect'][1]+row['rect'][3]).center) for row in data['result']['ocr']]
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=Mock(return_value=rows))
    return rows


@pytest.mark.parametrize('missing',[None,'获得武备','确定','GEAR','[异常·击破]溶剂弹射枪'])
def test_gear_reward_requires_actual_title_name_marker_and_lower_confirmation(missing):
    from zzz_od.application.hollow_zero.lost_void.mission_screen import common_choice
    op=operation(LostVoidChooseCommon)
    rows=gear_reward_fixture(op)
    op.ctx.ocr_service.get_ocr_result_list.return_value=[row for row in rows if row.data!=missing]
    assert common_choice(op.ctx,op.last_screenshot)==(missing is None)
    op.ctx.controller.btn_press.assert_not_called()


def test_actual_gear_reward_signature_includes_level_and_name_without_description():
    op=operation(LostVoidChooseCommon)
    gear_reward_fixture(op)
    op.to_choose_gear=True
    assert op._reward_page_signature(op.last_screenshot)==('武备','[异常·击破]溶剂弹射枪','2')


def test_gear_reward_resets_selection_confirmation_budget_and_acknowledges_once():
    op=operation(LostVoidChooseCommon)
    gear_reward_fixture(op)
    op._pad_confirm_requests=3
    op._pad_target=None
    op._pad_reward_page=None
    op.to_choose_num=0
    op.to_choose_gear=True
    op.to_choose_artifact=False
    op.check_and_update_current_screen=Mock(return_value=None)
    op.get_artifact_pos=Mock(return_value=([],[]))
    assert op._choose_with_pad().result==R.WAIT
    assert op._pad_confirm_requests==1
    op.ctx.controller.btn_press.assert_called_once_with('xbox_a',press_time=.12)


def test_generic_gear_choice_replay_uses_real_rim_and_annotated_title_and_slots():
    from zzz_od.application.hollow_zero.lost_void.mission_screen import common_choice
    op=operation(LostVoidChooseCommon)
    path=Path(__file__).parent/'fixtures/lost_void/two_gear_choice.png'
    op.last_screenshot=cv2.cvtColor(cv2.imread(str(path)),cv2.COLOR_BGR2RGB)
    # Visible text annotations for this screenshot, not a claimed OCR recording.
    words=[('请选择1项',960,190),('确定',970,925),('GEAR',760,770),('[异常·击破]溶剂弹射枪',760,447)]
    rows=[SimpleNamespace(data=t,center=SimpleNamespace(x=x,y=y)) for t,x,y in words]
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=Mock(return_value=rows))
    assert common_choice(op.ctx,op.last_screenshot)
    op.ctx.controller.btn_press.assert_not_called()


def test_actual_resonium_event_single_card_is_recognized_without_abandon_button():
    from zzz_od.application.hollow_zero.lost_void.mission_screen import common_choice
    op=operation(LostVoidRunLevel)
    path=Path(__file__).parent/'fixtures/lost_void/resonium_event_card.png'
    op.last_screenshot=cv2.cvtColor(cv2.imread(str(path)),cv2.COLOR_BGR2RGB)
    data=json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
    rows=[SimpleNamespace(data=row['text'],center=Rect(row['rect'][0],row['rect'][1],
        row['rect'][0]+row['rect'][2],row['rect'][1]+row['rect'][3]).center) for row in data['result']['ocr']]
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=Mock(return_value=rows))
    assert common_choice(op.ctx,op.last_screenshot)
    op.locked_interact_target=SimpleNamespace(name='研究员')
    assert op.after_interact().status=='后续交互'
    op.ctx.controller.btn_press.assert_not_called()


def store_upgrade_fixture(op):
    path=Path(__file__).parent/'fixtures/lost_void/store_gear_upgrade.png'
    op.last_screenshot=cv2.cvtColor(cv2.imread(str(path)),cv2.COLOR_BGR2RGB)
    data=json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
    rows=[SimpleNamespace(data=row['text'],center=Rect(row['rect'][0],row['rect'][1],
        row['rect'][0]+row['rect'][2],row['rect'][1]+row['rect'][3]).center) for row in data['result']['ocr']]
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=Mock(return_value=rows))
    return rows


@pytest.mark.parametrize('missing',[None,'武备已升级','确定','GENR','[绝境]浩劫令牌'])
def test_actual_store_upgrade_accepts_stylized_marker_only_with_receipt_identifiers(missing):
    from zzz_od.application.hollow_zero.lost_void.mission_screen import common_choice
    op=operation(LostVoidChooseCommon)
    rows=store_upgrade_fixture(op)
    op.ctx.ocr_service.get_ocr_result_list.return_value=[row for row in rows if row.data!=missing]
    assert common_choice(op.ctx,op.last_screenshot)==(missing is None)
    op.ctx.controller.btn_press.assert_not_called()


def test_visible_upgrade_takes_precedence_over_shop_background_and_bounds_acknowledgements():
    op=operation(LostVoidChooseCommon)
    store_upgrade_fixture(op)
    op.to_choose_num=0
    op.to_choose_gear=True
    op.return_screen_name='迷失之地-邦布商店'
    op._pad_confirm_requests=1
    op._pad_target=None
    op.check_and_update_current_screen=Mock(return_value='迷失之地-邦布商店')
    op.get_artifact_pos=Mock(return_value=([],[]))
    for _ in range(5):
        assert op._choose_with_pad().result==R.WAIT
    assert op._choose_with_pad().is_fail
    assert op.ctx.controller.btn_press.call_count==5
    op.ctx.ocr_service.get_ocr_result_list.return_value=[]
    assert op._choose_with_pad().is_success
    assert op.ctx.controller.btn_press.call_count==5


@pytest.mark.parametrize('quantity_present',[False,True])
def test_missing_reward_quantity_does_not_create_a_new_page_or_reset_budget(quantity_present):
    op=reward_operation()
    op._pad_reward_page=('藏品','[机敏]防护安全带','01') if not quantity_present else ('藏品','[机敏]防护安全带')
    op._pad_confirm_requests=2
    op.ctx.ocr_service.get_ocr_result_list.return_value=reward_rows(quantity='01' if quantity_present else '')
    assert op._choose_with_pad().result==R.WAIT
    assert op._pad_confirm_requests==3


def test_store_reward_is_processed_before_buying_behind_the_overlay(monkeypatch):
    import zzz_od.application.hollow_zero.lost_void.operation.interact.lost_void_bangboo_store as module
    op=operation(LostVoidBangbooStore)
    store_upgrade_fixture(op)
    op.store_type='标识-金币'
    op.ctx.lost_void.challenge_config.store_gold=True
    op.check_and_update_current_screen=Mock(return_value='迷失之地-邦布商店')
    receipt=SimpleNamespace(execute=Mock(return_value=SimpleNamespace(success=True)))
    monkeypatch.setattr(module,'LostVoidChooseCommon',lambda ctx:receipt)
    assert op._buy_with_pad().result==R.WAIT
    assert receipt.return_screen_name=='迷失之地-邦布商店'
    receipt.execute.assert_called_once()
    op.ctx.controller.btn_press.assert_not_called()


def test_store_browses_disabled_buttons_with_finite_limit_instead_of_waiting_for_green():
    op=operation(LostVoidBangbooStore)
    op.store_type='标识-金币'
    op.ctx.lost_void.challenge_config.store_gold=True
    op.check_and_update_current_screen=Mock(return_value='迷失之地-邦布商店')
    op._gold_balance=Mock(return_value=0)
    for _ in range(8):
        assert op._buy_with_pad().result==R.WAIT
    assert op._buy_with_pad().is_fail
    assert op.ctx.controller.btn_press.call_count==8
    assert all(call.args==('xbox_dpad_right',) for call in op.ctx.controller.btn_press.call_args_list)


def period_buff_screen(name):
    path = Path(__file__).parent / f'fixtures/lost_void/period_buff_{name}.png'
    return cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)


@pytest.mark.parametrize('name,expected', [('unfocused', (None, None)), ('focused', (None, 0)),
                                           ('selected', (0, 0))])
def test_period_buff_state_reads_real_controller_screens(name, expected):
    from zzz_od.application.hollow_zero.lost_void.mission_screen import period_buff_state
    assert period_buff_state(period_buff_screen(name)) == expected


def buff_operation(buff_no):
    from zzz_od.application.hollow_zero.lost_void.lost_void_app import LostVoidApp
    op = operation(LostVoidApp)
    op.config = SimpleNamespace(mission_name='战线肃清')
    op.ctx.lost_void.challenge_config.period_buff_no = buff_no
    return op


def test_controller_buff_selection_focuses_then_confirms_until_verified():
    op = buff_operation('第一个')
    for name in ('unfocused', 'focused'):
        op.last_screenshot = period_buff_screen(name)
        assert op.choose_buff().result == R.WAIT
    assert [c.args[0] for c in op.ctx.controller.btn_press.call_args_list] == ['xbox_a', 'xbox_a']
    op.last_screenshot = period_buff_screen('selected')
    assert op.choose_buff().is_success
    assert op.ctx.controller.btn_press.call_count == 2


def test_controller_buff_selection_moves_focus_to_configured_card_and_is_bounded():
    op = buff_operation('第三个')
    op.last_screenshot = period_buff_screen('focused')
    assert op.choose_buff().result == R.WAIT
    assert op.ctx.controller.btn_press.call_args.args[0] == 'xbox_dpad_down'
    # A selected first card is not the configured third card.
    op.last_screenshot = period_buff_screen('selected')
    for _ in range(7):
        assert op.choose_buff().result == R.WAIT
    assert op.choose_buff().is_fail


def test_background_gear_menu_exits_repeated_screen_with_pad():
    op=operation(LostVoidChooseGear)
    op.completed_name_list=['[携游]敕令玄幡','[通用]某武备']
    op._pad_scan=None
    assert op._choose_gear_with_pad().status == LostVoidChooseGear.STATUS_REPEATED
    assert op.exit_repeated().result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_b',press_time=.12)
    op.ctx.lost_void.in_normal_world.return_value=True
    result=op.exit_repeated()
    assert result.is_success and result.status == LostVoidChooseGear.STATUS_REPEATED


def test_background_gear_first_slot_name_marks_screen_repeated():
    op=operation(LostVoidChooseGear)
    op.completed_name_list=['[携游]敕令玄幡']
    assert op._repeated_screen('[携游]敕令玄幡')
    assert not op._repeated_screen('[通用]另一个武备')
    assert not op._repeated_screen(None)
