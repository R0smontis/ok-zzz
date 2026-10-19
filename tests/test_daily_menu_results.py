import pytest
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import cv2
from onedragon.base.geometry.rectangle import Rect
from onedragon.base.operation.operation_round_result import OperationRoundResultEnum as R
from zzz_od.application.coffee.coffee_app import CoffeeApp
from zzz_od.application.engagement_reward.engagement_reward_app import EngagementRewardApp
from zzz_od.application.random_play.random_play_app import RandomPlayApp
from zzz_od.application.city_fund.city_fund_app import CityFundApp
from zzz_od.application.ridu_weekly.ridu_weekly_app import RiduWeeklyApp
from zzz_od.operation.back_to_normal_world import BackToNormalWorld
from test_lost_void_background_menus import operation
from src.navigation.menus import (compendium_card, compendium_category, compendium_lost_void, go_focused,
                                  lost_void_gateway)

BASE=Path(__file__).parent/'fixtures/daily_map'

def fixture(op,name):
    op.last_screenshot=cv2.cvtColor(cv2.imread(str(BASE/f'{name}.png')),cv2.COLOR_BGR2RGB)
    data=json.loads((BASE/f'{name}.json').read_text(encoding='utf-8'))
    rows=[SimpleNamespace(data=r['text'],center=Rect(r['rect'][0],r['rect'][1],r['rect'][0]+r['rect'][2],r['rect'][1]+r['rect'][3]).center) for r in data['result']['ocr']]
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=lambda image,rect,**_: [r for r in rows if rect.x1<=r.center.x<rect.x2 and rect.y1<=r.center.y<rect.y2])
    return rows


def coffee():
    op=operation(CoffeeApp);fixture(op,'coffee-order-menu')
    cup=SimpleNamespace(coffee_name='汀曼特调',extra=False,without_benefit=True)
    op.ctx.compendium_service=SimpleNamespace(name_2_coffee={'汀曼特调':cup})
    op._get_coffee_to_choose=Mock(return_value=['沙罗特调','汀曼特调'])
    op._pad_coffee_ordered=False;op.had_coffee_list=set();op.chosen_coffee=None
    return op


def test_coffee_uses_available_real_menu_not_unavailable_extra_coffee():
    op=coffee()
    assert op.choose_coffee().is_success
    assert op.chosen_coffee.coffee_name=='汀曼特调'
    op.ctx.controller.btn_press.assert_not_called()
    assert op.order_coffee().is_success
    op.ctx.controller.btn_press.assert_called_once_with('xbox_a',press_time=.12)
    assert not op.had_coffee_list  # Delivery is not proof of drinking/reward.
    assert op.order_coffee().is_fail
    assert op.ctx.controller.btn_press.call_count==1


def test_coffee_never_orders_without_actual_free_label_and_name():
    op=coffee();rows=fixture(op,'coffee-order-menu')
    assert op.choose_coffee().is_success
    rows[:]=[r for r in rows if '每日免费' not in str(r.data)]
    assert op.order_coffee().result==R.RETRY
    op.ctx.controller.btn_press.assert_not_called()
    assert not op.had_coffee_list


def test_engagement_requires_real_reward_popup_and_returned_daily_state():
    op=operation(EngagementRewardApp);op.handle_init()
    fixture(op,'engagement-before-claim')
    assert op.click_reward().is_success
    op.ctx.controller.btn_press.assert_called_once_with('xbox_x',press_time=.12)
    assert not op._pad_reward_seen
    fixture(op,'engagement-after-x')
    assert op.check_reward().result==R.RETRY
    assert op._pad_reward_seen
    assert op.ctx.controller.btn_press.call_args.args==('xbox_a',)
    fixture(op,'engagement-confirmed')
    assert op.check_reward().is_success
    assert op.ctx.controller.btn_press.call_count==2


def test_engagement_already_claimed_does_not_repeat_input():
    op=operation(EngagementRewardApp);op.handle_init()
    fixture(op,'engagement-confirmed')
    assert op.click_reward().status==op.STATUS_NO_REWARD
    assert op.check_reward().is_success
    op.ctx.controller.btn_press.assert_not_called()


def test_engagement_repeated_claim_without_game_change_is_bounded():
    op=operation(EngagementRewardApp);op.handle_init()
    fixture(op,'engagement-before-claim')
    for _ in range(4):assert op.click_reward().is_success
    assert op.click_reward().is_fail
    assert op.ctx.controller.btn_press.call_count==4


def test_random_play_ledger_uses_back_not_reward_selection_or_mouse():
    op=operation(RandomPlayApp)
    op.round_by_find_area=Mock(return_value=SimpleNamespace(is_success=True))
    op.round_by_find_and_click_area=Mock()
    assert op.wait_run().result==R.RETRY
    op.ctx.controller.btn_press.assert_called_once_with('xbox_b',press_time=.12)
    op.round_by_find_and_click_area.assert_not_called()


def store():
    op=operation(RandomPlayApp)
    op.config=SimpleNamespace(agent_name_1='随机',agent_name_2='随机')
    op.ctx.controller=SimpleNamespace(background_mode=True,btn_press=Mock())
    op.handle_init()
    return op


def test_small_promoter_confirm_is_read_without_full_footer_downscaling():
    op=store();fixture(op,'store-promoter-small-confirm')
    assert op.click_promoter_entry().is_success
    assert op.choose_promoter().result==R.RETRY
    assert op._pad_promoter_name=='丝琪'
    op.ctx.controller.btn_press.assert_called_once_with('xbox_a',press_time=.12)


def test_promoter_selection_requires_both_independent_labels():
    op=store();rows=fixture(op,'store-promoter-small-confirm')
    rows[:]=[r for r in rows if r.data!='确定']
    assert not op.click_promoter_entry().is_success
    assert op.choose_promoter().result==R.RETRY
    op.ctx.controller.btn_press.assert_not_called()


def test_integrity_business_popup_is_acknowledged_then_real_status_is_required():
    op=store();fixture(op,'store-integrity-popup')
    assert op.confirm().result==R.RETRY
    op.ctx.controller.btn_press.assert_called_once_with('xbox_a',press_time=.12)


def test_compendium_category_selects_then_verifies_actual_highlight():
    op=store();fixture(op,'compendium-category-up')
    # WAIT keeps the node's retry budget for real failures; lower categories need several presses.
    assert compendium_category(op,op.last_screenshot,'周期征讨').result==R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_dpad_up',press_time=.12)
    op.ctx.controller.btn_press.reset_mock()
    fixture(op,'compendium-periodic-select')
    assert compendium_category(op,op.last_screenshot,'周期征讨').is_success
    op.ctx.controller.btn_press.assert_not_called()


def test_compendium_category_presses_are_bounded_by_own_step_limit():
    op=store();fixture(op,'compendium-category-up')
    op._pad_category_steps=12
    assert compendium_category(op,op.last_screenshot,'周期征讨').result==R.FAIL
    op.ctx.controller.btn_press.assert_not_called()


