"""丽都城募's once-per-season screens, handled inside the app so the daily keeps going.

Opening 丽都城募 in a new season first shows the plan intro (成长计划 / 典藏计划 with
「开启丽都城募」 at the bottom right), then the reward-scheme picker 「请选择丽都城募奖励」.
「开启丽都城募」 opens the free track; the paid plans are separate panels and 「解锁丽都城募」
is a different button, so neither is ever pressed here. The picker is confirmed with its
preselected scheme (「确认方案」, X on controller prompts, 2026-10-21).
"""
from onedragon.base.geometry.rectangle import Rect
from src.navigation.common import bump, norm_text, ocr_rows
from src.navigation.menus import pad_press, press_labelled

INTRO_BUTTON = '开启丽都城募'
INTRO_RECT = Rect(1500, 980, 1920, 1065)
PICKER_TITLE = '请选择丽都城募奖励'
PICKER_TITLE_RECT = Rect(600, 250, 1320, 340)
PICKER_CONFIRM = '确认方案'
PICKER_BUTTON_RECT = Rect(560, 730, 1400, 830)
REVEAL_PRESSES = 2
CONFIRM_PRESSES = 3


def season_screen(op, screen):
    """A round result while the intro or the picker is shown; None on any other screen."""
    if any(PICKER_TITLE in norm_text(r.data) for r in ocr_rows(op, screen, PICKER_TITLE_RECT)):
        if getattr(op.ctx.controller, 'background_mode', False):
            return _press(op, screen, PICKER_CONFIRM, PICKER_BUTTON_RECT, '_city_fund_picker_presses',
                          '确认丽都城募奖励方案')
        return _click(op, screen, PICKER_CONFIRM, PICKER_BUTTON_RECT, '确认丽都城募奖励方案')
    rows = ocr_rows(op, screen, INTRO_RECT)
    if any(norm_text(r.data).endswith(INTRO_BUTTON) for r in rows):
        if getattr(op.ctx.controller, 'background_mode', False):
            return _press(op, screen, INTRO_BUTTON, INTRO_RECT, '_city_fund_intro_presses', INTRO_BUTTON)
        return _click(op, screen, INTRO_BUTTON, INTRO_RECT, INTRO_BUTTON)
    return None


def _press(op, screen, label, rect, counter, action):
    if bump(op, counter, CONFIRM_PRESSES):
        return op.round_fail(f'手柄{action}后画面未变化')
    button = press_labelled(op, screen, label, rect)
    if button:
        return op.round_wait(f'手柄{action}（{button.upper()}），等待实际画面', wait=1.5)
    op.__dict__[counter] -= 1  # Nothing was pressed.
    # Keyboard prompts print no button letter; a d-pad press switches the game to controller prompts.
    if bump(op, '_city_fund_reveal_presses', REVEAL_PRESSES):
        return op.round_fail(f'未核验「{label}」的手柄提示，未操作')
    pad_press(op, 'dpad_down')
    return op.round_wait(f'显示手柄提示以{action}', wait=1)


def _click(op, screen, label, rect, action):
    target = next((r for r in ocr_rows(op, screen, rect) if norm_text(r.data).endswith(label)), None)
    if target is None or bump(op, '_city_fund_clicks', CONFIRM_PRESSES):
        return op.round_fail(f'{action}后画面未变化')
    op.ctx.controller.click(target.center)
    return op.round_wait(action, wait=1.5)
