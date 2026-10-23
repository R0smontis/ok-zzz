"""资源更新重登提示：确认输入必须与当前交互方式一致。"""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import pytest

from onedragon.base.matcher.ocr.ocr_match_result import OcrMatchResult
from onedragon.base.operation.operation_round_result import OperationRoundResultEnum as R
from onedragon.base.screen.screen_loader import ScreenContext
from zzz_od.operation.enter_game.enter_game import EnterGame
from test_charge_plan_empty_targets import operation


@pytest.fixture
def update_popup():
    op = operation(EnterGame)
    folder = Path(__file__).parent / 'fixtures' / 'daily_map'
    op.last_screenshot = cv2.cvtColor(cv2.imread(str(folder / 'game-data-updated.png')), cv2.COLOR_BGR2RGB)
    payload = json.loads((folder / 'game-data-updated.json').read_text(encoding='utf-8'))
    rows = [OcrMatchResult(c=row['confidence'], x=row['rect'][0], y=row['rect'][1],
                          w=row['rect'][2], h=row['rect'][3], data=row['text'])
            for row in payload['result']['ocr']]
    loader = ScreenContext()
    loader.reload()
    op.ctx.screen_loader = loader
    op.ctx.ocr_service = SimpleNamespace(get_ocr_result_list=lambda image, rect, **kwargs: [
        row for row in rows if rect.x1 <= row.center.x < rect.x2 and rect.y1 <= row.center.y < rect.y2])
    op.ctx.controller.btn_press = Mock()
    op.ctx.controller.click = Mock(return_value=True)
    op.ctx.controller.background_mode = True
    op.ctx.game_config = SimpleNamespace(background_gamepad_type='xbox')
    op.after_first_enter_click = op.after_second_enter_click = True
    op.resource_download_start_time = 123
    op.update_screen_after_operation = Mock()
    return op, rows


@pytest.mark.parametrize('pad_type,key', [('xbox', 'xbox_a'), ('ds4', 'ds4_cross')])
def test_real_update_popup_uses_controller_confirm_and_waits(update_popup, pad_type, key):
    op, rows = update_popup
    op.ctx.game_config.background_gamepad_type = pad_type
    result = op.check_game_data_updated(op.last_screenshot, back_to_check_screen=False)
    assert result.result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with(key, press_time=.12)
    op.ctx.controller.click.assert_not_called()
    assert not op.after_first_enter_click and not op.after_second_enter_click
    assert op.resource_download_start_time is None
    rows.clear()  # A fresh frame no longer shows the popup: do not confirm again.
    assert op.check_game_data_updated(op.last_screenshot, back_to_check_screen=False) is None
    assert op.ctx.controller.btn_press.call_count == 1


def test_foreground_update_popup_clicks_verified_confirm(update_popup):
    op, _ = update_popup
    op.ctx.controller.background_mode = False
    result = op.check_game_data_updated(op.last_screenshot, back_to_check_screen=False)
    assert result.result == R.WAIT
    point = op.ctx.controller.click.call_args.args[0]
    assert 947 <= point.x <= 1011 and 634 <= point.y <= 672
    op.ctx.controller.btn_press.assert_not_called()


@pytest.mark.parametrize('message', ['提示', '游戏数据已损坏，请重新登录。', '账号已在其他设备登录。'])
def test_other_dialogs_do_not_trigger_update_confirmation(update_popup, message):
    op, rows = update_popup
    rows[0].data = message
    assert op.check_game_data_updated(op.last_screenshot, back_to_check_screen=False) is None
    op.ctx.controller.btn_press.assert_not_called()
    op.ctx.controller.click.assert_not_called()
    assert op.after_second_enter_click


def test_update_message_without_confirm_sends_nothing(update_popup):
    op, rows = update_popup
    rows.pop()
    assert op.check_game_data_updated(op.last_screenshot, back_to_check_screen=False).result == R.RETRY
    op.ctx.controller.btn_press.assert_not_called()
    op.ctx.controller.click.assert_not_called()
    assert op.after_second_enter_click and op.resource_download_start_time == 123


@pytest.mark.parametrize('method', ['check_screen', 'check_enter_click_status', 'wait_loading'])
def test_update_popup_during_any_login_phase_returns_to_screen_detection(update_popup, method):
    op, _ = update_popup
    op._init_network()
    nodes = {'check_screen': '画面识别', 'check_enter_click_status': '点击进入游戏', 'wait_loading': '登录成功'}
    op._current_node = op._node_map[nodes[method]]
    result = getattr(op, method)()
    assert result.status == EnterGame.STATUS_GAME_DATA_UPDATED
    if method == 'check_screen':
        assert result.result == R.WAIT
    else:
        assert result.is_success
        assert op._get_next_node(result).cn == '画面识别'
    op.ctx.controller.btn_press.assert_called_once_with('xbox_a', press_time=.12)
    op.ctx.controller.click.assert_not_called()