def test_category_returns_from_real_header_focus_without_go_buttons():
    from src.navigation.menus import panel_button_focused
    op=store();rows=fixture(op,'compendium-hunt-other-focused')
    op.last_screenshot=cv2.cvtColor(cv2.imread(str(BASE/'compendium-hunt-header-focus.png')),cv2.COLOR_BGR2RGB)
    # Reuse a real focused header. No 前往 OCR is available: the category exit must not depend on it.
    rows[:]=[r for r in rows if str(r.data).strip()!='前往']
    assert panel_button_focused(op.last_screenshot)
    result=compendium_category(op,op.last_screenshot,'实战模拟室')
    assert result.result==R.WAIT and result.status=='返回分类列表，等待实际焦点'
    op.ctx.controller.btn_press.assert_called_once_with('xbox_b',press_time=.12)
    op.ctx.controller.btn_press.reset_mock()
    fixture(op,'compendium-combat-sim-cards')
    result=compendium_category(op,op.last_screenshot,'实战模拟室')
    assert result.is_success
    op.ctx.controller.btn_press.assert_not_called()


def test_unset_goal_subtitle_is_one_category_control_not_two_selections():
    op=store();fixture(op,'compendium-training-unset')
    result=compendium_category(op,op.last_screenshot,'专业挑战室')
    assert result.result==R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_dpad_down',press_time=.12)


def test_two_separate_highlighted_categories_still_block_navigation():
    op=store();fixture(op,'compendium-training-unset')
    op.last_screenshot[440:500,195:415]=(30,70,230)
    op._pad_category_unverified=6
    assert compendium_category(op,op.last_screenshot,'专业挑战室').result==R.RETRY
    op.ctx.controller.btn_press.assert_not_called()


def test_double_drop_badge_is_part_of_the_selected_category():
    # Real 3.2 frame: a yellow 双倍 badge is read as its own line on top of the blue 实战模拟室.
    op=store();fixture(op,'compendium-double-badge')
    assert compendium_category(op,op.last_screenshot,'实战模拟室').is_success
    op.ctx.controller.btn_press.assert_not_called()
    op=store();fixture(op,'compendium-double-badge')
    assert compendium_category(op,op.last_screenshot,'区域巡防').result==R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_dpad_down',press_time=.12)
    op=store();fixture(op,'compendium-double-badge')
    assert compendium_category(op,op.last_screenshot,'特训目标').result==R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_dpad_up',press_time=.12)


def is_butcher(text):
    import difflib
    return difflib.get_close_matches(text,['初生死路屠夫'],n=1)==['初生死路屠夫']


def test_go_focus_accepts_both_pulse_colors_and_rejects_idle_buttons():
    op=store()
    fixture(op,'compendium-hunt-target-focused')  # yellow-green phase, focus on the lower card
    assert go_focused(op.last_screenshot,851) and not go_focused(op.last_screenshot,641)
    fixture(op,'compendium-hunt-other-focused')  # yellow phase
    assert go_focused(op.last_screenshot,851) and not go_focused(op.last_screenshot,641)


def test_compendium_card_confirms_only_the_focused_target():
    op=store();fixture(op,'compendium-hunt-target-focused')
    assert compendium_card(op,op.last_screenshot,is_butcher,'初生死路屠夫').is_success
    op.ctx.controller.btn_press.assert_called_once_with('xbox_a',press_time=.12)
    assert op._pad_go_sent


def test_compendium_card_moves_toward_visible_target_without_confirming():
    op=store();fixture(op,'compendium-hunt-target-focused')
    is_unknown=lambda text: '未知复合' in text  # Visible above the focused card.
    assert compendium_card(op,op.last_screenshot,is_unknown,'未知复合侵蚀体').result==R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_dpad_up',press_time=.12)
    assert not getattr(op,'_pad_go_sent',False)


def test_compendium_card_scrolls_then_reverses_at_list_end():
    op=store();fixture(op,'compendium-hunt-other-focused')
    missing=lambda text: text=='库萨里库'
    assert compendium_card(op,op.last_screenshot,missing,'库萨里库').result==R.WAIT
    op.ctx.controller.btn_press.assert_called_with('xbox_dpad_down',press_time=.12)
    # Same focused card after the press: the list end was reached, search upward.
    assert compendium_card(op,op.last_screenshot,missing,'库萨里库').result==R.WAIT
    op.ctx.controller.btn_press.assert_called_with('xbox_dpad_up',press_time=.12)
    assert op.ctx.controller.btn_press.call_count==2


def test_compendium_card_reads_top_card_of_combat_simulation_list():
    import difflib
    names=['基础材料','代理人晋升','音擎改装']
    matcher=lambda name: (lambda text: difflib.get_close_matches(text,names,n=1)==[name])
    op=store();fixture(op,'compendium-combat-sim-cards')  # Focus on 代理人晋升; 基础材料 is the top card.
    assert compendium_card(op,op.last_screenshot,matcher('基础材料'),'基础材料').result==R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_dpad_up',press_time=.12)
    op=store();fixture(op,'compendium-combat-sim-cards')
    assert compendium_card(op,op.last_screenshot,matcher('代理人晋升'),'代理人晋升').is_success  # OCR reads 晉.
    op.ctx.controller.btn_press.assert_called_once_with('xbox_a',press_time=.12)


def test_compendium_card_without_focus_enters_list_and_never_moves_categories():
    # Keyboard prompts (no focus anywhere): A switches prompts or enters the list; a d-pad press here
    # would move the category selection instead.
    op=store();fixture(op,'compendium-combat-sim-keyboard')
    for _ in range(2):
        assert compendium_card(op,op.last_screenshot,lambda t: t=='基础材料','基础材料').result==R.WAIT
    assert [c.args[0] for c in op.ctx.controller.btn_press.call_args_list]==['xbox_a','xbox_a']
    op._pad_card_steps=30
    assert compendium_card(op,op.last_screenshot,lambda t: t=='基础材料','基础材料').is_fail


def test_compendium_card_moves_off_focused_header_button():
    op=store();fixture(op,'compendium-hunt-target-focused')
    header=cv2.imread(str(BASE/'compendium-hunt-header-focus.png'))  # Focus on 周期挑战, no 前往 focused.
    op.last_screenshot=cv2.cvtColor(header,cv2.COLOR_BGR2RGB)
    assert compendium_card(op,op.last_screenshot,is_butcher,'初生死路屠夫').result==R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_dpad_down',press_time=.12)


def test_compendium_lost_void_never_confirms_focused_neighbor():
    op=store();fixture(op,'compendium-periodic-select')
    assert compendium_lost_void(op,op.last_screenshot).result==R.RETRY
    op.ctx.controller.btn_press.assert_called_once_with('xbox_dpad_down',press_time=.12)
    op.ctx.controller.btn_press.reset_mock()
    fixture(op,'compendium-lost-focus')
    assert compendium_lost_void(op,op.last_screenshot).is_success
    op.ctx.controller.btn_press.assert_called_once_with('xbox_a',press_time=.12)


def test_lost_void_gateway_confirms_selected_gamepad_marker_with_bounded_attempts():
    op=store();fixture(op,'lost-void-gateway')
    for _ in range(4):assert lost_void_gateway(op,op.last_screenshot).result==R.RETRY
    assert lost_void_gateway(op,op.last_screenshot).is_fail
    assert op.ctx.controller.btn_press.call_count==4
    assert all(call.args==('xbox_a',) for call in op.ctx.controller.btn_press.call_args_list)


