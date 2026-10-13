"""World recovery must verify the destination and the exit confirmation focus."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from onedragon.base.geometry.rectangle import Rect
from onedragon.base.operation.operation_round_result import OperationRoundResultEnum as R
from test_lost_void_background_menus import operation
from zzz_od.operation.back_to_normal_world import BackToNormalWorld


def recovery(background=True, ensure=True):
    op = operation(BackToNormalWorld)
    op.handle_init()
    op.ensure_normal_world = ensure
    op.allow_battle = False
    op.ctx.controller.background_mode = background
    op.check_and_update_current_screen = Mock(return_value=None)
    op.round_by_find_area = Mock(return_value=op.round_retry())
    op.round_by_find_and_click_area = Mock(return_value=op.round_retry())
    op.round_by_click_area = Mock(return_value=op.round_success())
    op.round_by_goto_screen = Mock(return_value=op.round_fail())
    op.ctx.ocr_service = SimpleNamespace(get_ocr_result_list=Mock(return_value=[]))
    op.ctx.screen_loader = SimpleNamespace(current_screen_name=None)
    op.ctx.world_patrol_service = SimpleNamespace(cut_mini_map=lambda _: SimpleNamespace(play_mask_found=True))
    return op


def test_still_exploring_after_transport_waits_for_verified_normal_destination():
    op = recovery()
    op._previous_node = SimpleNamespace(cn='画面识别')
    op._previous_round_result = op.round_success()
    op.check_and_update_current_screen.return_value = '大世界-勘域'
    assert op.check_screen_and_run().status == '传送到录像店'
    op._previous_node = SimpleNamespace(cn='执行传送')
    for _ in range(6):
        assert op.check_screen_and_run().result == R.WAIT
    assert op.check_screen_and_run().is_fail
    op._normal_arrival_waits = 0
    op.check_and_update_current_screen.return_value = '大世界-普通'
    assert op.check_screen_and_run().status == '大世界-普通'


@pytest.mark.parametrize('background', [False, True])
def test_battle_hud_precedes_minimap_and_generic_navigation(background):
    op = recovery(background)
    op.round_by_find_area.return_value = op.round_success('普通攻击')
    result = op.check_screen_and_run()
    assert not result.is_success
    op.round_by_click_area.assert_called_once_with('战斗画面', '菜单')
    op.round_by_goto_screen.assert_not_called()
    op.allow_battle = True
    assert op.check_screen_and_run().status == '大世界-战斗'


def test_exploration_minimap_routes_transport_instead_of_world_success():
    op = recovery()
    assert op.check_screen_and_run().status == '传送到录像店'
    op.ctx.controller.btn_press.assert_not_called()


def test_exit_confirmation_requires_text_and_focus_then_waits_for_closure():
    op = recovery()
    op.click_exit_battle = True
    assert not op.check_screen_and_run().is_success
    op.ctx.controller.btn_press.assert_not_called()
    confirm = SimpleNamespace(data='确认', center=Rect(1000, 600, 1260, 656).center)
    cancel = SimpleNamespace(data='取消', center=Rect(660, 600, 920, 656).center)
    op.ctx.ocr_service.get_ocr_result_list.return_value = [confirm, cancel]
    op.last_screenshot[600:656,660:920] = (255,230,0)
    op.check_screen_and_run()
    op.ctx.controller.btn_press.assert_called_once_with('xbox_dpad_right', press_time=.12)
    op.last_screenshot[:] = 0
    op.last_screenshot[600:656,980:1280] = (255,230,0)
    op.check_screen_and_run()
    assert op.ctx.controller.btn_press.call_args.args == ('xbox_a',)
    count = op.ctx.controller.btn_press.call_count
    op.check_screen_and_run()
    assert op.ctx.controller.btn_press.call_count == count
    op.check_and_update_current_screen.return_value = '大世界-普通'
    assert op.check_screen_and_run().status == '大世界-普通'


def test_main_menu_returns_to_observe_world_before_deciding_transport(monkeypatch):
    op = recovery()
    from src.navigation import map as map_navigation
    monkeypatch.setattr(map_navigation, 'map_state', lambda *args: None)
    op.ctx.ocr_service.get_ocr_result_list.return_value = [
        SimpleNamespace(data=label) for label in ('设置', '公告', '成就', '绳网', '仓库')]
    assert op.check_screen_and_run().result == R.RETRY
    op.ctx.controller.btn_press.assert_called_once_with('xbox_b', press_time=.12)
    op.check_and_update_current_screen.return_value = '大世界-普通'
    assert op.check_screen_and_run().status == '大世界-普通'
    assert op.ctx.controller.btn_press.call_count == 1
