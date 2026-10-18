"""兑换码 in the background: 菜单 → 更多 → 兑换码, paste with Y, redeem with A.

On the controller layout of the 兑换码 panel Y pastes the clipboard into the empty field
and clears a filled one; the d-pad moves the focus to 「兑换」. The menus ignore window
message clicks and typing, but the paste reads the clipboard and needs no foreground
(verified live 2026-10-12: ZZZ888 → 「兑换成功，请稍后前往邮箱领取」).
"""
import re
import time

import numpy as np

from onedragon.base.geometry.rectangle import Rect
from onedragon.utils.log_utils import log
from src.controls.gamepad import press as pad
from src.navigation.common import bump, norm_text, ocr_rows
from src.navigation.menus import focus_mask, grid_target, main_menu_target

MORE_TITLE = Rect(480, 180, 800, 250)
MORE_GRID = Rect(500, 300, 1420, 880)
PANEL = Rect(560, 300, 1360, 760)
FIELD = Rect(700, 530, 1150, 600)
MESSAGE = Rect(560, 620, 1360, 675)
BUTTON = Rect(830, 680, 1090, 745)
# The cell outline sits ~80 px either side of the centred label.
GRID_HALF_WIDTH = 79


def _text(value) -> str:
    return norm_text(value, 'redemption')


def same_code(read: str, code: str) -> bool:
    """OCR confuses O/0 and I/1 in codes; letters and digits otherwise have to match."""
    norm = lambda s: re.sub(r'[^A-Z0-9]', '', s.upper()).replace('O', '0').replace('I', '1')
    return bool(read) and norm(read) == norm(code)


def more_panel_open(op, screen) -> bool:
    return any(_text(r.data) == '更多功能' for r in ocr_rows(op, screen,MORE_TITLE))


def code_panel(op, screen):
    """(field text, result message, button label) on the 兑换码 panel, or None when it is not open."""
    rows = ocr_rows(op, screen,PANEL)
    if not any(_text(r.data) == '兑换码' and r.center.y < 400 for r in rows):
        return None
    inside = lambda r, rect: rect.x1 <= r.center.x < rect.x2 and rect.y1 <= r.center.y < rect.y2
    field = ''.join(_text(r.data) for r in sorted(rows, key=lambda r: r.center.x)
                    if inside(r, FIELD) and re.fullmatch(r'[A-Za-z0-9]+', _text(r.data)))
    message = next((_text(r.data) for r in rows if inside(r, MESSAGE) and len(_text(r.data)) > 2), '')
    button = next((_text(r.data) for r in rows if inside(r, BUTTON) and _text(r.data).startswith('兑换')), None)
    return field, message, button


def button_focused(screen) -> bool:
    part = screen[BUTTON.y1:BUTTON.y2, BUTTON.x1:BUTTON.x2]
    return bool(part.size) and np.mean(focus_mask(part)) > .35


# 剪贴板里除文本外还可能有图片、文件等；粘贴前全部取出，粘贴后原样放回。
# 位图/图元等 GDI 句柄格式无法安全复制，跳过（图片通常同时带 DIB 数据格式）。
_CLIPBOARD_SKIP = ('CF_BITMAP', 'CF_PALETTE', 'CF_METAFILEPICT', 'CF_ENHMETAFILE',
                   'CF_OWNERDISPLAY', 'CF_DSPBITMAP', 'CF_DSPMETAFILEPICT', 'CF_DSPENHMETAFILE',
                   'CF_DSPTEXT')


def snapshot_clipboard(cb, win32con):
    """[(format, data)] of everything that can be put back later."""
    skipped = {getattr(win32con, name) for name in _CLIPBOARD_SKIP if hasattr(win32con, name)}
    formats, current = [], 0
    while True:
        current = cb.EnumClipboardFormats(current)
        if not current:
            break
        if current in skipped:
            continue
        try:
            formats.append((current, cb.GetClipboardData(current)))
        except Exception:
            continue  # 该格式不可读：宁可少恢复一种，也不让粘贴失败
    return formats


def restore_clipboard(cb, formats):
    cb.EmptyClipboard()
    for fmt, data in formats:
        try:
            cb.SetClipboardData(fmt, data)
        except Exception:
            continue