def test_lost_void_gateway_does_not_confirm_without_selection_marker():
    op=store();fixture(op,'lost-void-gateway')
    op.last_screenshot[910:960,430:490]=0
    assert lost_void_gateway(op,op.last_screenshot).result==R.RETRY
    op.ctx.controller.btn_press.assert_not_called()


def test_world_return_uses_gamepad_back_on_verified_deep_investigation_gateway():
    op=operation(BackToNormalWorld);fixture(op,'lost-void-gateway')
    op.check_and_update_current_screen=Mock(return_value=None)
    op.round_by_find_area=Mock(return_value=SimpleNamespace(is_success=False))
    op._background_menu_back=0
    for _ in range(6):
        assert op.check_screen_and_run().result==R.RETRY
    assert op.check_screen_and_run().is_fail
    assert op.ctx.controller.btn_press.call_count==6
    assert all(call.args==('xbox_b',) for call in op.ctx.controller.btn_press.call_args_list)


def test_starting_on_gateway_routes_directly_to_entry_without_world_exit(monkeypatch):
    from zzz_od.application.hollow_zero.lost_void.lost_void_app import LostVoidApp
    op=operation(LostVoidApp);fixture(op,'lost-void-gateway')
    op.lost_void_debug=False
    monkeypatch.setattr('zzz_od.application.hollow_zero.lost_void.lost_void_app.recover_connection',lambda op:None)
    assert op.check_initial_screen().status=='可前往副本画面'
    assert op.choose_lost_void_entry().result==R.RETRY
    assert op.ctx.controller.btn_press.call_args.args==('xbox_a',)


def test_store_existing_promoter_is_verified_and_videos_open_by_actual_focus():
    op=store();fixture(op,'store-promoter-confirmed')
    assert op.check_running().is_success
    assert op.click_promoter_entry().is_success
    assert op.choose_promoter().is_success
    assert op.check_video_theme().is_success
    assert op._need_video_themes==['惊悚','访谈','亲情']
    assert op.click_video_entry().result==R.RETRY
    op.ctx.controller.btn_press.assert_called_once_with('xbox_dpad_right',press_time=.12)
    fixture(op,'store-video-focus')
    assert op.click_video_entry().result==R.RETRY
    assert op.ctx.controller.btn_press.call_args.args==('xbox_a',)


def test_store_random_promoter_requires_confirm_and_actual_card_name():
    op=store();fixture(op,'store-promoter-list')
    assert op.click_promoter_entry().is_success
    assert op.choose_promoter().result==R.RETRY
    assert op._pad_promoter_name=='丝琪'
    fixture(op,'store-promoter-confirmed')
    assert op.choose_promoter().is_success
    assert op.ctx.controller.btn_press.call_count==1


def test_store_specific_promoter_never_confirms_wrong_character():
    op=store();op.config.agent_name_1=op.config.agent_name_2='安比'
    fixture(op,'store-promoter-list')
    assert op.choose_promoter().result==R.RETRY
    op.ctx.controller.btn_press.assert_called_once_with('xbox_dpad_right',press_time=.12)
    assert op._pad_promoter_name is None


def test_store_recommended_shelf_requires_returned_three_video_cards():
    op=store();fixture(op,'store-video-list')
    assert op.check_recommended().result==R.RETRY
    op.ctx.controller.btn_press.assert_called_once_with('xbox_x',press_time=.12)
    fixture(op,'store-promoter-confirmed')
    assert not op.check_recommended().is_success
    fixture(op,'store-recommended-applied')
    assert op.check_recommended().status=='推荐上架'
    assert op.start().is_success
    fixture(op,'store-business-confirmation')
    assert op.confirm_business().is_success
    assert op.ctx.controller.btn_press.call_args.args==('xbox_a',)
    # A delivered confirm or remaining Start button is not proof of business.
    fixture(op,'store-business-cancelled')
    assert not op.confirm().is_success


def test_city_fund_reads_current_top_tabs_and_claims_actual_task_rewards():
    op=operation(CityFundApp);op.handle_init();fixture(op,'city-task-tab')
    assert op.click_fund().is_success
    assert op.click_task().is_success
    assert op.click_task_claim().result==R.RETRY
    op.ctx.controller.btn_press.assert_called_once_with('xbox_x',press_time=.12)
    assert op.click_level().result==R.RETRY
    assert op.ctx.controller.btn_press.call_args.args==('xbox_lb',)


def test_store_recovery_cannot_turn_failure_into_success(monkeypatch):
    op=store()
    monkeypatch.setattr(RandomPlayApp,'previous_node',property(lambda self:SimpleNamespace(name='点击宣传员入口',is_success=False,status='入口失败')))
    back=Mock();back.execute.return_value=SimpleNamespace(success=True,status='大世界-普通')
    monkeypatch.setattr('zzz_od.application.random_play.random_play_app.BackToNormalWorld',lambda ctx:back)
    op.round_by_op_result=lambda result:op.round_success(result.status)
    assert op.close_business_page().is_success
    assert op.back_to_world().is_fail
    assert op.back_to_world().status=='入口失败'


def test_weekly_does_not_mark_entry_complete_until_real_weekly_page():
    op=operation(RiduWeeklyApp);op.handle_init();fixture(op,'weekly-entry-real')
    assert op.click_schedule().result==R.RETRY
    op.ctx.controller.btn_press.assert_called_once_with('xbox_a',press_time=.12)
    fixture(op,'weekly-detail-real')
    assert op.click_schedule().is_success
    assert op.claim_score().result==R.WAIT
    assert op.ctx.controller.btn_press.call_args.args==('xbox_dpad_right',)


def test_weekly_only_claims_actual_completed_highlighted_grid():
    op=operation(RiduWeeklyApp);op.handle_init();fixture(op,'weekly-claim-focus')
    assert op.claim_score().result==R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_a',press_time=.12)
    assert op._pad_weekly_score==1
    assert op.confirm_schedule().is_success  # Disabled X hint must not trigger.
    assert op.ctx.controller.btn_press.call_count==1


def test_weekly_scrolls_offscreen_entry_without_confirming_other_daily_card():
    op=operation(RiduWeeklyApp);op.handle_init();fixture(op,'weekly-offscreen-real')
    assert op.click_schedule().result==R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_dpad_left',press_time=.12)
    for _ in range(11):assert op.click_schedule().result==R.WAIT
    assert op.click_schedule().is_fail
    assert op.ctx.controller.btn_press.call_count==12


def test_business_success_message_is_confirmed_but_not_counted_as_running():
    op=store();fixture(op,'store-business-success-popup')
    assert op.confirm().result==R.RETRY
    op.ctx.controller.btn_press.assert_called_once_with('xbox_a',press_time=.12)
    assert not op.confirm().is_success


def test_compendium_does_not_repeat_open_confirmation_on_delayed_focus():
    op=store();fixture(op,'compendium-prefix-focus')
    op.last_screenshot[610:680,1330:1610]=0
    assert compendium_lost_void(op,op.last_screenshot).result==R.RETRY
    assert compendium_lost_void(op,op.last_screenshot).result==R.RETRY
    op.ctx.controller.btn_press.assert_called_once_with('xbox_a',press_time=.12)
    op.ctx.controller.btn_press.reset_mock()
    fixture(op,'compendium-prefix-focus')
    assert compendium_lost_void(op,op.last_screenshot).result==R.RETRY
    op.ctx.controller.btn_press.assert_called_once_with('xbox_dpad_down',press_time=.12)


