"""The log records each round's kind, the screen text on failure (never the UID) and navigation inputs."""
import logging
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from onedragon.base.geometry.point import Point
from onedragon.base.operation.operation import Operation
from onedragon.base.operation.operation_round_result import OperationRoundResult, OperationRoundResultEnum


def row(text, x, y):
    return SimpleNamespace(data=text, center=Point(x, y))


def bare_op(**fields):
    op = Operation.__new__(Operation)
    op.op_name = '邮件'
    op.__dict__.update(fields)
    return op


def test_round_kind_shows_retry_count_wait_and_failure():
    op = bare_op(node_retry_times=1, node_max_retry_times=3)
    result = lambda kind: OperationRoundResult(result=kind, status='x')
    assert op._round_kind_text(result(OperationRoundResultEnum.RETRY)) == '（重试 2/3）'
    op.node_retry_times = 3
    assert op._round_kind_text(result(OperationRoundResultEnum.RETRY)) == '（重试次数用尽）'
    assert op._round_kind_text(result(OperationRoundResultEnum.WAIT)) == '（等待）'
    assert op._round_kind_text(result(OperationRoundResultEnum.FAIL)) == '（失败）'
    assert op._round_kind_text(result(OperationRoundResultEnum.SUCCESS)) == ''
    assert op._round_kind_text(None) == ''


def test_failure_logs_screen_text_in_reading_order_without_uid(monkeypatch):
    from onedragon.base.operation import operation as module
    lines = []
    monkeypatch.setattr(module.log, 'info', lambda fmt, *args: lines.append(fmt % args))
    rows = [row('确认', 900, 700), row('邮件', 300, 100), row('全部领取', 1500, 1000),
            row('UID：12345678', 1700, 1070), row('12345678', 1870, 1070), row('收件箱', 600, 105)]
    ocr = SimpleNamespace(get_ocr_result_list=Mock(return_value=rows))
    op = bare_op(ctx=SimpleNamespace(ocr_service=ocr), last_screenshot=np.zeros((1080, 1920, 3), np.uint8))
    op._log_failure_screen()
    assert lines == ['指令[ 邮件 ] 失败时画面文字：邮件 | 收件箱 | 确认 | 全部领取']
    assert '1234' not in lines[0]
    # No screenshot or a broken reader: nothing logged, nothing raised.
    op.last_screenshot = None
    op._log_failure_screen()
    op.last_screenshot = np.zeros((1080, 1920, 3), np.uint8)
    ocr.get_ocr_result_list.side_effect = RuntimeError('ocr')
    op._log_failure_screen()
    assert len(lines) == 1


def test_navigation_inputs_are_logged_one_line_each(caplog):
    from src.controls import gamepad
    controller = SimpleNamespace(btn_press=Mock())
    ctx = SimpleNamespace(controller=controller, game_config=SimpleNamespace(background_gamepad_type='xbox'))
    with caplog.at_level(logging.INFO, logger='ok'):
        gamepad.press(ctx, 'dpad_right')
        gamepad.press(ctx, 'dpad_right')
        gamepad.press(ctx, 'b', 1)
    assert [r.getMessage() for r in caplog.records] == [
        '输入:手柄 DPAD_RIGHT', '输入:手柄 DPAD_RIGHT', '输入:手柄 B 按住 1 秒']
    assert controller.btn_press.call_count == 3
