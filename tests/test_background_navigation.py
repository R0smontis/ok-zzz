import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import pytest

from onedragon.base.geometry.rectangle import Rect
from onedragon.base.operation.operation_round_result import OperationRoundResultEnum as R
from src.navigation.menus import compendium_tab
from zzz_od.context.zzz_context import ZContext
from zzz_od.game_data.map_area import MapAreaService
from zzz_od.operation.transport import Transport
from test_lost_void_background_menus import operation


def compendium_fixture():
    op=operation(Transport)
    path=Path(__file__).parent/'fixtures/lost_void/compendium_combat_tab.png'
    op.last_screenshot=cv2.cvtColor(cv2.imread(str(path)),cv2.COLOR_BGR2RGB)
    info=json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
    rows=[SimpleNamespace(data=row['text'],center=Rect(row['rect'][0],row['rect'][1],
        row['rect'][0]+row['rect'][2],row['rect'][1]+row['rect'][3]).center) for row in info['result']['ocr']]
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=Mock(return_value=rows))
    return op,rows


def test_context_supplies_real_loaded_map_service_for_daily_transport():
    ctx=ZContext.__new__(ZContext)
    assert isinstance(ctx.map_service,MapAreaService)
    assert ctx.map_service is ctx.map_service
    assert '咖啡店' in ctx.map_service.area_name_map['六分街'].tp_list
    assert '柜台' in ctx.map_service.area_name_map['录像店'].tp_list
    assert '吼吼饼铺' in ctx.map_service.area_name_map['布亚斯特城区'].tp_list


@pytest.mark.parametrize('missing',[None,'tabs','focus','ambiguous'])
def test_real_tab_switch_requires_complete_header_and_unique_selected_tab(missing):
    op,rows=compendium_fixture()
    if missing=='tabs':op.ctx.ocr_service.get_ocr_result_list.return_value=rows[:2]
    elif missing=='focus':op.last_screenshot[:]=0
    elif missing=='ambiguous':op.last_screenshot[120:200,925:1050]=(240,210,0)
    result=compendium_tab(op,op.last_screenshot,'快捷手册-日常')
    if missing is None:
        assert result.result==R.WAIT
        op.ctx.controller.btn_press.assert_called_once_with('xbox_lb',press_time=.12)
    else:
        assert result.result==R.RETRY
        op.ctx.controller.btn_press.assert_not_called()


def test_unchanged_tab_does_not_generate_infinite_waits():
    op,_=compendium_fixture()
    for _ in range(3):assert compendium_tab(op,op.last_screenshot,'快捷手册-日常').result==R.WAIT
    assert compendium_tab(op,op.last_screenshot,'快捷手册-日常').is_fail
    assert op.ctx.controller.btn_press.call_count==3


def test_ds4_right_tab_navigation_uses_controller_shoulder_button():
    op,_=compendium_fixture()
    op.ctx.game_config.background_gamepad_type='ds4'
    assert compendium_tab(op,op.last_screenshot,'快捷手册-战术').result==R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('ds4_r1',press_time=.12)


def test_verified_selected_tab_ends_navigation_without_input():
    op,_=compendium_fixture()
    assert compendium_tab(op,op.last_screenshot,'快捷手册-作战').is_success
    op.ctx.controller.btn_press.assert_not_called()


def test_unrelated_screen_is_not_intercepted():
    op,_=compendium_fixture()
    assert compendium_tab(op,op.last_screenshot,'迷失之地-特遣调查') is None
    op.ctx.controller.btn_press.assert_not_called()


def map_open_operation(monkeypatch):
    clock=SimpleNamespace(now=100.)
    monkeypatch.setattr('zzz_od.operation.transport.time.monotonic',lambda:clock.now)
    op=operation(Transport)
    op.is_map_screen=Mock(return_value=False)
    op.check_and_update_current_screen=Mock(return_value='大世界-普通')
    return op,clock


def test_background_map_open_requires_actual_screen_change_and_bounds_time(monkeypatch):
    op,clock=map_open_operation(monkeypatch)
    # Live 2026-10-12: nine presses over ~20 s at the start of a run did not open the map.
    for _ in range(10):
        assert op.open_map().result==R.WAIT
        clock.now+=2.5
    assert op.ctx.controller.btn_press.call_count==10
    assert all(c.args==('xbox_back',) for c in op.ctx.controller.btn_press.call_args_list)
    clock.now=100.+Transport.MAP_OPEN_TIMEOUT_SECONDS
    assert op.open_map().is_fail
    assert op.ctx.controller.btn_press.call_count==10
    op.is_map_screen.return_value=True
    assert op.open_map().is_success
    assert op.ctx.controller.btn_press.call_count==10


def test_background_map_press_without_effect_rearms_input_device_switch(monkeypatch):
    op,_=map_open_operation(monkeypatch)
    assert op.open_map().result==R.WAIT
    op.ctx.controller.forget_game_input_mode.assert_not_called()
    assert op.open_map().result==R.WAIT
    op.ctx.controller.forget_game_input_mode.assert_called_once()
    assert op.ctx.controller.btn_press.call_count==2