def test_business_success_then_counter_overworld_completes(monkeypatch):
    # Live 2026-10-09: after "丁尼广进，生意兴隆！" + A, the game closes the store page and
    # returns to the counter instead of showing "正在营业"; the node waited until it failed.
    op=store();fixture(op,'store-business-success-popup')
    assert op.confirm().result==R.RETRY
    op.last_screenshot=cv2.cvtColor(cv2.imread(str(BASE/'store-counter-after-business.png')),cv2.COLOR_BGR2RGB)
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=lambda image,rect:[])
    screens=[]
    op.check_and_update_current_screen=lambda screen,screen_name_list:screens.append(screen_name_list) or '大世界-普通'
    assert op.confirm().is_success
    assert screens==[['大世界-普通']]
    assert op.ctx.controller.btn_press.call_count==1


@pytest.mark.parametrize('slogan,label',[('童叟无欺，客似云来！','确认'),('丁尼广进，生意兴隆！','C确认')])
def test_any_business_slogan_popup_is_confirmed_then_counter_overworld_completes(slogan,label):
    # Live 2026-10-12: a slogan outside the known texts waited 11 rounds and failed the app.
    op=store();rows=fixture(op,'store-business-success-popup')
    next(r for r in rows if '生意兴隆' in r.data).data=slogan
    next(r for r in rows if r.data=='确认').data=label
    assert op.confirm().result==R.RETRY
    op.ctx.controller.btn_press.assert_called_once_with('xbox_a',press_time=.12)
    op.last_screenshot=cv2.cvtColor(cv2.imread(str(BASE/'store-counter-after-business.png')),cv2.COLOR_BGR2RGB)
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=lambda image,rect:[])
    op.check_and_update_current_screen=lambda screen,screen_name_list:'大世界-普通'
    assert op.confirm().is_success


def test_start_confirmation_dialog_is_not_taken_as_business_slogan():
    op=store();fixture(op,'store-business-confirmation')
    assert not op._business_slogan_popup()
    op.check_and_update_current_screen=lambda screen,screen_name_list:None
    op.last_screenshot[595:655,980:1250]=0  # Focus not verified: no input.
    assert op.confirm().result==R.RETRY
    op.ctx.controller.btn_press.assert_not_called()
    fixture(op,'store-business-confirmation')
    assert op.confirm().result==R.RETRY  # A lingering, focused confirm is pressed again.
    op.ctx.controller.btn_press.assert_called_once_with('xbox_a',press_time=.12)
    assert not op._business_success_seen


def test_overworld_without_success_popup_is_not_business_success():
    op=store()
    op.last_screenshot=cv2.cvtColor(cv2.imread(str(BASE/'store-counter-after-business.png')),cv2.COLOR_BGR2RGB)
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=lambda image,rect:[])
    op.check_and_update_current_screen=lambda screen,screen_name_list:'大世界-普通'
    assert op.confirm().result==R.RETRY
    op.ctx.controller.btn_press.assert_not_called()


SIM_MISSIONS=['调查专项','音擎专项','赏金专项','镀剂专项']


def test_combat_simulation_focused_tile_is_selection_without_input():
    from src.navigation.menus import combat_simulation_mission
    op=store();fixture(op,'combat-sim-mission-focus')  # Focus on 调查专项 (yellow-green border).
    assert combat_simulation_mission(op,op.last_screenshot,'调查专项',SIM_MISSIONS).is_success
    op.ctx.controller.btn_press.assert_not_called()


@pytest.mark.parametrize('target,button',[('镀剂专项','xbox_dpad_right'),('音擎专项','xbox_dpad_right')])
def test_combat_simulation_moves_focus_toward_target_tile(target,button):
    from src.navigation.menus import combat_simulation_mission
    op=store();fixture(op,'combat-sim-mission-focus')
    assert combat_simulation_mission(op,op.last_screenshot,target,SIM_MISSIONS).result==R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with(button,press_time=.12)
    op._pad_mission_steps=2*len(SIM_MISSIONS)+2
    assert combat_simulation_mission(op,op.last_screenshot,target,SIM_MISSIONS).is_fail


def test_combat_simulation_without_unique_focus_sends_nothing():
    from src.navigation.menus import combat_simulation_mission
    op=store();fixture(op,'combat-sim-mission-focus')
    op.last_screenshot[700:880,:]=30
    assert combat_simulation_mission(op,op.last_screenshot,'调查专项',SIM_MISSIONS).result==R.RETRY
    op.ctx.controller.btn_press.assert_not_called()


SKILL_MISSIONS=['刚性测试','升温测试','冰结测试','电流测试','风切测试','共鸣测试','琢光测试']  # 图鉴顺序


def test_combat_simulation_off_screen_target_searches_one_way_and_reverses_at_row_end():
    """真实画面：焦点在电流测试，风切测试不在屏上；图鉴里风切排在电流之后、共鸣之前，
    游戏行序不同。旧逻辑按图鉴序号在电流/共鸣之间来回，永远到不了风切测试。"""
    from src.navigation.menus import combat_simulation_mission
    op=store();fixture(op,'combat-sim-skill-wrap')
    assert combat_simulation_mission(op,op.last_screenshot,'风切测试',SKILL_MISSIONS).result==R.WAIT
    # 同一画面再次出现：焦点没有移动，说明已到行尾，改为反方向继续查找
    assert combat_simulation_mission(op,op.last_screenshot,'风切测试',SKILL_MISSIONS).result==R.WAIT
    assert [c.args[0] for c in op.ctx.controller.btn_press.call_args_list]==['xbox_dpad_right','xbox_dpad_left']
    op._pad_mission_steps=2*len(SKILL_MISSIONS)+2
    assert combat_simulation_mission(op,op.last_screenshot,'风切测试',SKILL_MISSIONS).is_fail


def test_combat_simulation_visible_target_uses_screen_position_not_compendium_order():
    from src.navigation.menus import combat_simulation_mission
    op=store();fixture(op,'combat-sim-skill-wrap')  # 焦点电流测试；共鸣测试在其右侧
    assert combat_simulation_mission(op,op.last_screenshot,'共鸣测试',SKILL_MISSIONS).result==R.WAIT
    assert combat_simulation_mission(op,op.last_screenshot,'刚性测试',SKILL_MISSIONS).result==R.WAIT
    assert [c.args[0] for c in op.ctx.controller.btn_press.call_args_list]==['xbox_dpad_right','xbox_dpad_left']


def test_combat_simulation_next_uses_menu_button_and_is_bounded():
    from zzz_od.operation.compendium.combat_simulation import CombatSimulation
    op=operation(CombatSimulation)
    found={'下一步'}
    op.round_by_find_area=lambda screen,screen_name,area_name: SimpleNamespace(is_success=area_name in found,status=area_name)
    for _ in range(5):
        assert op.click_next().result==R.WAIT
    assert op.click_next().is_fail
    assert [c.args[0] for c in op.ctx.controller.btn_press.call_args_list]==['xbox_start']*5
    found={'出战'}
    assert op.click_next().is_success


