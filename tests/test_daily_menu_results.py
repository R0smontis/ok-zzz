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
from src.navigation.menus import compendium_category, compendium_lost_void, lost_void_gateway

BASE=Path(__file__).parent/'fixtures/daily_map'

def fixture(op,name):
    op.last_screenshot=cv2.cvtColor(cv2.imread(str(BASE/f'{name}.png')),cv2.COLOR_BGR2RGB)
    data=json.loads((BASE/f'{name}.json').read_text(encoding='utf-8'))
    rows=[SimpleNamespace(data=r['text'],center=Rect(r['rect'][0],r['rect'][1],r['rect'][0]+r['rect'][2],r['rect'][1]+r['rect'][3]).center) for r in data['result']['ocr']]
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=lambda image,rect: [r for r in rows if rect.x1<=r.center.x<rect.x2 and rect.y1<=r.center.y<rect.y2])
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
    assert compendium_category(op,op.last_screenshot,'周期征讨').result==R.RETRY
    op.ctx.controller.btn_press.assert_called_once_with('xbox_dpad_up',press_time=.12)
    op.ctx.controller.btn_press.reset_mock()
    fixture(op,'compendium-periodic-select')
    assert compendium_category(op,op.last_screenshot,'周期征讨').is_success
    op.ctx.controller.btn_press.assert_not_called()


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