def paste_code(ctx, code: str) -> None:
    """Press Y with the code on the clipboard, then put the user's own clipboard back."""
    import win32clipboard as cb
    import win32con

    def open_clipboard():
        for _ in range(10):
            try:
                cb.OpenClipboard()
                return
            except Exception:
                time.sleep(.05)
        cb.OpenClipboard()  # Raise the real error after retrying a busy clipboard.

    previous = []
    open_clipboard()
    try:
        previous = snapshot_clipboard(cb, win32con)
        cb.EmptyClipboard()
        cb.SetClipboardText(code, win32con.CF_UNICODETEXT)
    finally:
        cb.CloseClipboard()
    try:
        pad(ctx, 'y')
        time.sleep(.4)  # The game reads the clipboard while handling the press.
    finally:
        open_clipboard()
        try:
            restore_clipboard(cb, previous)
        finally:
            cb.CloseClipboard()


def _cooling(button) -> bool:
    """The 兑换 label counts down as 兑换(5)…兑换(1) after a submission."""
    return button is not None and ('(' in button or '（' in button)


def open_more(op, screen):
    if more_panel_open(op, screen) or code_panel(op, screen) is not None:
        return op.round_success('更多功能已打开')
    return main_menu_target(op, '更多')


def open_code_panel(op, screen):
    if code_panel(op, screen) is not None:
        return op.round_success('兑换码已打开')
    if more_panel_open(op, screen):
        return grid_target(op, screen, '兑换码', MORE_GRID, half_width=GRID_HALF_WIDTH)
    if bump(op,'_redeem_panel_waits', 6):
        return op.round_fail('未打开兑换码面板')
    return op.round_wait('等待兑换码面板', wait=.6)


def _next_code(op):
    op.code_idx += 1
    for name in ('_redeem_phase', '_redeem_pastes', '_redeem_clears', '_redeem_moves',
                 '_redeem_cooldown', '_redeem_submits', '_redeem_results', '_redeem_answer_waits'):
        op.__dict__.pop(name, None)


def redeem_round(op, screen, codes, mark_used):
    """One verified step on the 兑换码 panel. `mark_used(code)` records a code the game answered."""
    if op.code_idx >= len(codes):
        return op.round_success('全部兑换完毕')
    state = code_panel(op, screen)
    if state is None:
        if bump(op,'_redeem_panel_waits', 6):
            return op.round_fail('兑换码面板未打开')
        return op.round_wait('等待兑换码面板', wait=.6)
    op._redeem_panel_waits = 0
    field, message, button = state
    code = codes[op.code_idx]
    phase = op.__dict__.setdefault('_redeem_phase', 'paste')

    if phase == 'result':
        if message:
            log.info('兑换码 %s：%s', code, message)
            mark_used(code)
            _next_code(op)
            return op.round_wait(f'兑换码 {code}：{message}', wait=.3)
        # The game answers late and briefly: the red line appears near the end of the 兑换(5)→(1)
        # countdown and stays about one second (live 2026-10-17). Poll quickly until it ends.
        if _cooling(button) and not bump(op,'_redeem_answer_waits', 30):
            return op.round_wait('等待兑换结果（按钮倒计时）', wait=.2)
        if bump(op,'_redeem_results', 6):
            # The press was verified on a focused, ready button; do not redeem the same code again.
            log.warning('兑换码 %s 已提交，未读到结果提示', code)
            mark_used(code)
            _next_code(op)
            return op.round_wait(f'兑换码 {code} 未读到结果，继续下一个', wait=.3)
        return op.round_wait('等待兑换结果', wait=.5)

    if not same_code(field, code):
        op._redeem_phase = 'paste'
        if field:
            if bump(op,'_redeem_clears', 3):
                return op.round_fail('手柄清除兑换码输入框未生效')
            pad(op.ctx, 'y')
            return op.round_wait('手柄清除输入框', wait=.8)
        if bump(op,'_redeem_pastes', 3):
            return op.round_fail('手柄粘贴兑换码未生效')
        paste_code(op.ctx, code)
        return op.round_wait(f'手柄粘贴兑换码 {code}', wait=.6)

    op._redeem_phase = 'submit'
    if not button_focused(screen):
        if bump(op,'_redeem_moves', 4):
            return op.round_fail('手柄选择兑换按钮未生效')
        pad(op.ctx, 'dpad_down')
        return op.round_wait('手柄选择兑换按钮', wait=.6)
    if button is None or _cooling(button):
        if bump(op,'_redeem_cooldown', 10):
            return op.round_fail('兑换按钮一直不可用')
        return op.round_wait('兑换按钮冷却中', wait=1)
    if bump(op,'_redeem_submits', 2):
        return op.round_fail('兑换按钮未响应')
    pad(op.ctx, 'a')
    op._redeem_phase = 'result'
    return op.round_wait(f'手柄兑换 {code}', wait=1.2)
