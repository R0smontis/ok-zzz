"""快捷导航 teleports by point name; every press follows a focus verified on a real frame."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from onedragon.base.operation.operation_round_result import OperationRoundResultEnum as R
from src.navigation.map import quick_nav, quick_nav_state
from zzz_od.operation.transport import Transport
from test_background_map_navigation import fixture


def pressed(op):
    return [call.args[0] for call in op.ctx.controller.btn_press.call_args_list]


def test_real_quick_nav_page_reads_focused_region_and_its_points():
    op, screen = fixture('map-quick-nav', '澄辉坪', '随便观')
    state = quick_nav_state(op, screen)
    assert [name for name, _, lit in state['tiles'] if lit] == ['布亚斯特城区']
    assert len(state['tiles']) == 9 and not any(lit for _, _, lit in state['points'])
    op, screen = fixture('map-quick-nav-region', '澄辉坪', '随便观')
    state = quick_nav_state(op, screen)
    assert [name for name, _, lit in state['tiles'] if lit] == ['澄辉坪']
    assert [name for name, _, lit in state['points'] if lit] == ['随便观']
    assert [name for name, _, _ in state['points']][-1] == '随便观外庭'


def test_region_focus_moves_toward_target_then_selects_it():
    op, screen = fixture('map-quick-nav', '澄辉坪', '随便观')
    assert quick_nav(op, screen).result == R.WAIT
    assert pressed(op) == ['xbox_dpad_right']
    op, screen = fixture('map-quick-nav', '录像店', '录像店营业点')
    quick_nav(op, screen)
    assert pressed(op) == ['xbox_dpad_down']
    op, screen = fixture('map-quick-nav', '布亚斯特城区', '片刻闲')
    quick_nav(op, screen)
    assert pressed(op) == ['xbox_a']


def test_point_strip_presses_only_the_verified_target_point():
    op, screen = fixture('map-quick-nav-region', '澄辉坪', '随便观')
    assert quick_nav(op, screen).result == R.WAIT
    assert pressed(op) == ['xbox_a'] and op._quick_nav_chosen == '随便观'
    op, screen = fixture('map-quick-nav-region', '澄辉坪', '饮茶仙')
    quick_nav(op, screen)
    assert pressed(op) == ['xbox_dpad_right'] and op._quick_nav_chosen is None


def test_points_of_another_region_return_to_region_choice():
    op, screen = fixture('map-quick-nav-region', '六分街', '随便观')
    quick_nav(op, screen)
    assert pressed(op) == ['xbox_b']


def test_missing_point_sweeps_both_ways_then_fails_without_choosing():
    op, screen = fixture('map-quick-nav-region', '澄辉坪', '不存在的点')
    results = [quick_nav(op, screen) for _ in range(13)]
    assert results[-1].is_fail and all(r.result == R.WAIT for r in results[:-1])
    assert set(pressed(op)) == {'xbox_dpad_right', 'xbox_dpad_left'} and 'xbox_a' not in pressed(op)


def test_unknown_region_fails_without_input():
    op, screen = fixture('map-quick-nav', '不存在的区域', '随便观')
    assert quick_nav(op, screen).is_fail
    op.ctx.controller.btn_press.assert_not_called()


def test_teleport_dialog_is_confirmed_only_after_the_verified_point_press():
    op, screen = fixture('map-quick-nav-point', '澄辉坪', '随便观')
    assert quick_nav_state(op, screen) == {'dialog': True, 'confirm_focused': True}
    quick_nav(op, screen)
    assert pressed(op) == ['xbox_b']
    op, screen = fixture('map-quick-nav-point', '澄辉坪', '随便观')
    op._quick_nav_chosen = '随便观'
    for _ in range(3):
        assert quick_nav(op, screen).result == R.WAIT
    assert quick_nav(op, screen).is_fail
    assert pressed(op) == ['xbox_a'] * 3


def test_arrival_is_success_only_after_a_confirm():
    op, screen = fixture('suibian-arrived', '澄辉坪', '随便观')
    assert quick_nav(op, screen).result == R.WAIT
    op._quick_nav_confirms = 1
    assert quick_nav(op, screen).is_success
    op.ctx.controller.btn_press.assert_not_called()


def test_map_opens_quick_nav_with_menu_button_and_is_bounded():
    op, screen = fixture('map-counter-region', '澄辉坪', '随便观')
    for _ in range(3):
        assert quick_nav(op, screen).result == R.WAIT
    assert quick_nav(op, screen).is_fail
    assert pressed(op) == ['xbox_start'] * 3
    op, screen = fixture('map-counter-region', '澄辉坪', '随便观')
    op.ctx.game_config.background_gamepad_type = 'ds4'
    quick_nav(op, screen)
    assert pressed(op) == ['ds4_options']


def _transport(monkeypatch, point, quick_result):
    import src.navigation.map as nav
    import zzz_od.operation.transport as module
    op, screen = fixture('map-quick-nav', '布亚斯特城区', point)
    transport = Transport.__new__(Transport)
    transport.ctx, transport.area_name, transport.tp_name, transport.last_screenshot = op.ctx, '布亚斯特城区', point, screen
    transport._after_round_wait = lambda **_: None
    transport.ctx.controller.background_mode = True
    monkeypatch.setattr(nav, 'quick_nav', Mock(return_value=quick_result))
    monkeypatch.setattr(module, 'MapTransport', Mock(return_value=SimpleNamespace(execute=Mock(return_value='map'))))
    transport.round_by_op_result = lambda result: result
    return transport, op


@pytest.mark.parametrize('point', ['随便观', '阿朔', '柜台', '吼吼饼铺', '咖啡店'])
def test_transport_reaches_every_point_by_name(monkeypatch, point):
    quick = SimpleNamespace(is_fail=False, status='ok')
    transport, _ = _transport(monkeypatch, point, quick)
    assert transport.do_transport() is quick


def test_point_missing_from_quick_nav_falls_back_to_the_map_icon(monkeypatch):
    missing = SimpleNamespace(is_fail=True, status='布亚斯特城区 中没有传送点 吼吼饼铺：未来邦布研究室')
    transport, op = _transport(monkeypatch, '吼吼饼铺', missing)
    assert transport.do_transport().result == R.WAIT and transport._icon_fallback
    # The fixture still shows 快捷导航: B out of it before searching the map.
    assert transport.do_transport().result == R.WAIT and pressed(op) == ['xbox_b']
    transport.last_screenshot = None
    assert transport.do_transport() == 'map'


def test_points_without_icon_report_the_quick_nav_failure(monkeypatch):
    missing = SimpleNamespace(is_fail=True, status='澄辉坪 中没有传送点 某处')
    transport, _ = _transport(monkeypatch, '某处', missing)
    assert transport.do_transport() is missing


def test_video_store_english_hdd_is_a_named_destination_not_a_region():
    op, screen = fixture('quick-nav-video-store', '录像店', 'HDD')
    state = quick_nav_state(op, screen)
    assert [name for name, _, lit in state['points'] if lit] == ['HDD']
    assert quick_nav(op, screen).result == R.WAIT
    assert pressed(op) == ['xbox_a'] and op._quick_nav_chosen == 'HDD'
    op, screen = fixture('quick-nav-video-store', '录像店', '房间')
    assert quick_nav(op, screen).result == R.WAIT
    assert pressed(op) == ['xbox_dpad_right'] and op._quick_nav_chosen is None


def test_sixth_street_lists_coffee_and_newsstand_by_name():
    # Live 2026-10-12: 咖啡店 and 报刊亭 (刮刮卡) are named destinations of 六分街.
    op, screen = fixture('qn-sixth', '六分街', '报刊亭')
    state = quick_nav_state(op, screen)
    assert [name for name, _, lit in state['tiles'] if lit] == ['六分街']
    assert [name for name, _, _ in state['points']][:3] == ['喵吉长官', '咖啡店', '报刊亭']
    assert quick_nav(op, screen).result == R.WAIT
    assert pressed(op) == ['xbox_dpad_right']  # 喵吉长官 → 咖啡店 → 报刊亭


def test_bakery_is_a_named_destination_of_buyasite():
    op, screen = fixture('qn-open', '布亚斯特城区', '吼吼饼铺')
    state = quick_nav_state(op, screen)
    assert '吼吼饼铺' in [name for name, _, _ in state['points']]
    assert quick_nav(op, screen).result == R.WAIT
    assert pressed(op) == ['xbox_a']  # The focused tile is already the target region.


def test_region_outside_the_visible_columns_is_scrolled_into_view():
    op, screen = fixture('qn-open', '斯科特哨站', '某点')
    assert quick_nav(op, screen).result == R.WAIT
    assert pressed(op) == ['xbox_dpad_right']
    op, screen = fixture('wp-qn-right', '斯科特哨站', '某点')
    state = quick_nav_state(op, screen)
    assert '斯科特哨站' in [name for name, _, _ in state['tiles']]


def test_known_region_gives_up_after_a_full_scroll():
    op, screen = fixture('map-quick-nav', '斯科特哨站', '某点')  # A frame where it never appears.
    for _ in range(8):
        assert quick_nav(op, screen).result == R.WAIT
    assert quick_nav(op, screen).is_fail
