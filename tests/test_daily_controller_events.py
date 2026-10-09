from types import SimpleNamespace
from unittest.mock import Mock
from src.live.runtime import runtime_xbox_pad
from zzz_od.application.hou_hou_bakery.hou_hou_bakery_app import HouHouBakeryApp
from onedragon.base.operation.operation_round_result import OperationRoundResult, OperationRoundResultEnum as R
from test_lost_void_background_menus import operation
from zzz_od.operation.back_to_normal_world import BackToNormalWorld


def test_debug_leases_reuse_application_gamepad_instead_of_creating_xinput_slots():
    pad=object()
    controller=SimpleNamespace(xbox_controller=None)
    def enable():controller.xbox_controller=pad
    controller.enable_xbox=Mock(side_effect=enable)
    ctx=SimpleNamespace(controller=controller,init_controller=Mock())
    for _ in range(8):assert runtime_xbox_pad(ctx) is pad
    assert controller.enable_xbox.call_count==1
    ctx.init_controller.assert_not_called()


def test_first_debug_control_initializes_controller_without_activating_foreground():
    pad=object();ctx=SimpleNamespace(controller=None)
    def initialize(activate):
        assert activate is False
        ctx.controller=SimpleNamespace(xbox_controller=pad,enable_xbox=Mock())
    ctx.init_controller=Mock(side_effect=initialize)
    assert runtime_xbox_pad(ctx) is pad
    ctx.init_controller.assert_called_once_with(activate=False)
    ctx.controller.enable_xbox.assert_not_called()


def bakery(words):
    op=operation(HouHouBakeryApp);op.claimed=False
    op.round_by_ocr=lambda image,word:OperationRoundResult(R.SUCCESS if word in words else R.RETRY)
    return op


def test_bakery_continue_is_only_pressed_after_verified_box_open():
    words={'继续'};op=bakery(words)
    assert op.collect().result==R.RETRY
    op.ctx.controller.btn_press.assert_not_called()
    words.clear();words.add('每日可领取一次')
    assert op.collect().result==R.RETRY
    assert op._background_box_open
    words.clear();words.add('继续')
    assert op.collect().result==R.RETRY
    assert op.ctx.controller.btn_press.call_count==2
    assert not op.claimed
    words.clear();words.add('确认')
    assert op.collect().result==R.RETRY
    assert op.claimed
    words.clear();words.add('同类型奖励')
    assert op.collect().is_success
    assert op.ctx.controller.btn_press.call_count==3


def test_bakery_already_claimed_never_repeats_reward_confirmation():
    op=bakery({'同类型奖励','确认'})
    assert op.collect().is_success
    assert not op.claimed
    op.ctx.controller.btn_press.assert_not_called()


def test_bakery_current_daily_one_portion_label_opens_without_exchange():
    op=bakery({'每日可领取一份','集卡兑换'})
    assert op.collect().result==R.RETRY
    assert op._background_box_open
    op.ctx.controller.btn_press.assert_called_once_with('xbox_a',press_time=.12)
    assert not op.claimed


def test_bakery_menu_without_back_footer_returns_with_b_and_bounds_attempts():
    op=operation(BackToNormalWorld)
    op.check_and_update_current_screen=Mock(return_value=None)
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=lambda **_: [
        SimpleNamespace(data=w) for w in ('集卡兑换','选择盲盒（每日可领取一份）')])
    for _ in range(6):assert op.check_screen_and_run().result==R.RETRY
    assert op.check_screen_and_run().is_fail
    assert op.ctx.controller.btn_press.call_count==6


def test_bakery_claimed_menu_returns_without_missing_select_box_label():
    op=operation(BackToNormalWorld)
    op.check_and_update_current_screen=Mock(return_value=None)
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=lambda **_: [
        SimpleNamespace(data=w) for w in ('集卡兑换','今日已领取同类型奖励')])
    assert op.check_screen_and_run().result==R.RETRY
    op.ctx.controller.btn_press.assert_called_once_with('xbox_b',press_time=.12)
    assert all(c.args==('xbox_b',) for c in op.ctx.controller.btn_press.call_args_list)
    op.check_and_update_current_screen.return_value='大世界-普通'
    assert op.check_screen_and_run().is_success
    assert op.ctx.controller.btn_press.call_count==1
