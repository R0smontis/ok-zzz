"""快捷导航 teleports by point name; every press follows a focus verified on a real frame."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from onedragon.base.operation.operation_round_result import OperationRoundResultEnum as R
from src.navigation.map import needs_quick_nav, quick_nav, quick_nav_state
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


@pytest.mark.parametrize('point,quick', [('随便观', True), ('阿朔', True), ('柜台', False), ('吼吼饼铺', False)])
def test_transport_uses_quick_nav_only_for_points_without_icon(monkeypatch, point, quick):
    import src.navigation.map as nav
    assert needs_quick_nav(point) is quick
    op, screen = fixture('map-quick-nav', '澄辉坪', point)
    transport = Transport.__new__(Transport)
    transport.ctx, transport.area_name, transport.tp_name, transport.last_screenshot = op.ctx, '澄辉坪', point, screen
    transport.ctx.controller.background_mode = True
    monkeypatch.setattr(nav, 'quick_nav', Mock(return_value='quick'))
    import zzz_od.operation.transport as module
    monkeypatch.setattr(module, 'MapTransport', Mock(return_value=SimpleNamespace(execute=Mock(return_value='map'))))
    transport.round_by_op_result = lambda result: result
    assert transport.do_transport() == ('quick' if quick else 'map')


def test_video_store_english_hdd_is_a_named_destination_not_a_region():
    op, screen = fixture('quick-nav-video-store', '录像店', 'HDD')
    state = quick_nav_state(op, screen)
    assert [name for name, _, lit in state['points'] if lit] == ['HDD']
    assert quick_nav(op, screen).result == R.WAIT
    assert pressed(op) == ['xbox_a'] and op._quick_nav_chosen == 'HDD'
    op, screen = fixture('quick-nav-video-store', '录像店', '房间')
    assert quick_nav(op, screen).result == R.WAIT
    assert pressed(op) == ['xbox_dpad_right'] and op._quick_nav_chosen is None
