"""开场实机画面：A继续、黄色事件焦点、免费鸣徽优先级，不发送真实输入。"""
import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import pytest

from onedragon.base.geometry.rectangle import Rect
from onedragon.base.matcher.match_result import MatchResult
from onedragon.base.operation.operation_round_result import OperationRoundResultEnum as R
from src.navigation.hollow_events import advance_dialogue, event_option, free_resonium, pending_option
from zzz_od.hollow_zero.event.choose_resonium import ChooseResonium
from zzz_od.hollow_zero.event.resonium_utils import choose_resonium_by_priority
from zzz_od.hollow_zero.game_data.hollow_zero_resonium import Resonium
from zzz_od.hollow_zero.hollow_zero_data_service import HallowZeroDataService
from test_lost_void_background_menus import operation

BASE = Path(__file__).parent / 'fixtures/withered'
SERVICE = HallowZeroDataService()
SERVICE.reload()


def frame(name, op=None):
    op = op or operation(ChooseResonium)
    image = cv2.cvtColor(cv2.imread(str(BASE / f'{name}.png')), cv2.COLOR_BGR2RGB)
    payload = json.loads((BASE / f'{name}.json').read_text(encoding='utf-8'))
    rows = [MatchResult(1, *r['rect'], data=r['text']) for r in payload['result']['ocr']]
    op.ctx.ocr_service = SimpleNamespace(get_ocr_result_list=lambda image, rect: [
        row for row in rows if rect.x1 <= row.center.x < rect.x2 and rect.y1 <= row.center.y < rect.y2])
    op.ctx.withered_domain = SimpleNamespace(data_service=SERVICE,
        challenge_config=SimpleNamespace(resonium_priority=['冻结', '闪避', '能量']))
    op.last_screenshot = image
    return op, image, rows


def pressed(op):
    return [call.args[0] for call in op.ctx.controller.btn_press.call_args_list]


def test_dialogue_advances_only_with_verified_right_paragraph_a():
    op, image, _ = frame('hollow-board-map-ready')
    assert advance_dialogue(op, image).result == R.RETRY and pressed(op) == []
    _, paragraph, _ = frame('hollow-opening-paragraph', op)
    assert advance_dialogue(op, paragraph).result == R.WAIT
    assert pressed(op) == ['xbox_a']


def test_unknown_highlighted_option_is_not_paragraph_continuation():
    op, image, _ = frame('hollow-researcher-menu')
    assert advance_dialogue(op, image).result == R.RETRY
    assert pressed(op) == []


def test_configured_event_option_uses_unique_focus_and_waits_for_real_result():
    op, image, rows = frame('hollow-researcher-menu')
    wanted = next(row for row in rows if row.data == '接受他的好意')
    assert event_option(op, image, wanted.data, wanted.rect).result == R.WAIT
    assert pressed(op) == ['xbox_a']
    assert pending_option(op, image).result == R.WAIT
    _, next_image, _ = frame('hollow-opening-reward', op)
    assert pending_option(op, next_image).result == R.WAIT
    assert pending_option(op, next_image).is_success
    assert pressed(op) == ['xbox_a']


def test_nonfocused_event_option_moves_without_confirming():
    op, image, rows = frame('hollow-researcher-menu')
    wanted = next(row for row in rows if row.data == '拒绝他的好意')
    assert event_option(op, image, wanted.data, wanted.rect).result == R.WAIT
    assert pressed(op) == ['xbox_dpad_down']


def test_free_card_selection_follows_category_priority_then_verifies_change():
    op, image, _ = frame('hollow-board-initial')
    assert free_resonium(op, image).result == R.WAIT
    assert pressed(op) == ['xbox_dpad_right']  # 顽强 → 冻结
    _, image, _ = frame('hollow-freeze-focus', op)
    assert free_resonium(op, image).result == R.WAIT
    assert pressed(op)[-1] == 'xbox_a'
    _, image, _ = frame('hollow-researcher-menu', op)
    assert free_resonium(op, image).result == R.WAIT
    assert free_resonium(op, image).is_success
    assert op._pad_resonium_pending is None


def test_corruption_locked_cards_are_not_candidates():
    op, image, _ = frame('hollow-gift-choice')
    assert free_resonium(op, image).result == R.WAIT
    assert pressed(op) == ['xbox_a']  # Only 冻结 冰屑枪 is available and focused.


def test_named_priority_matches_name_after_category_and_includes_ss():
    items = [Resonium('诡术', '其它', 'SS'), Resonium('诡术', '华丽手杖', 'SS'),
             Resonium('冻结', '冰屑枪', 'A')]
    assert choose_resonium_by_priority(items, ['诡术 华丽手杖']) == [1, 0, 2]
    assert choose_resonium_by_priority(items, ['诡术 华丽手杖'], only_priority=True) == [1]


