"""Warehouse navigation from real game frames, with no destructive confirmation."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import pytest

from onedragon.base.geometry.rectangle import Rect
from onedragon.base.operation.operation_round_result import OperationRoundResultEnum as R
from src.navigation.warehouse import warehouse_tab
from zzz_od.context.zzz_context import ZContext
from zzz_od.operation.transport import Transport
from test_lost_void_background_menus import operation

BASE = Path(__file__).parent / 'fixtures/warehouse'


def fixture(name):
    op = operation(Transport)
    screen = cv2.cvtColor(cv2.imread(str(BASE / f'{name}.png')), cv2.COLOR_BGR2RGB)
    data = json.loads((BASE / f'{name}.json').read_text(encoding='utf-8'))
    rows = [SimpleNamespace(data=r['text'], center=Rect(r['rect'][0], r['rect'][1],
             r['rect'][0]+r['rect'][2], r['rect'][1]+r['rect'][3]).center) for r in data['result']['ocr']]
    op.ctx.ocr_service = SimpleNamespace(get_ocr_result_list=lambda image, rect: [
        r for r in rows if rect.x1 <= r.center.x < rect.x2 and rect.y1 <= r.center.y < rect.y2])
    return op, screen


def test_wengine_switches_to_drive_discs_with_rb_then_requires_new_title():
    op, screen = fixture('wengine')
    assert warehouse_tab(op, screen, '仓库-驱动仓库').result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_rb', press_time=.12)
    _, screen = fixture('drive-discs')
    op.ctx.ocr_service = fixture('drive-discs')[0].ctx.ocr_service
    assert warehouse_tab(op, screen, '仓库-驱动仓库').is_success
    assert op.ctx.controller.btn_press.call_count == 1


@pytest.mark.parametrize('name', ['drive-discs', 'drive-discs-keyboard', 'drive-discs-controller'])
def test_drive_discs_title_is_sufficient_with_either_prompt_mode(name):
    op, screen = fixture(name)
    assert warehouse_tab(op, screen, '仓库-驱动仓库').is_success
    op.ctx.controller.btn_press.assert_not_called()
    assert warehouse_tab(op, screen, '仓库-音擎仓库').result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_lb', press_time=.12)


def test_ignored_switch_is_bounded_and_ds4_uses_r1():
    op, screen = fixture('wengine')
    op.ctx.game_config.background_gamepad_type = 'ds4'
    for _ in range(3):
        assert warehouse_tab(op, screen, '仓库-驱动仓库').result == R.WAIT
    assert warehouse_tab(op, screen, '仓库-驱动仓库').is_fail
    assert op.ctx.controller.btn_press.call_count == 3
    assert all(c.args == ('ds4_r1',) for c in op.ctx.controller.btn_press.call_args_list)


def test_missing_or_ambiguous_title_sends_no_input():
    op, screen = fixture('wengine')
    for rows in ([], [SimpleNamespace(data='音擎仓库'), SimpleNamespace(data='驱动仓库')]):
        op.ctx.ocr_service.get_ocr_result_list = Mock(return_value=rows)
        assert warehouse_tab(op, screen, '仓库-驱动仓库').result == R.RETRY
    op.ctx.controller.btn_press.assert_not_called()


def test_dismantle_is_not_mistaken_for_a_plain_tab():
    op, screen = fixture('drive-discs')
    assert warehouse_tab(op, screen, '仓库-驱动仓库-驱动盘拆解') is None
    op.ctx.controller.btn_press.assert_not_called()


def test_context_routes_via_tab_without_legacy_clicks():
    op, screen = fixture('wengine')
    context = ZContext.__new__(ZContext)
    context.screen_loader = SimpleNamespace(get_screen_route=Mock(return_value=SimpleNamespace(
        can_go=True, node_list=[SimpleNamespace(to_screen='仓库-驱动仓库')])))
    result = context.navigate_background_screen(op, screen, '仓库-驱动仓库-驱动盘拆解', current='仓库-音擎仓库')
    assert result.result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_rb', press_time=.12)
    op.ctx.controller.btn_press.reset_mock()
    context.screen_loader.get_screen_route.return_value.node_list[0].to_screen = '仓库-驱动仓库-驱动盘拆解'
    result = context.navigate_background_screen(op, screen, '仓库-驱动仓库-驱动盘拆解', current='仓库-驱动仓库')
    assert result.is_fail and '尚未核验' in result.status
    op.ctx.controller.btn_press.assert_not_called()