def test_background_back_icon_screen_uses_controller_back():
    op=operation(BackToNormalWorld);fixture(op,'combat-sim-mission-focus')
    op.check_and_update_current_screen=Mock(return_value=None)
    op._background_menu_back=0
    op.round_by_find_area=lambda screen,screen_name,area_name: SimpleNamespace(
        is_success=(screen_name,area_name)==('画面-通用','返回'),status=area_name)
    assert op.check_screen_and_run().result==R.RETRY
    op.ctx.controller.btn_press.assert_called_once_with('xbox_b',press_time=.12)


def result_op(try_next, visible):
    from zzz_od.operation.challenge_mission.check_next_after_battle import ChooseNextOrFinishAfterBattle
    op=operation(ChooseNextOrFinishAfterBattle)
    op.try_next=try_next;op.is_agent_plan=False
    op.round_by_find_area=lambda screen,screen_name,area_name: SimpleNamespace(is_success=area_name in visible,status=area_name)
    return op


@pytest.mark.parametrize('try_next,button,status',[(False,'xbox_b','战斗结果-完成'),(True,'xbox_x','战斗结果-再来一次')])
def test_battle_result_uses_controller_buttons_and_waits_for_screen_change(try_next,button,status):
    visible={'战斗结果-完成','战斗结果-再来一次'}
    op=result_op(try_next,visible)
    assert op.check_next().result==R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with(button,press_time=.12)
    visible.clear()  # Result screen left.
    result=op.check_next()
    assert result.is_success and result.status==status
    assert op.ctx.controller.btn_press.call_count==1


def test_battle_result_without_buttons_sends_nothing_and_presses_are_bounded():
    op=result_op(False,set())
    assert op.check_next().result==R.RETRY
    op.ctx.controller.btn_press.assert_not_called()
    op=result_op(False,{'战斗结果-完成','战斗结果-再来一次'})
    for _ in range(4):assert op.check_next().result==R.WAIT
    assert op.check_next().is_fail


def test_background_world_return_leaves_battle_result_with_b():
    op=operation(BackToNormalWorld);fixture(op,'battle-result-finish')
    op.check_and_update_current_screen=Mock(return_value=None)
    op._background_menu_back=0
    op.round_by_find_area=lambda screen,screen_name,area_name: SimpleNamespace(is_success=False,status=area_name)
    assert op.check_screen_and_run().result==R.RETRY
    op.ctx.controller.btn_press.assert_called_once_with('xbox_b',press_time=.12)


def test_obtained_popup_confirms_only_verified_focus():
    op=operation(BackToNormalWorld);rows=fixture(op,'combat-sim-after-result')  # 确认 focused, 前往 not.
    op.check_and_update_current_screen=Mock(return_value=None)
    op.round_by_find_area=Mock(return_value=SimpleNamespace(is_success=False))
    op._background_menu_back=0
    assert op.check_screen_and_run().result==R.RETRY
    op.ctx.controller.btn_press.assert_called_once_with('xbox_a',press_time=.12)
    op=operation(BackToNormalWorld);rows=fixture(op,'combat-sim-after-result')
    op.check_and_update_current_screen=Mock(return_value=None)
    op.round_by_find_area=Mock(return_value=SimpleNamespace(is_success=False))
    op._background_menu_back=0
    op.last_screenshot[680:780,1000:1300]=20  # 确认 no longer focused.
    assert op.check_screen_and_run().result==R.RETRY
    op.ctx.controller.btn_press.assert_called_once_with('xbox_dpad_right',press_time=.12)


def test_title_enter_uses_controller_a_in_gamepad_mode():
    from zzz_od.operation.enter_game.enter_game import EnterGame
    op=operation(EnterGame)
    op.force_login=False;op.already_login=True
    op.after_first_enter_click=op.after_second_enter_click=False
    op.resource_download_start_time=None
    op.check_game_data_updated=lambda screen,back_to_check_screen: None
    op.check_enter_click_status_text=lambda screen,include_enter_click=False: ('点击进入游戏',None)
    op.round_by_click_area=Mock(side_effect=AssertionError('window-message click is ignored on the title'))
    assert op.check_enter_click_status().result==R.WAIT
    assert op.check_enter_click_status().result==R.WAIT  # First A may only switch prompts.
    assert [c.args[0] for c in op.ctx.controller.btn_press.call_args_list]==['xbox_a','xbox_a']
    assert op.after_first_enter_click and op.after_second_enter_click


def test_controller_prompt_title_label_still_matches_enter_target():
    from onedragon.utils import str_utils
    assert str_utils.find_best_match_by_difflib('进入游戏',['点击进入游戏'])==0


def menu_context(op):
    from zzz_od.context.zzz_context import ZContext
    from onedragon.base.screen.screen_loader import ScreenContext
    loader=ScreenContext();loader.reload()
    ctx=ZContext.__new__(ZContext)
    ctx.__dict__['screen_loader']=loader
    op.ctx.screen_loader=loader
    return ctx


def test_menu_bottom_bar_target_moves_controller_focus_toward_mail():
    op=store();fixture(op,'main-menu-agent-focus')  # Focus on 代理人, 邮件 is to its left.
    ctx=menu_context(op)
    result=ctx.navigate_background_screen(op,op.last_screenshot,'邮件',current='菜单')
    assert result.result==R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_dpad_left',press_time=.12)


def test_menu_hook_leaves_screens_without_a_bottom_bar_route_alone():
    from src.navigation.menus import main_menu_target
    op=store();fixture(op,'main-menu-agent-focus')
    ctx=menu_context(op)
    for target in ('代理人','大世界-普通'):  # No 菜单 route through the bottom bar.
        assert ctx.navigate_background_screen(op,op.last_screenshot,target,current='菜单') is None
    op.ctx.controller.btn_press.assert_not_called()
    assert main_menu_target(op,'代理人').result==R.WAIT  # Focused item: confirm.
    op.ctx.controller.btn_press.assert_called_once_with('xbox_a',press_time=.12)


def test_mail_uses_controller_buttons_and_confirms_only_a_real_popup():
    from zzz_od.application.email_app.email_app import EmailApp
    op=operation(EmailApp);rows=fixture(op,'email-page')
    op.round_by_find_area=lambda screen,screen_name,area_name: SimpleNamespace(is_success=area_name=='全部领取',status=area_name)
    op.round_by_find_and_click_area=Mock(side_effect=AssertionError('the mail page ignores window-message clicks'))
    assert op.click_get_all().is_success
    op.ctx.controller.btn_press.assert_called_once_with('xbox_x',press_time=.12)
    op.ctx.controller.btn_press.reset_mock()
    assert op.click_confirm().result==R.RETRY  # Nothing claimed: no popup, no confirm.
    op.ctx.controller.btn_press.assert_not_called()
    rows.append(SimpleNamespace(data='确认',center=Rect(940,700,1000,740).center))
    assert op.click_confirm().is_success
    op.ctx.controller.btn_press.assert_called_once_with('xbox_a',press_time=.12)
    op.ctx.controller.btn_press.reset_mock()
    assert op.back_to_menu().is_success
    op.ctx.controller.btn_press.assert_called_once_with('xbox_b',press_time=.12)


