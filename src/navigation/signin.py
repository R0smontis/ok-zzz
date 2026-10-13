"""每日签到 alternatives in the background: 刮刮卡 at the 报刊亭 and 卦象集录 at 阿朔.

All three sign-ins (吼吼饼铺, 刮刮卡, 卦象集录) share one reward a day. Verified live on
2026-10-12 with the day's reward already taken at the bakery: the 报刊亭 page shows the
刮刮卡 button under an X prompt, and opening it answers 「今日已经完成过一次相同类型的奖励领取」
with a focused 确认 that A accepts.
"""
import numpy as np

from onedragon.base.geometry.rectangle import Rect
from onedragon.utils.log_utils import log
from src.controls.gamepad import press as pad

DIALOGUE_OPTIONS = ('叫醒他', '叫醒嗷呜', '只是来看刮刮卡和报纸')
PROMPTS = Rect(1100, 985, 1920, 1075)
ALREADY_DONE = '按钮-同类型确认'


def _text(value) -> str:
    return str(value).replace(' ', '')


def _rows(op, screen, rect):
    rows = op.ctx.ocr_service.get_ocr_result_list(image=screen, rect=rect)
    return rows if isinstance(rows, (list, tuple)) else []


def _press(op, button, counter, limit, status):
    count = op.__dict__.get(counter, 0)
    if count >= limit:
        return op.round_fail(f'{status}未生效')
    op.__dict__[counter] = count + 1
    pad(op.ctx, button)
    return op.round_wait(status, wait=1.2)


def newsstand_step(op, screen):
    """报刊亭 → the 刮刮卡 page, or report the day's reward taken elsewhere."""
    found = lambda area: op.round_by_find_area(screen, '报刊亭', area).is_success
    if found('每日可刮取一次'):
        return op.round_success('每日可刮取一次')
    if found(ALREADY_DONE):
        op._signin_taken = True
        return _press(op, 'a', '_signin_confirms', 3, '手柄确认今日已领取同类奖励')
    if found('刮刮卡'):
        if getattr(op, '_signin_taken', False):
            return op.round_success(ALREADY_DONE)
        return _press(op, 'x', '_scratch_opens', 3, '手柄打开刮刮卡')
    options = [r for r in _rows(op, screen, op.ctx.screen_loader.get_area('报刊亭', '对话选项').rect)
               if _text(r.data) in DIALOGUE_OPTIONS]
    if options or found('嗷呜被你叫醒了') or found('嗷呜标题'):
        # Every 嗷呜 dialogue choice leads to the newsstand, so the focused one is fine.
        return _press(op, 'a', '_scratch_dialogue', 6, '手柄继续嗷呜对话')
    return op.round_retry('未识别报刊亭画面，未操作', wait=1)


def unverified_gesture(op, screen, name):
    """The scratch / divination gesture has not been seen with a free reward yet: stop, don't guess."""
    prompts = ' '.join(_text(r.data) for r in _rows(op, screen, PROMPTS))
    log.warning('%s页面的手柄提示：%s', name, prompts or '无')
    return op.round_fail(f'{name}后台操作尚待实机核验（今日奖励未领取时才出现），未操作')


def trigrams_step(op, screen):
    """阿朔: A 占卜 on the 卦象集录 page; A accepts the 确认 that follows (reward or already taken)."""
    rows = _rows(op, screen, Rect(0, 400, 1920, 1080))
    texts = [_text(r.data) for r in rows]
    if any('滑动屏幕以获取卦象' in t for t in texts):
        return unverified_gesture(op, screen, '卦象集录')
    if '确认' in texts:
        op.claim_reward = True
        return _press(op, 'a', '_trigram_confirms', 3, '手柄确认卦象结果')
    if any(t in ('卦象集录', '卦象集錄') for t in texts) and '占卜' in texts:
        if getattr(op, 'claim_reward', False):
            return op.round_success('卦象集录')
        return _press(op, 'a', '_trigram_divines', 3, '手柄占卜')
    return op.round_retry('未识别卦象集录画面，未操作', wait=1)


def scratch_step(op, screen):
    """The 刮刮卡 page prints 「R 刮一刮」: right-stick strokes scrape the coating (live 2026-10-13).

    Strokes from the centre in the four directions clear it within one round. The game then
    shows the prizes with only 「B 返回」 left, also when the card is opened again that day.
    """
    card = op.round_by_find_area(screen, '报刊亭', '每日可刮取一次').is_success
    prompts = [_text(r.data) for r in _rows(op, screen, Rect(760, 700, 1160, 780))]
    count = op.__dict__.get('_scratch_rounds', 0)
    if not card:
        if count == 0:
            return op.round_retry('等待刮刮卡画面，未操作', wait=1)
        return op.round_success('刮刮卡已刮开')
    coating = screen[530:615, 810:1110]
    scraped = bool(coating.size) and float(np.mean(coating.max(axis=2) < 60)) < .3
    if not any('刮一刮' in t for t in prompts) or scraped:
        return op.round_success('刮刮卡已刮开') if '返回' in prompts or scraped else op.round_retry(
            '等待刮刮卡提示，未操作', wait=1)
    if count >= 4:
        return op.round_fail('手柄刮刮卡未生效')
    op._scratch_rounds = count + 1
    for _ in range(3):
        for direction in ('up', 'right', 'down', 'left'):
            pad(op.ctx, 'rs_' + direction, .2)
    return op.round_wait('手柄右摇杆刮刮卡', wait=1.5)