def test_clear_corruption_sends_a_once_and_requires_actual_panel_close():
    from src.navigation.hollow_events import remove_corruption
    op, image, _ = frame('hollow-single-blocked')
    op.round_by_find_area = lambda *args: op.round_success('背包')
    assert remove_corruption(op, image).result == R.WAIT
    assert pressed(op) == ['xbox_a']
    assert remove_corruption(op, image).result == R.WAIT
    _, image, _ = frame('hollow-clear-accepted', op)
    assert remove_corruption(op, image).result == R.WAIT
    assert remove_corruption(op, image).is_success
    assert pressed(op) == ['xbox_a']


def test_ignored_clear_never_reports_success_or_repeats_the_click():
    from src.navigation.hollow_events import remove_corruption
    op, image, _ = frame('hollow-single-blocked')
    assert remove_corruption(op, image).result == R.WAIT
    for _ in range(5):
        assert remove_corruption(op, image).result == R.WAIT
    assert remove_corruption(op, image).is_fail
    assert pressed(op) == ['xbox_a']
    op.ctx.controller.click.assert_not_called()


def test_non_resonium_cards_fall_back_to_the_focused_card_and_verify_change():
    from src.navigation.hollow_events import default_card
    op, image, _ = frame('hollow-assist-bangboo')
    assert free_resonium(op, image).result == R.RETRY and pressed(op) == []
    assert default_card(op, image).result == R.WAIT
    assert pressed(op) == ['xbox_a']
    assert default_card(op, image).result == R.WAIT
    _, image, _ = frame('hollow-resumed-board', op)
    assert default_card(op, image).result == R.WAIT
    assert default_card(op, image).is_success
    assert pressed(op) == ['xbox_a']


def test_fallback_needs_cards_and_a_prompt():
    from src.navigation.hollow_events import default_card
    op, image, _ = frame('hollow-resumed-board')
    assert default_card(op, image).result == R.RETRY and pressed(op) == []


def test_swift_supply_moves_to_stress_button_then_confirms_once():
    from src.navigation.hollow_events import bottom_button
    op, image, _ = frame('hollow-swift-supply')
    assert bottom_button(op, image, ['降低压力值']).result == R.WAIT
    assert pressed(op) == ['xbox_dpad_right']  # 回复生命值 is focused
    op2, image, _ = frame('hollow-swift-supply')
    assert bottom_button(op2, image, ['回复生命值']).result == R.WAIT
    assert pressed(op2) == ['xbox_a']
    assert bottom_button(op2, image, ['回复生命值']).result == R.WAIT
    _, image, _ = frame('hollow-resumed-board', op2)
    assert bottom_button(op2, image, ['回复生命值']).result == R.WAIT
    assert bottom_button(op2, image, ['回复生命值']).status == '回复生命值'
    assert pressed(op2) == ['xbox_a']


def test_bottom_button_ignored_confirm_fails_without_repeating():
    from src.navigation.hollow_events import bottom_button
    op, image, _ = frame('hollow-swift-supply')
    bottom_button(op, image, ['回复生命值'])
    results = [bottom_button(op, image, ['回复生命值']) for _ in range(8)]
    assert results[-1].is_fail and pressed(op) == ['xbox_a', 'xbox_a']


def test_swift_supply_handler_uses_pad_in_background():
    from zzz_od.hollow_zero.event.swift_supply import SwiftSupply
    op, image, _ = frame('hollow-swift-supply', operation(SwiftSupply))
    op.ctx.controller.background_mode = True
    assert op.choose_one().result == R.WAIT
    assert pressed(op) == ['xbox_dpad_right']
    op.ctx.controller.click.assert_not_called()


def test_drop_picks_least_wanted_card():
    from src.navigation.hollow_events import resonium_card
    op, image, _ = frame('hollow-board-initial')  # 顽强 focused; priority 冻结 > 闪避 > 能量
    assert resonium_card(op, image, '选择', lowest=True).result == R.WAIT
    # lowest of the visible cards is 顽强 (not in priority) — already focused, so A
    assert pressed(op) == ['xbox_a']


def test_option_reports_the_matched_word():
    from src.navigation.hollow_events import pad_option
    op, image, _ = frame('hollow-researcher-menu')
    assert pad_option(op, image, ['接受他的好意', '拒绝他的好意']).result == R.WAIT
    assert pressed(op) == ['xbox_a']  # 接受他的好意 is the focused option
    assert op._pad_event_pending['status'] == '接受他的好意'
    op2, image, _ = frame('hollow-researcher-menu')
    assert pad_option(op2, image, ['拒绝他的好意', '接受他的好意']).result == R.WAIT
    assert pressed(op2) == ['xbox_dpad_down']