def test_app_on_title_screen_is_routed_through_enter_game_without_relaunch(monkeypatch):
    from zzz_od.application.zzz_application import ZApplication, at_title_screen
    from zzz_od.operation.enter_game.open_game import OpenGame
    from onedragon.base.operation.application_base import Application
    op=operation(ZApplication)
    op.screenshot=lambda: op.last_screenshot
    words=['进入游戏']  # Controller prompts; keyboard prompts read 点击进入游戏.
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=lambda image,rect: [SimpleNamespace(data=w) for w in words])
    op.ctx.screen_loader=SimpleNamespace(get_area=lambda screen,area: SimpleNamespace(rect=Rect(700,820,1220,1032)))
    monkeypatch.setattr(Application,'check_game_window',lambda self: self.round_success())
    result=op.check_game_window()
    assert result.is_fail and result.status==ZApplication.STATUS_AT_TITLE  # -> 打开并进入游戏 edge
    words[:]=['点击进入游戏']
    assert at_title_screen(op.ctx,op.last_screenshot)
    words[:]=['菜单','邮件']
    assert op.check_game_window().is_success
    game=operation(OpenGame)
    game.ctx.controller.is_game_window_ready=True
    assert game.open_game().is_success  # Already open: no second launch.


TITLE_RECT=Rect(700,820,1220,1032)


def back_to_world_op():
    op=operation(BackToNormalWorld)
    op.handle_init()
    op.check_and_update_current_screen=Mock(return_value=None)
    op.round_by_goto_screen=lambda **_: SimpleNamespace(is_success=False,is_fail=True,status='无路径')
    op.round_by_find_area=lambda *a,**k: SimpleNamespace(is_success=False,status='')
    op.round_by_find_and_click_area=lambda *a,**k: SimpleNamespace(is_success=False,status='')
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=lambda **_: [])
    op.ctx.screen_loader=SimpleNamespace(current_screen_name=None,
        get_area=lambda screen,area: SimpleNamespace(rect=TITLE_RECT))
    op.ctx.world_patrol_service=SimpleNamespace(cut_mini_map=lambda screen: SimpleNamespace(play_mask_found=False))
    op.check_compendium=lambda screen: None
    op._check_agent_dialog=lambda screen: False
    op.round_by_click_area=Mock(side_effect=AssertionError('blind window-message click'))
    import zzz_od.operation.back_to_normal_world as module
    module.hollow_event_utils.check_in_hollow=lambda ctx,screen: None
    return op


def test_unknown_screen_in_gamepad_mode_backs_out_with_b():
    op=back_to_world_op()
    assert op.check_screen_and_run().result==R.RETRY
    op.ctx.controller.btn_press.assert_called_once_with('xbox_b',press_time=.12)


def test_title_screen_is_not_backed_out_with_b():
    op=back_to_world_op()
    title=[SimpleNamespace(data='进入游戏')]
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=lambda **k: title if k.get('rect') is TITLE_RECT else [])
    result=op.check_screen_and_run()
    assert result.is_fail and result.status=='游戏停在标题画面，先登录'
    op.ctx.controller.btn_press.assert_not_called()  # B on the title opens 退出游戏.


def title_check_app(monkeypatch, words, process):
    from zzz_od.application.zzz_application import ZApplication
    from zzz_od.operation.enter_game import game_startup
    from onedragon.base.operation.application_base import Application
    op=operation(ZApplication)
    op.screenshot=lambda: op.last_screenshot
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=lambda image,rect: [SimpleNamespace(data=w) for w in words])
    op.ctx.screen_loader=SimpleNamespace(get_area=lambda screen,area: SimpleNamespace(rect=Rect(700,820,1220,1032)))
    monkeypatch.setattr(Application,'check_game_window',lambda self: self.round_success())
    monkeypatch.setattr(game_startup,'_game_process',lambda ctx: process[0])
    return op, game_startup


def test_freshly_launched_game_enters_game_before_any_application(monkeypatch):
    process=[(4242, 12.0)]  # ok-script launched the game seconds before the task.
    op, game_startup=title_check_app(monkeypatch, [], process)
    monkeypatch.setattr(game_startup,'in_game_screen',lambda ctx,screen: False)
    result=op.check_game_window()
    assert result.is_fail and result.status==op.STATUS_STARTING  # Splash screen -> 打开并进入游戏
    from onedragon.base.operation.application_base import Application
    monkeypatch.setattr(Application,'open_and_enter_game',lambda self: self.round_success('大世界'))
    assert op.open_and_enter_game().is_success
    assert op.check_game_window().is_success  # This process reached the game; trust its screens.
    process[0]=(5151, 20.0)  # Restarted game: a new process starts over.
    assert op.check_game_window().is_fail
    process[0]=(5151, game_startup.STARTUP_SECONDS+1)  # Long-running game: unchanged behavior.
    assert op.check_game_window().is_success
    process[0]=None  # Unknown process: unchanged behavior.
    assert op.check_game_window().is_success


def test_fresh_game_already_in_a_known_screen_is_trusted(monkeypatch):
    process=[(4242, 90.0)]
    op, game_startup=title_check_app(monkeypatch, ['菜单'], process)
    monkeypatch.setattr(game_startup,'in_game_screen',lambda ctx,screen: True)
    assert op.check_game_window().is_success
    assert op.ctx.entered_game_pid==4242
    monkeypatch.setattr(game_startup,'in_game_screen',lambda ctx,screen: False)
    assert op.check_game_window().is_success


def test_title_loading_states_route_through_enter_game(monkeypatch):
    op, _=title_check_app(monkeypatch, ['版本校对中'], [None])
    result=op.check_game_window()
    assert result.is_fail and result.status==op.STATUS_AT_TITLE


def test_enter_game_waits_out_a_slow_startup(monkeypatch):
    from zzz_od.operation.enter_game.enter_game import EnterGame
    from zzz_od.operation.enter_game import game_startup
    op=operation(EnterGame)
    op.check_game_data_updated=lambda screen,back_to_check_screen: None
    op.check_enter_click_status_text=lambda screen,include_enter_click=False: (None,None)
    op.check_login_related=lambda screen: None
    op.match_login_error=lambda screen: None
    op.round_by_find_area=lambda *a,**k: SimpleNamespace(is_success=False)
    age=[30.0]
    monkeypatch.setattr(game_startup,'startup_seconds',lambda ctx: age[0])
    first=op.check_screen()
    age[0]=31.0
    second=op.check_screen()
    assert first.result==second.result==R.WAIT  # Not counted against the 60 retries.
    assert first.status!=second.status  # Keeps the background stall check from ending the wait.
    age[0]=None
    assert op.check_screen().result==R.RETRY


def test_dungeon_next_step_uses_menu_button_for_every_dungeon_type():
    from zzz_od.operation.compendium.expert_challenge import ExpertChallenge
    from zzz_od.operation.compendium.area_patrol import AreaPatrol
    from zzz_od.operation.compendium.notorious_hunt import NotoriousHunt
    for cls in (ExpertChallenge,AreaPatrol,NotoriousHunt):
        op=operation(cls)
        op.round_by_find_area=lambda screen,screen_name,area_name: SimpleNamespace(is_success=area_name=='下一步',status=area_name)
        op.round_by_find_and_click_area=Mock(side_effect=AssertionError('ignored click'))
        assert op.click_next().result==R.WAIT, cls.__name__
        op.ctx.controller.btn_press.assert_called_once_with('xbox_start',press_time=.12)


