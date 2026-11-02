"""Close informational game popups that would otherwise block whatever task is running.

The game shows notices such as 「迷失之地」内容更新 or version and event announcements on top of
any screen. They are dialogs with the red × close button and only text inside. Dialogs a task
opens itself (快捷使用, 兑换码, 周期挑战奖励, 游历时间选择 ...) carry the same × but also action
labels and button hints; pressing B there would cancel what the task is doing, so they are left
to the task. Every operation node checks this before its own logic (Operation._execute_one_round),
so a new notice needs no task-specific handling.
"""
import numpy as np

from onedragon.base.geometry.point import Point
from onedragon.base.geometry.rectangle import Rect
from src.controls.gamepad import press as pad
from src.navigation.common import OCR_FIXES, cjk_count, norm_text, ocr_rows

# The × of dialogs centred on screen lies here; full-screen menus put theirs further right (x≈1760).
CLOSE_SEARCH = Rect(900, 120, 1740, 480)
CLOSE_THRESHOLD = .85
# The × button's red fill, counted on a 1/4-scale sample (a real × gives ~180-210 pixels). Most
# frames have almost none, so the per-round check usually stops here (~1 ms instead of ~40 ms).
CLOSE_MIN_RED = 100
# Words that mark a dialog the task is operating: buttons, controller hints and inputs. Only short
# rows count, so a notice sentence such as 「活动开始后可前往…」 is still recognised as a notice.
ACTION_WORDS = ('确认', '确定', '取消', '返回', '选择', '领取', '兑换', '粘贴', '清除', '前往', '输入',
                '派遣', '开始', '出战', '购买', '使用', '跳过', '继续', '重试', '退出', '登录')
ACTION_LABEL_LENGTH = 6
DIALOG_HEIGHT = 620
MAX_PRESSES = 4


def _text(row):
    return norm_text(row.data, fixes=OCR_FIXES['restore_charge']).strip()


def has_close_red(screen):
    part = screen[CLOSE_SEARCH.y1:CLOSE_SEARCH.y2:4, CLOSE_SEARCH.x1:CLOSE_SEARCH.x2:4]
    red = (part[..., 0] > 170) & (part[..., 1] < 90) & (part[..., 2] < 80)
    return int(np.count_nonzero(red)) >= CLOSE_MIN_RED


def info_popup(op, screen):
    """(× centre, dialog title) of an informational popup on this frame, else None."""
    if screen is None or getattr(screen, 'ndim', 0) != 3 or not has_close_red(screen):
        return None
    found = op.ctx.tm.crop_and_match_template(screen, CLOSE_SEARCH, 'menu', 'btn_close',
                                              threshold=CLOSE_THRESHOLD).max
    if found is None:
        return None
    close = Point(found.center.x + CLOSE_SEARCH.x1, found.center.y + CLOSE_SEARCH.y1)
    dialog = Rect(max(0, close.x - 1100), max(0, close.y - 40), min(1920, close.x + 40),
                  min(1080, close.y + DIALOG_HEIGHT))
    rows = [row for row in ocr_rows(op, screen, dialog)
            if abs(row.center.x - close.x) > 40 or abs(row.center.y - close.y) > 40]  # The × itself.
    texts = [_text(row) for row in rows]
    if any(len(text) <= ACTION_LABEL_LENGTH and word in text for text in texts for word in ACTION_WORDS):
        return None
    if sum(cjk_count(text) for text in texts) < 4:
        return None  # Not a readable dialog; nothing proves it is safe to close.
    title_rows = sorted((row for row in rows if abs(row.center.y - close.y) < 45),
                        key=lambda row: row.center.x)
    title = ''.join(_text(row) for row in title_rows) or texts[0]
    return close, title


def dismiss_info_popup(op):
    """WAIT after closing an informational popup, FAIL when it does not close, None when there is none."""
    popup = info_popup(op, op.last_screenshot)
    if popup is None:
        op.__dict__.pop('_info_popup', None)
        return None
    close, title = popup
    previous = op.__dict__.get('_info_popup')
    presses = previous[1] + 1 if previous is not None and previous[0] == title else 1
    if presses > MAX_PRESSES:
        op.__dict__.pop('_info_popup', None)
        return op.round_fail(f'弹窗「{title}」无法关闭，请手动关闭后重试')
    op.__dict__['_info_popup'] = (title, presses)
    if getattr(op.ctx.controller, 'background_mode', False):
        # B closes these notices; one A in between covers a notice that only reacts to confirm.
        pad(op.ctx, 'a' if presses == MAX_PRESSES - 1 else 'b')
    else:
        op.ctx.controller.click(close)
    return op.round_wait(f'关闭弹窗：{title}', wait=1)
