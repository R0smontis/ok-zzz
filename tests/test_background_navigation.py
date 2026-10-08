import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import pytest

from onedragon.base.geometry.rectangle import Rect
from onedragon.base.operation.operation_round_result import OperationRoundResultEnum as R
from src.background_navigation import compendium_tab
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


def test_background_map_open_requires_actual_screen_change_and_bounds_attempts():
    op=operation(Transport)
    op.is_map_screen=Mock(return_value=False)
    for _ in range(3):assert op.open_map().result==R.WAIT
    assert op.open_map().is_fail
    assert op.ctx.controller.btn_press.call_count==3
    op.is_map_screen.return_value=True
    assert op.open_map().is_success
    assert op.ctx.controller.btn_press.call_count==3


def test_verified_compendium_back_is_bounded_and_requires_visible_return_prompt():
    op,rows=compendium_fixture()
    assert compendium_tab(op,op.last_screenshot,'大世界-普通').result==R.RETRY
    op.ctx.controller.btn_press.assert_not_called()
    rows.append(SimpleNamespace(data='返回',center=Rect(1110,995,1160,1030).center))
    for _ in range(3):assert compendium_tab(op,op.last_screenshot,'大世界-普通').result==R.WAIT
    assert compendium_tab(op,op.last_screenshot,'大世界-普通').is_fail
    assert op.ctx.controller.btn_press.call_count==3
    assert all(call.args==('xbox_b',) for call in op.ctx.controller.btn_press.call_args_list)