TEAMS=[f'编队{i}' for i in range(1,11)]


@pytest.mark.parametrize('target,button',[('编队1','xbox_a'),('编队2','xbox_dpad_right'),('编队3','xbox_dpad_down'),('编队4','xbox_dpad_down')])
def test_predefined_team_list_moves_focus_by_grid_and_selects_only_the_target(target,button):
    from src.navigation.menus import predefined_team
    op=store();fixture(op,'predefined-team-list')  # Focus on 编队1 (title OCR reads 编队1RS).
    result=predefined_team(op,op.last_screenshot,target,TEAMS)
    assert result.is_success==(target=='编队1')
    op.ctx.controller.btn_press.assert_called_once_with(button,press_time=.12)


def test_predefined_team_without_visible_focus_sends_nothing():
    from src.navigation.menus import predefined_team
    op=store();fixture(op,'predefined-team-list')
    op.last_screenshot[90:130,:]=20
    assert predefined_team(op,op.last_screenshot,'编队2',TEAMS).result==R.RETRY
    op.ctx.controller.btn_press.assert_not_called()


def test_deploy_reports_empty_team_popup_instead_of_success():
    from zzz_od.operation.deploy import Deploy
    op=operation(Deploy);op._deploy_requests=1
    op.round_by_find_area=lambda screen,screen_name,area_name: SimpleNamespace(is_success=False,status=area_name)
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=lambda image,rect: [SimpleNamespace(data='至少选择1位代理人出战')])
    result=op.deploy()
    assert result.is_fail and result.status==Deploy.STATUS_EMPTY_TEAM
    op.ctx.controller.btn_press.assert_called_once_with('xbox_a',press_time=.12)
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=lambda image,rect: [])
    assert op.deploy().is_success  # Screen really changed.


def test_monthly_card_is_closed_with_b_and_bounded():
    from zzz_od.operation.enter_game.enter_game import EnterGame
    op=operation(EnterGame);fixture(op,'monthly-card-popup')
    op.interact_ignore_word_list=[]
    op.round_by_find_and_click_area=lambda *a,**k: SimpleNamespace(is_success=False,status='')
    op.round_by_find_area=lambda *a,**k: SimpleNamespace(is_success=False,status='')
    rows=op.ctx.ocr_service.get_ocr_result_list(image=None,rect=Rect(0,0,1920,1080))
    from onedragon.base.matcher.match_result import MatchResult, MatchResultList
    def run_ocr(screen):
        result={}
        for r in rows:
            mrl=MatchResultList(only_best=False);mrl.append(MatchResult(1,r.center.x-10,r.center.y-10,20,20));result[str(r.data)]=mrl
        return result
    op.ctx.ocr=SimpleNamespace(run_ocr=run_ocr)
    for _ in range(6):
        assert op.check_screen_to_interact(op.last_screenshot).result==R.WAIT
    assert [c.args[0] for c in op.ctx.controller.btn_press.call_args_list]==['xbox_b']*6
    op.ctx.controller.click.assert_not_called()


def hunt_op(name,use_charge_power):
    from zzz_od.operation.compendium.notorious_hunt import NotoriousHunt
    op=operation(NotoriousHunt);fixture(op,name)
    op.use_charge_power=op.pursuit=use_charge_power
    op.plan=SimpleNamespace(plan_times=1,run_times=0,is_agent_plan=False)
    op.run_record=SimpleNamespace(left_times=3)
    op.round_by_find_area=lambda *a,**k: SimpleNamespace(is_success=False,status='')
    op.round_by_click_area=Mock(side_effect=AssertionError('ignored click'))
    return op


def test_hunt_target_page_is_recognised_on_the_current_layout():
    op=hunt_op('hunt-entry-page',False)
    assert op.wait_entry_load().status=='按钮-街区'
    assert op.wait_back_to_entry().is_success


def test_free_hunt_turns_pursuit_off_then_reads_remaining_rewards():
    from zzz_od.operation.compendium.notorious_hunt import NotoriousHunt
    op=hunt_op('hunt-entry-page',False)  # 深度追猎 ON
    assert op.decide_notorious_hunt().result==R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_r_thumb',press_time=.12)
    op=hunt_op('hunt-entry-pursuit-toggle',False)  # OFF, 剩余奖励次数 0/3
    result=op.decide_notorious_hunt()
    assert result.status==NotoriousHunt.STATUS_NO_LEFT_TIMES and op.run_record.left_times==0
    op.ctx.controller.btn_press.assert_not_called()


def test_pursuit_hunt_switches_on_and_confirms_energy_prompt():
    from zzz_od.operation.compendium.notorious_hunt import NotoriousHunt
    op=hunt_op('hunt-entry-pursuit-toggle',True)  # OFF
    assert op.decide_by_use_power().result==R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_r_thumb',press_time=.12)
    op=hunt_op('hunt-entry-pursuit-on',True)  # "免费挑战次数已用尽" prompt
    assert op.decide_by_use_power().result==R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_a',press_time=.12)
    op=hunt_op('hunt-entry-page',True)  # ON
    assert op.decide_by_use_power().status==NotoriousHunt.STATUS_NO_LEFT_TIMES


def test_energy_plan_spends_free_rewards_first_when_pursuit_is_not_offered():
    from zzz_od.operation.compendium.notorious_hunt import NotoriousHunt
    op=hunt_op('hunt-entry-free-rewards',True)  # 剩余奖励次数 3/3; no 深度追猎 toggle on the page.
    op.plan.plan_times=2
    result=op.decide_by_use_power()
    assert result.status==NotoriousHunt.STATUS_WITH_LEFT_TIMES  # Used to be 本次跳过深度追猎.
    assert not op.pursuit and op.can_run_times==2 and op.run_record.left_times==3
    op.ctx.controller.btn_press.assert_not_called()


def test_free_hunt_restart_confirms_with_a_once_and_waits_for_the_dialog_to_close():
    op=hunt_op('hunt-restart-confirm',False)  # 是否消耗1次奖励次数，再次挑战「恶名狩猎」, 确认 focused
    op.round_by_find_and_click_area=Mock(side_effect=AssertionError('ignored click'))
    assert op.restart_confirm().result==R.WAIT
    assert op.restart_confirm().result==R.WAIT  # Still open: no second press.
    op.ctx.controller.btn_press.assert_called_once_with('xbox_a',press_time=.12)
    op.last_screenshot=op.last_screenshot*0
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=lambda image,rect,**_: [])
    assert op.restart_confirm().is_success


def test_free_hunt_restart_needs_the_focused_confirm():
    op=hunt_op('hunt-restart-confirm',False)
    op.last_screenshot[590:665,965:1260]=20  # 确认 without its focus fill.
    assert op.restart_confirm().result==R.RETRY
    op.ctx.controller.btn_press.assert_not_called()


def test_energy_plan_keeps_pursuit_when_free_rewards_are_spent():
    op=hunt_op('hunt-entry-pursuit-toggle',True)  # 剩余奖励次数 0/3, toggle OFF
    assert op.decide_by_use_power().result==R.WAIT and op.pursuit
    op.ctx.controller.btn_press.assert_called_once_with('xbox_r_thumb',press_time=.12)