def test_background_map_is_not_toggled_while_screen_is_changing(monkeypatch):
    op,_=map_open_operation(monkeypatch)
    assert op.open_map().result==R.WAIT
    op.check_and_update_current_screen.return_value=None  # Map still opening: neither world nor map.
    for _ in range(3):assert op.open_map().result==R.WAIT
    assert op.ctx.controller.btn_press.call_count==1
    op.is_map_screen.return_value=True
    assert op.open_map().is_success


def test_verified_compendium_back_is_bounded_and_refuses_unrelated_footer():
    op,rows=compendium_fixture()
    other=SimpleNamespace(data='确认',center=Rect(1110,995,1160,1030).center)
    rows.append(other)
    assert compendium_tab(op,op.last_screenshot,'大世界-普通').result==R.RETRY
    op.ctx.controller.btn_press.assert_not_called()
    other.data='B返回'  # OCR can merge the controller glyph into the label.
    for _ in range(4):assert compendium_tab(op,op.last_screenshot,'大世界-普通').result==R.WAIT
    assert compendium_tab(op,op.last_screenshot,'大世界-普通').is_fail
    assert op.ctx.controller.btn_press.call_count==4
    assert all(call.args==('xbox_b',) for call in op.ctx.controller.btn_press.call_args_list)


def test_keyboard_prompt_compendium_is_woken_by_controller_back():
    op,_=compendium_fixture()  # Captured with keyboard prompts: no footer hints at all.
    assert compendium_tab(op,op.last_screenshot,'大世界-普通').result==R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_b',press_time=.12)


def test_transport_opens_map_from_verified_hollow_overworld(monkeypatch):
    op, _ = map_open_operation(monkeypatch)
    op.check_and_update_current_screen.return_value = '大世界-勘域'
    assert op.open_map().result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_back', press_time=.12)


def test_return_world_uses_pad_map_open_not_ignored_mouse(monkeypatch):
    from zzz_od.operation.back_to_normal_world import BackToNormalWorld
    import src.navigation.map as nav
    op = operation(BackToNormalWorld)
    op.check_and_update_current_screen = Mock(return_value='大世界-勘域')
    monkeypatch.setattr(nav, 'map_state', lambda *_: None)
    monkeypatch.setattr(nav, 'quick_nav_state', lambda *_: None)
    assert op.open_map().result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_back', press_time=.12)
    op.ctx.controller.click.assert_not_called()


def test_return_world_existing_quick_nav_needs_no_toggle(monkeypatch):
    from zzz_od.operation.back_to_normal_world import BackToNormalWorld
    import src.navigation.map as nav
    op = operation(BackToNormalWorld)
    monkeypatch.setattr(nav, 'map_state', lambda *_: None)
    monkeypatch.setattr(nav, 'quick_nav_state', lambda *_: {'dialog': False})
    assert op.open_map().is_success
    op.ctx.controller.btn_press.assert_not_called()


def test_return_world_teleports_to_named_room_not_old_icon_operation(monkeypatch):
    from zzz_od.operation.back_to_normal_world import BackToNormalWorld
    import src.navigation.map as nav
    op = operation(BackToNormalWorld)
    expected = op.round_wait('正在传送')
    quick = Mock(return_value=expected)
    monkeypatch.setattr(nav, 'quick_nav', quick)
    assert op.do_transport() is expected
    assert (op.area_name, op.tp_name) == ('录像店', '房间')
    quick.assert_called_once_with(op, op.last_screenshot)


def test_return_world_does_not_count_post_confirmation_hollow_as_normal():
    from zzz_od.operation.back_to_normal_world import BackToNormalWorld
    op = operation(BackToNormalWorld)
    op.ensure_normal_world = True
    op.handle_init()
    op._previous_node = SimpleNamespace(cn='执行传送')
    op._previous_round_result = op.round_success('已确认传送')
    op.check_and_update_current_screen = Mock(return_value='大世界-勘域')
    for _ in range(6):
        assert op.check_screen_and_run().result == R.WAIT
    assert op.check_screen_and_run().is_fail
    op.ctx.controller.btn_press.assert_not_called()
    op.check_and_update_current_screen.return_value = '大世界-普通'
    assert op.check_screen_and_run().is_success


def test_return_world_counters_are_reset_for_a_new_execution():
    from zzz_od.operation.back_to_normal_world import BackToNormalWorld
    op = operation(BackToNormalWorld)
    op._map_open_requests = 30
    op._quick_nav_steps = 40
    op._quick_nav_chosen = '房间'
    op._normal_arrival_waits = 9
    op.handle_init()
    assert op._normal_arrival_waits == 0
    assert not any(key.startswith(('_map_open_', '_quick_nav_')) for key in op.__dict__)