def test_challenge_result_is_confirmed_with_a_and_verified_closed():
    from src.navigation.hollow_events import result_confirm
    op, image, _ = frame('hollow-challenge-result')
    assert result_confirm(op, image).result == R.WAIT
    assert pressed(op) == ['xbox_a']
    assert result_confirm(op, image).result == R.WAIT
    _, image, _ = frame('hollow-resumed-board', op)
    assert result_confirm(op, image).result == R.WAIT
    assert result_confirm(op, image).is_success
    assert pressed(op) == ['xbox_a']


def test_challenge_result_ignored_press_gets_one_spaced_retry_then_fails():
    from src.navigation.hollow_events import result_confirm
    op, image, _ = frame('hollow-challenge-result')
    result_confirm(op, image)
    results = [result_confirm(op, image) for _ in range(8)]
    assert results[-1].is_fail
    assert pressed(op) == ['xbox_a'] * 2


def test_result_confirm_needs_the_result_screen():
    from src.navigation.hollow_events import result_confirm
    op, image, _ = frame('hollow-swift-supply')
    assert result_confirm(op, image).result == R.RETRY and pressed(op) == []


def test_prompt_label_alone_locates_the_focused_card_when_ocr_drops_the_glyph():
    op, image, rows = frame('hollow-gate-resonium')
    kept = [r for r in rows if r.data not in ('A', 'Ａ')]
    op.ctx.ocr_service = SimpleNamespace(get_ocr_result_list=lambda image, rect: [
        row for row in kept if rect.x1 <= row.center.x < rect.x2 and rect.y1 <= row.center.y < rect.y2])
    assert free_resonium(op, image).result == R.WAIT
    assert pressed(op) == ['xbox_a']  # 冻结 is first in priority and focused on the left


def test_obtain_popup_matched_as_choice_confirms_its_focused_button():
    op, image, _ = frame('hollow-obtain-popup')
    op.ctx.controller.background_mode = True
    assert op.choose_one().result == R.RETRY
    assert op.choose_default().result == R.WAIT
    assert pressed(op) == ['xbox_a']
    assert op.choose_default().result == R.WAIT
    _, op.last_screenshot, _ = frame('hollow-resumed-board', op)
    op.choose_default()
    assert op.choose_default().is_success
    assert pressed(op) == ['xbox_a']


def test_runner_confirms_a_focused_popup_instead_of_blind_blank_click():
    from zzz_od.hollow_zero.hollow_runner import HollowRunner
    op, image, _ = frame('hollow-corruption-popup', operation(HollowRunner))
    op.ctx.controller.background_mode = True
    assert op._tap_blank().result == R.WAIT
    assert pressed(op) == ['xbox_a']
    op.ctx.controller.click.assert_not_called()
    op2, image, _ = frame('hollow-resumed-board', operation(HollowRunner))
    op2.ctx.controller.background_mode = True
    assert op2._tap_blank() is None and pressed(op2) == []


def test_exit_menu_opens_with_start_then_abandons_with_y():
    from src.navigation.hollow_events import exit_abandon, exit_open_menu
    op, image, _ = frame('hollow-resumed-board')
    assert exit_open_menu(op, image).result == R.WAIT
    assert pressed(op) == ['xbox_start']
    _, image, _ = frame('hollow-exit-menu', op)
    assert exit_open_menu(op, image).is_success
    assert exit_abandon(op, image).result == R.WAIT
    assert pressed(op) == ['xbox_start', 'xbox_y']


def test_exit_confirm_needs_a_dialog():
    from src.navigation.hollow_events import exit_confirm
    op, image, _ = frame('hollow-exit-menu')
    assert exit_confirm(op, image).result == R.RETRY and pressed(op) == []


def test_loot_confirm_button_below_the_card_is_confirmed():
    from zzz_od.hollow_zero.event.confirm_resonium import ConfirmResonium
    op, image, _ = frame('hollow-loot-confirm', operation(ConfirmResonium))
    op.ctx.controller.background_mode = True
    assert op.choose_one().result == R.WAIT
    assert pressed(op) == ['xbox_a']


def test_grey_disabled_option_is_not_a_candidate():
    from src.navigation.hollow_events import option_enabled
    _, image, rows = frame('hollow-door-disabled-option')
    by = {r.data: r.rect for r in rows}
    assert not option_enabled(image, by['接受检疫扫描'])
    assert option_enabled(image, by['强行闯入通道'])
    assert option_enabled(image, by['暂时离开'])  # focused
    assert option_enabled(image, by['异化检疫门'])