def test_hunt_weekly_rewards_use_x_for_panel_and_claim():
    from zzz_od.application.notorious_hunt.notorious_hunt_app import NotoriousHuntApp
    op=operation(NotoriousHuntApp);fixture(op,'hunt-entry-pursuit-toggle')
    op.round_by_click_area=Mock(side_effect=AssertionError('ignored click'))
    op.round_by_find_and_click_area=Mock(side_effect=AssertionError('ignored click'))
    assert op.click_reward_entry().result==R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_x',press_time=.12)
    op.ctx.controller.btn_press.reset_mock()
    fixture(op,'hunt-reward-panel')
    assert op.click_reward_entry().is_success
    op.ctx.controller.btn_press.assert_not_called()
    op.round_by_find_area=lambda screen,screen_name,area_name: SimpleNamespace(is_success=area_name=='全部领取',status=area_name)
    assert op.claim_all().is_success
    op.ctx.controller.btn_press.assert_called_once_with('xbox_x',press_time=.12)


def test_labelled_button_press_reads_the_glyph_next_to_the_label():
    from src.navigation.menus import press_labelled
    op=store();fixture(op,'hunt-battle-failed')  # 「B 退出」
    assert press_labelled(op,op.last_screenshot,'退出',Rect(1400,980,1900,1070))=='b'
    op.ctx.controller.btn_press.assert_called_once_with('xbox_b',press_time=.12)
    op.ctx.controller.btn_press.reset_mock()
    assert press_labelled(op,op.last_screenshot,'撤退',Rect(400,800,1500,960)) is None
    op.ctx.controller.btn_press.assert_not_called()


def test_lost_hunt_retreats_once_instead_of_rewinding_forever():
    from zzz_od.operation.compendium.notorious_hunt import NotoriousHunt
    op=operation(NotoriousHunt);rows=fixture(op,'hunt-battle-failed')
    op.round_by_find_and_click_area=Mock(side_effect=AssertionError('ignored click'))
    assert op.battle_fail().result==R.RETRY  # No 撤退 on screen: nothing pressed, no fake success.
    op.ctx.controller.btn_press.assert_not_called()
    rows+= [SimpleNamespace(data='X',center=Rect(560,866,580,890).center),SimpleNamespace(data='撤退',center=Rect(620,862,700,894).center),
            SimpleNamespace(data='A',center=Rect(900,866,920,890).center),SimpleNamespace(data='倒带',center=Rect(960,862,1040,894).center)]
    result=op.battle_fail()
    assert result.is_success and result.status=='战斗结果-撤退'
    op.ctx.controller.btn_press.assert_called_once_with('xbox_x',press_time=.12)
    assert op.battle_fail_exit().is_fail


def test_world_return_leaves_defeat_result_with_its_labelled_button():
    op=operation(BackToNormalWorld);fixture(op,'hunt-battle-failed')
    op.handle_init()
    op.check_and_update_current_screen=Mock(return_value=None)
    op.round_by_goto_screen=lambda **_: SimpleNamespace(is_success=False,is_fail=True,status='')
    op.round_by_find_area=lambda *a,**k: SimpleNamespace(is_success=False,status='')
    op.round_by_find_and_click_area=Mock(side_effect=AssertionError('ignored click'))
    op.ctx.screen_loader=SimpleNamespace(current_screen_name=None)
    op.ctx.world_patrol_service=SimpleNamespace(cut_mini_map=lambda screen: SimpleNamespace(play_mask_found=False))
    assert op.check_screen_and_run().result==R.RETRY
    op.ctx.controller.btn_press.assert_called_once_with('xbox_b',press_time=.12)


@pytest.mark.parametrize('level,button',[('等级Lv.50','xbox_dpad_up'),('等级Lv.65','xbox_a')])
def test_hunt_level_list_moves_focus_and_applies_target(level,button):
    op=hunt_op('hunt-level-dropdown',True)  # List open, focus on Lv.65.
    op.plan.level=level
    assert op.choose_level().result==R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with(button,press_time=.12)


def test_hunt_level_opens_list_with_ls_and_accepts_verified_header():
    op=hunt_op('hunt-entry-page',True)  # Header shows 等级Lv.65, list closed.
    op.plan.level='等级Lv.50'
    assert op.choose_level().result==R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_l_thumb',press_time=.12)
    op=hunt_op('hunt-entry-page',True);op.plan.level='等级Lv.65'
    assert op.choose_level().is_success


def test_function_menu_grid_moves_outline_and_opens_target():
    from src.navigation.menus import grid_target
    op=store();fixture(op,'function-menu-focus')  # Outline on 站点; 情报板 to its right.
    rect=Rect(1240,240,1900,1000)
    assert grid_target(op,op.last_screenshot,'情报板',rect).result==R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_dpad_right',press_time=.12)
    op=store();fixture(op,'function-menu-focus')
    assert grid_target(op,op.last_screenshot,'站点',rect).is_success
    op.ctx.controller.btn_press.assert_called_once_with('xbox_a',press_time=.12)
    op=store();fixture(op,'function-menu-keyboard')  # Keyboard prompts: no outline yet.
    assert grid_target(op,op.last_screenshot,'情报板',rect).result==R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_dpad_down',press_time=.12)


def test_intel_board_without_site_stops_with_reason():
    from zzz_od.application.intel_board.intel_board_app import IntelBoardApp
    op=operation(IntelBoardApp);fixture(op,'intel-board-list')
    result=op.open_filter()
    assert result.is_fail and result.status==IntelBoardApp.STATUS_NO_SITE
    op.ctx.controller.btn_press.assert_not_called()


def test_combat_tab_category_moves_down_to_shiyu_and_waits_while_list_settles():
    op=store();fixture(op,'compendium-combat-tab-shiyu')
    assert compendium_category(op,op.last_screenshot,'式舆防卫战').result==R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_dpad_down',press_time=.12)
    op=store();fixture(op,'compendium-combat-tab-shiyu')
    op.last_screenshot[300:440,160:440]=60  # Selection not drawn yet (list animating).
    for _ in range(6):
        assert compendium_category(op,op.last_screenshot,'式舆防卫战').result==R.WAIT
    assert compendium_category(op,op.last_screenshot,'式舆防卫战').result==R.RETRY
    op.ctx.controller.btn_press.assert_not_called()


def test_category_match_tolerates_one_misread_glyph():
    op=store();rows=fixture(op,'compendium-combat-tab-shiyu')
    for r in rows:
        if r.data=='式舆防卫战': r.data='式奥防卫战'
    assert compendium_category(op,op.last_screenshot,'式舆防卫战').result==R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_dpad_down',press_time=.12)
    op.ctx.controller.btn_press.reset_mock()
    assert compendium_category(op,op.last_screenshot,'周期征讨').is_success  # Exact names still win.


def test_missing_card_failure_lists_the_cards_seen():
    op=store();fixture(op,'compendium-shiyu-cards-top')
    op._pad_card_steps=30
    result=compendium_card(op,op.last_screenshot,lambda t: t=='剧变节点','剧变节点')
    assert result.is_fail and '稳定节点' in result.status and '纷争节点' in result.status
