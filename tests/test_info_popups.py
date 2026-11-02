"""Game notices covering any screen are closed before the node acts; task dialogs are left alone.

Frames and OCR are real: 「迷失之地」内容更新 blocked 一条龙 on 2026-11-01 because the entry clicked its ×
with a window message, which the game ignores in background mode.
"""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import pytest

from onedragon.base.geometry.rectangle import Rect
from onedragon.base.matcher.template_matcher import TemplateMatcher
from onedragon.base.operation.operation import Operation
from onedragon.base.operation.operation_node import OperationNode
from onedragon.base.operation.operation_round_result import OperationRoundResultEnum as R
from onedragon.base.screen.template_loader import TemplateLoader
from src.navigation.popups import MAX_PRESSES, dismiss_info_popup, info_popup

FIXTURES = Path(__file__).parent / 'fixtures'
NOTICE = 'lost_void/update-notice'
TM = TemplateMatcher(TemplateLoader())


def frame_op(name, background=True):
    """An operation on a real frame whose OCR returns the fixture's real rows inside the asked rect."""
    screen = cv2.cvtColor(cv2.imread(str(FIXTURES / f'{name}.png')), cv2.COLOR_BGR2RGB)
    data = json.loads((FIXTURES / f'{name}.json').read_text(encoding='utf-8'))
    rows = [SimpleNamespace(data=r['text'], center=Rect(r['rect'][0], r['rect'][1], r['rect'][0] + r['rect'][2],
                                                       r['rect'][1] + r['rect'][3]).center)
            for r in data['result']['ocr']]
    op = Operation.__new__(Operation)
    op.last_screenshot = screen
    op.ctx = SimpleNamespace(
        tm=TM, controller=Mock(background_mode=background),
        game_config=SimpleNamespace(background_gamepad_type='xbox'),
        ocr_service=SimpleNamespace(get_ocr_result_list=lambda image, rect, **_: [
            row for row in rows if rect.x1 <= row.center.x < rect.x2 and rect.y1 <= row.center.y < rect.y2]))
    return op


def test_update_notice_is_closed_with_b_in_background():
    op = frame_op(NOTICE)
    result = dismiss_info_popup(op)
    assert result.result == R.WAIT and '「迷失之地」内容更新' in result.status
    op.ctx.controller.btn_press.assert_called_once_with('xbox_b', press_time=.12)


def test_update_notice_is_clicked_closed_in_foreground():
    op = frame_op(NOTICE, background=False)
    assert dismiss_info_popup(op).result == R.WAIT
    point = op.ctx.controller.click.call_args.args[0]
    assert abs(point.x - 1374) < 15 and abs(point.y - 269) < 15  # The ×, not the dialog body.
    op.ctx.controller.btn_press.assert_not_called()


def test_notice_that_never_closes_fails_after_bounded_presses():
    op = frame_op(NOTICE)
    for _ in range(MAX_PRESSES):
        assert dismiss_info_popup(op).result == R.WAIT
    failed = dismiss_info_popup(op)
    assert failed.is_fail and '无法关闭' in failed.status
    keys = [c.args[0] for c in op.ctx.controller.btn_press.call_args_list]
    assert len(keys) == MAX_PRESSES and 'xbox_a' in keys  # B, plus one A for confirm-only notices.


@pytest.mark.parametrize('name', [
    'daily_map/restore-quick-traditional',  # 快捷使用: B would cancel the charge restore in progress.
    'daily_map/restore-quick',
    'daily_map/hunt-reward-panel',          # 周期挑战 reward panel opened by the task.
    'redemption/redeem-code-panel',         # 兑换码 input dialog.
    'redemption/redeem-code-cooling',
    'suibian/duration-15min-focused',       # 游历时间选择.
    'daily_map/weekly-entry-real',          # Full-screen 快捷手册 with its own × at the far right.
    'lost_void/compendium_combat_tab',
])
def test_task_dialogs_and_menus_with_a_close_button_are_left_to_the_task(name):
    op = frame_op(name)
    assert info_popup(op, op.last_screenshot) is None
    assert dismiss_info_popup(op) is None
    op.ctx.controller.btn_press.assert_not_called()
    op.ctx.controller.click.assert_not_called()


def test_every_node_round_closes_a_notice_before_the_node_runs():
    op = frame_op(NOTICE)
    op.ctx.dismiss_info_popup = dismiss_info_popup
    node_body = Mock()
    op._current_node = OperationNode('前往迷失之地-入口', op_method=node_body, screenshot_before_round=True)
    op._current_node_start_time = None
    op.screenshot = Mock()
    assert op._execute_one_round().result == R.WAIT
    node_body.assert_not_called()
    op.last_screenshot = frame_op('lost_void/compendium_combat_tab').last_screenshot
    node_body.return_value = op.round_success('入口')
    assert op._execute_one_round().is_success
    node_body.assert_called_once()