def test_top_focused_option_of_four_is_found_and_greyed_ones_skipped():
    from src.navigation.hollow_events import _event_focus, option_enabled
    _, image, rows = frame('hollow-four-options')
    focus = _event_focus(image)
    assert focus is not None and focus.y1 < 440 < focus.y2
    by = {r.data: r.rect for r in rows}
    first = next(rect for text, rect in by.items() if '1号' in text)
    second = next(rect for text, rect in by.items() if '2号' in text)
    assert option_enabled(image, first) and not option_enabled(image, second)


def test_shop_menu_trade_option_is_focused_and_confirmed_with_a():
    from src.navigation.hollow_events import pad_option
    op, image, _ = frame('hollow-shop-menu')
    assert pad_option(op, image, ['鸣徽交易', '特价折扣']).result == R.WAIT
    assert pressed(op) == ['xbox_a']


def test_shop_list_reads_items_prices_coins_and_focus():
    from src.navigation.hollow_events import shop_coins, shop_focus_y, shop_items
    op, image, _ = frame('hollow-shop-list')
    items = shop_items(op, image)
    names = [(item.category, item.name) if item else None for _, item, _ in items]
    assert ('能量', '白仔益生菌') in names and all(n is not None for n in names)  # 急救箱 is 求救箱 in the game data
    assert [price for _, _, price in items] == [600, 1000, 2000]
    assert shop_coins(op, image) == 2403
    assert abs(shop_focus_y(op, image) - 277) < 20


def test_shop_moves_to_the_priority_item_without_buying():
    from src.navigation.hollow_events import shop_choose
    op, image, _ = frame('hollow-shop-list')
    assert shop_choose(op, image, ['顽强'], True).result == R.WAIT
    assert pressed(op) == ['xbox_dpad_down']
    op2, image, _ = frame('hollow-shop-list')
    assert shop_choose(op2, image, ['能量'], True).is_success and pressed(op2) == []


def test_shop_skips_unwanted_items():
    from src.navigation.hollow_events import shop_choose
    op, image, _ = frame('hollow-shop-list')
    assert shop_choose(op, image, ['冻结'], True).status == '不购买' and pressed(op) == []


def test_shop_buy_presses_a_once_and_needs_a_visible_change():
    from src.navigation.hollow_events import shop_buy
    op, image, _ = frame('hollow-shop-list')
    assert shop_buy(op, image).result == R.WAIT
    results = [shop_buy(op, image) for _ in range(6)]
    assert results[-1].is_fail and pressed(op) == ['xbox_a']


def test_shop_leave_backs_out_until_the_board():
    from src.navigation.hollow_events import shop_leave
    op, image, _ = frame('hollow-shop-list')
    assert shop_leave(op, image).result == R.WAIT and pressed(op) == ['xbox_b']
    _, image, _ = frame('hollow-shop-menu', op)
    assert shop_leave(op, image).result == R.WAIT and pressed(op) == ['xbox_b', 'xbox_b']
    _, image, _ = frame('hollow-resumed-board', op)
    assert shop_leave(op, image).is_success


def test_shop_focus_comes_from_the_card_outline_without_the_a_glyph():
    from src.navigation.hollow_events import shop_focus_y
    op, image, rows = frame('hollow-shop-list-2')
    kept = [r for r in rows if r.data not in ('A', 'Ａ')]
    op.ctx.ocr_service = SimpleNamespace(get_ocr_result_list=lambda image, rect: [
        r for r in kept if rect.x1 <= r.center.x < rect.x2 and rect.y1 <= r.center.y < rect.y2])
    assert abs(shop_focus_y(op, image) - 277) < 20


@pytest.mark.parametrize('missing', ['coins', 'price'])
def test_shop_never_buys_with_an_unverified_budget(missing):
    from src.navigation.hollow_events import shop_buy, shop_choose
    op, image, rows = frame('hollow-shop-list')
    kept = [r for r in rows if not (r.data == '2403' if missing == 'coins' else r.data == '600')]
    op.ctx.ocr_service = SimpleNamespace(get_ocr_result_list=lambda image, rect: [
        r for r in kept if rect.x1 <= r.center.x < rect.x2 and rect.y1 <= r.center.y < rect.y2])
    assert shop_buy(op, image).result == R.RETRY
    assert pressed(op) == []
    if missing == 'coins':
        assert shop_choose(op, image, ['能量'], True).result == R.RETRY
