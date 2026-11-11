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
from src.navigation.popups import (MAX_PRESSES, STARTUP_PRESSES, dismiss_info_popup, info_popup,
                                   monthly_card, resume_prompt)

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


# 2026-11-10: 一条龙 started on the monthly card and sat in 传送 → 打开地图 pressing the map key; a run
# started on 「当前正在处理…是否继续？」 waited forever on a click the game ignores.
@pytest.mark.parametrize('name', ['daily_map/monthly-card-popup', 'daily_map/monthly-card-november'])
def test_monthly_card_is_closed_before_any_node_acts(name):
    op = frame_op(name)
    for _ in range(STARTUP_PRESSES):
        result = dismiss_info_popup(op)
        assert result.result == R.WAIT and '月卡' in result.status
    assert dismiss_info_popup(op).is_fail  # Bounded: never presses forever.
    assert [c.args[0] for c in op.ctx.controller.btn_press.call_args_list] == ['xbox_b'] * STARTUP_PRESSES
    op.ctx.controller.click.assert_not_called()


def test_card_reappearing_after_daily_reset_mid_run_is_closed_again():
    # Around 04:00 the card pops up over whatever the running task shows; the same operation must
    # close it again instead of failing on the press count left from the login card.
    op = frame_op('daily_map/monthly-card-november')
    card, world = op.last_screenshot, frame_op('lost_void/compendium_combat_tab').last_screenshot
    for _ in range(STARTUP_PRESSES):
        assert dismiss_info_popup(op).result == R.WAIT
    op.last_screenshot = world
    assert dismiss_info_popup(op) is None
    op.last_screenshot = card
    assert dismiss_info_popup(op).result == R.WAIT


def test_unfocused_resume_prompt_moves_to_cancel_then_gives_up():
    # Real client: clicks and B are ignored; dpad_left focuses 取消.
    op = frame_op('daily_map/resume-battle-popup')
    for _ in range(3):
        assert dismiss_info_popup(op).status == '手柄选择取消'
    assert dismiss_info_popup(op).is_fail
    assert [c.args[0] for c in op.ctx.controller.btn_press.call_args_list] == ['xbox_dpad_left'] * 3
    op.ctx.controller.click.assert_not_called()


def test_focused_cancel_is_pressed_with_a():
    op = frame_op('daily_map/resume-battle-popup-cancel-focused')
    for _ in range(2):
        assert dismiss_info_popup(op).status == '手柄取消未完成的活动'
    assert dismiss_info_popup(op).is_fail
    assert [c.args[0] for c in op.ctx.controller.btn_press.call_args_list] == ['xbox_a'] * 2


def test_resume_prompt_is_clicked_in_foreground():
    op = frame_op('daily_map/resume-battle-popup', background=False)
    assert dismiss_info_popup(op).result == R.WAIT
    point = op.ctx.controller.click.call_args.args[0]
    assert abs(point.x - 827) < 30 and abs(point.y - 627) < 30  # 取消, never 确认.


def test_operation_that_resumes_its_run_keeps_the_prompt():
    op = frame_op('daily_map/resume-battle-popup')
    op.resumes_pending_activity = True
    assert dismiss_info_popup(op) is None
    op.ctx.controller.btn_press.assert_not_called()


def test_withered_domain_only_keeps_the_prompt_on_its_next_step_node():
    from zzz_od.application.hollow_zero.withered_domain.withered_domain_app import WitheredDomainApp
    app = WitheredDomainApp.__new__(WitheredDomainApp)
    app._current_node = OperationNode('下一步', op_method=Mock())
    assert app.resumes_pending_activity
    app._current_node = OperationNode('初始画面识别', op_method=Mock())
    assert not app.resumes_pending_activity


def test_no_other_real_frame_is_taken_for_a_startup_popup():
    startup = {'daily_map/monthly-card-popup', 'daily_map/monthly-card-november',
               'daily_map/resume-battle-popup', 'daily_map/resume-battle-popup-cancel-focused'}
    checked = 0
    for path in sorted(FIXTURES.rglob('*.png')):
        name = path.relative_to(FIXTURES).with_suffix('').as_posix()
        if name in startup or not path.with_suffix('.json').exists():
            continue
        try:
            op = frame_op(name)
        except (KeyError, TypeError, ValueError):
            continue
        if op.last_screenshot.shape[:2] != (1080, 1920):
            continue
        checked += 1
        assert monthly_card(op, op.last_screenshot) is None, name
        assert resume_prompt(op, op.last_screenshot) is None, name
    assert checked > 100
