"""后台对话只操作已识别动作，未知/消费确认没有键鼠兜底。"""
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from onedragon.base.geometry.point import Point
from onedragon.base.geometry.rectangle import Rect
from onedragon.base.operation.operation_round_result import OperationRoundResultEnum as R
from src.navigation.dialogue import dialogue_action
from zzz_od.application.commission_assistant.dialogue_detector import DialogueAction
from zzz_od.application.commission_assistant.commission_assistant_app import CommissionAssistantApp
from test_lost_void_background_menus import operation


def setup(rows=()):
    op = operation(CommissionAssistantApp)
    op.ctx.controller.background_mode = True
    op.ctx.ocr_service = SimpleNamespace(get_ocr_result_list=lambda image, rect, **_: [
        r for r in rows if rect.x1 <= r.center.x < rect.x2 and rect.y1 <= r.center.y < rect.y2])
    return op, np.zeros((1080, 1920, 3), np.uint8)


def row(text, x, y):
    return SimpleNamespace(data=text, center=Point(x, y))


def pressed(op):
    return [c.args[0] for c in op.ctx.controller.btn_press.call_args_list]


def test_unknown_screen_sends_no_input():
    op, screen = setup()
    assert dialogue_action(op, screen, None).result == R.RETRY
    assert not pressed(op)
    op.ctx.controller.click.assert_not_called()


def test_verified_dialogue_advances_once_and_changed_body_allows_next_sentence():
    rows = [row('你好，绳匠。', 900, 900)]
    op, screen = setup(rows)
    action = DialogueAction('advance', Point(959, 905), '继续对话')
    assert dialogue_action(op, screen, action).result == R.WAIT
    assert dialogue_action(op, screen, action).result == R.WAIT
    assert pressed(op) == ['xbox_a']
    rows[0] = row('下次见。', 900, 900)
    assert dialogue_action(op, screen, action).result == R.WAIT
    assert pressed(op) == ['xbox_a', 'xbox_a']


def test_ignored_confirm_is_bounded_without_more_presses():
    op, screen = setup([row('你好。', 900, 900)])
    action = DialogueAction('advance', Point(959, 905), '继续对话')
    dialogue_action(op, screen, action)
    results = [dialogue_action(op, screen, action) for _ in range(6)]
    assert results[-1].is_fail and pressed(op) == ['xbox_a']


@pytest.mark.parametrize('text', ['购买道具', '确认解锁', '消耗材料', '兑换奖励', '拆解驱动盘'])
def test_resource_options_require_manual_decision(text):
    op, screen = setup()
    result = dialogue_action(op, screen, DialogueAction('option', Point(1600, 620), text))
    assert result.result == R.RETRY and not pressed(op)


def test_option_navigation_requires_the_visible_target_and_unique_focus():
    rows = [row('继续聊聊', 1600, 600), row('再见', 1600, 720)]
    op, screen = setup(rows)
    screen[575:625, 1480:1720] = [240, 230, 0]
    action = DialogueAction('option', Point(1600, 720), '再见')
    assert dialogue_action(op, screen, action).result == R.WAIT
    assert pressed(op) == ['xbox_dpad_down']
    screen[:] = 0
    screen[695:745, 1480:1720] = [240, 230, 0]
    assert dialogue_action(op, screen, action).result == R.WAIT
    assert pressed(op) == ['xbox_dpad_down', 'xbox_a']
    dialogue_action(op, screen, action)
    assert len(pressed(op)) == 2


def test_skip_confirmation_needs_the_confirm_button_focus():
    op, screen = setup()
    action = DialogueAction('confirm_skip', Point(1120, 620), '确认跳过')
    assert dialogue_action(op, screen, action).result == R.RETRY
    assert not pressed(op)
    screen[592:648, 1000:1240] = [240, 230, 0]
    assert dialogue_action(op, screen, action).result == R.WAIT
    assert pressed(op) == ['xbox_a']


def test_skip_button_requires_its_printed_controller_glyph():
    rows = [row('跳过', 1750, 80)]
    op, screen = setup(rows)
    action = DialogueAction('skip', Point(1750, 80), '跳过剧情')
    assert dialogue_action(op, screen, action).result == R.RETRY and not pressed(op)
    rows.insert(0, row('X', 1690, 80))
    assert dialogue_action(op, screen, action).result == R.WAIT
    assert pressed(op) == ['xbox_x']


def test_menu_state_is_kept_only_after_a_verified_menu_press():
    rows = [row('Y', 1690, 80), row('菜单', 1750, 80)]
    op, screen = setup(rows)
    assert dialogue_action(op, screen, DialogueAction('menu', Point(1750, 80), '展开剧情菜单')).result == R.WAIT
    assert op._dialogue_menu_opened
    rows[:] = [row('X', 1690, 200), row('自动', 1750, 200)]
    assert dialogue_action(op, screen, DialogueAction('auto', Point(1750, 200), '开启剧情自动播放')).result == R.WAIT
    assert not op._dialogue_menu_opened
    assert pressed(op) == ['xbox_y', 'xbox_x']


def test_background_story_does_not_fall_through_to_legacy_mouse_branches():
    op, screen = setup()
    op.last_screenshot = screen
    op.run_mode = 0
    op._need_pause_in_background = lambda: False
    op._do_dialog_click = Mock(return_value=op.round_retry('等待对话'))
    op.round_by_find_and_click_area = Mock()
    op.round_by_ocr_and_click = Mock()
    result = op.story_mode()
    assert result.result == R.RETRY
    op._do_dialog_click.assert_called_once()
    op.round_by_find_and_click_area.assert_not_called()
    op.round_by_ocr_and_click.assert_not_called()
    op.ctx.controller.click.assert_not_called()
