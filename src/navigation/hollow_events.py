"""Controller actions on TV-board events and free resonium cards, verified on opening frames.

A glyph identifies dialogue continuation / a selected card; the event option itself is filled
yellow. Every selection waits for the old option to disappear before reporting success.
"""
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from onedragon.base.geometry.rectangle import Rect
from onedragon.utils import os_utils
from src.controls.gamepad import press as pad
from src.navigation.common import norm_text, ocr_rows
from src.navigation.menus import focus_mask


EVENT = Rect(1230, 200, 1920, 955)


def _text(value):
    return norm_text(value, 'hollow_events')


@lru_cache(maxsize=1)
def _a_template():
    path = Path(os_utils.get_resource_path('assets', 'template', 'hollow', 'dialog_continue_a', 'raw.png'))
    if not path.exists():
        path = Path(__file__).resolve().parents[2] / 'assets/template/hollow/dialog_continue_a/raw.png'
    image = cv2.imread(str(path))
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB) if image is not None else None


def _a_positions(screen, rect):
    template = _a_template()
    part = screen[rect.y1:rect.y2, rect.x1:rect.x2]
    if template is None or part.shape[0] < template.shape[0] or part.shape[1] < template.shape[1]:
        return []
    scores = cv2.matchTemplate(part, template, cv2.TM_SQDIFF_NORMED)
    positions = []
    for _ in range(4):
        score, _, (x, y), _ = cv2.minMaxLoc(scores)
        if score > .08:
            break
        positions.append((rect.x1 + x + template.shape[1] // 2, rect.y1 + y + template.shape[0] // 2))
        scores[max(0, y - 25):y + 26, max(0, x - 25):x + 26] = 1
    return positions


def _event_focus(screen):
    # Options start right under the question; with four options the first sits at y≈410.
    mask = focus_mask(screen[360:950, 1280:1920]).astype(np.uint8)
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    boxes = [Rect(x + 1280, y + 360, x + w + 1280, y + h + 360)
             for x, y, w, h, area in stats[1:] if w > 300 and h > 35 and area > w * h * .5]
    return boxes[0] if len(boxes) == 1 else None


def pending_option(op, screen):
    pending = getattr(op, '_pad_event_pending', None)
    if pending is None:
        return None
    rows = ocr_rows(op, screen,Rect(600, 200, 1920, 955))
    pending['waits'] += 1
    still_visible = any(SequenceMatcher(None, _text(r.data), pending['text']).ratio() >= .85
                        and abs(r.center.y - pending['y']) < 40 for r in rows)
    if rows and not still_visible:
        pending['missing'] += 1
        if pending['missing'] >= 2:
            op._pad_event_pending = None
            return op.round_success(pending['status'])
    else:
        pending['missing'] = 0
    if pending['waits'] >= 8:
        return op.round_fail('事件选择后未核验到页面变化，不重复确认')
    return op.round_wait('等待事件选项消失，未重复确认', wait=.5)


def event_option(op, screen, status, rect):
    focus = _event_focus(screen)
    rows = ocr_rows(op, screen, EVENT)
    label = min((r for r in rows if abs(r.center.y - rect.center.y) < 30),
                key=lambda r: abs(r.center.x - rect.center.x), default=None)
    if focus is None or label is None:
        return op.round_retry('事件目标及唯一焦点未核验，未操作', wait=.5)
    steps = getattr(op, '_pad_event_steps', 0)
    if steps >= 12:
        return op.round_fail(f'手柄选择事件选项未生效：{status}')
    op._pad_event_steps = steps + 1
    if focus.y1 <= rect.center.y <= focus.y2:
        pad(op.ctx, 'a')
        op._pad_event_pending = dict(text=_text(label.data), y=label.center.y, status=status, waits=0, missing=0)
        return op.round_wait(f'手柄选择事件：{status}，等待实际结果', wait=.8)
    pad(op.ctx, 'dpad_up' if rect.center.y < focus.center.y else 'dpad_down')
    return op.round_wait(f'手柄定位事件选项：{status}', wait=.5)


def advance_dialogue(op, screen):
    # A highlighted option is a decision, never paragraph continuation.
    if _event_focus(screen) is not None:
        return op.round_retry('存在未匹配的事件选项，不擅自确认', wait=.5)
    positions = _a_positions(screen, Rect(1780, 480, 1890, 880))
    if len(positions) != 1:
        return op.round_retry('事件段落A提示未核验，未操作', wait=.5)
    steps = getattr(op, '_pad_dialogue_steps', 0)
    if steps >= 12:
        return op.round_fail('事件段落继续未生效')
    op._pad_dialogue_steps = steps + 1
    pad(op.ctx, 'a')
    return op.round_wait('手柄继续已核验的事件段落', wait=.8)


def _selection_a_positions(rows, screen, word='选择'):
    labels = [r for r in rows if _text(r.data) == word and 725 < r.center.y < 815]
    reach = 66 + 22 * len(word)
    glyphs = [(r.center.x, r.center.y) for r in rows if _text(r.data) in ('A', 'Ａ')
              and 725 < r.center.y < 815
              and any(abs(r.center.y - label.center.y) < 20 and 0 < label.center.x - r.center.x < reach for label in labels)]
    if glyphs:
        return glyphs
    # OCR may drop the glyph; only the focused card shows the prompt, so a single label suffices.
    if len(labels) == 1:
        return [(labels[0].center.x - 22 * len(word), labels[0].center.y)]
    return _a_positions(screen, Rect(330, 725, 1580, 815))


def free_resonium(op, screen):
    return resonium_card(op, screen, '选择')


def resonium_card(op, screen, word, lowest=False):
    """Resonium cards whose buttons read `word` (选择/丢弃/交换/催化/抵押欠款); `lowest` picks the
    least wanted card, as upstream does when dropping."""
    from zzz_od.hollow_zero.event.resonium_utils import choose_resonium_by_priority
    rows = ocr_rows(op, screen,Rect(300, 120, 1630, 830))
    cards = []
    for row in rows:
        text = _text(row.data)
        if not (460 < row.center.y < 530 and text.startswith('[')):
            continue
        item = op.ctx.withered_domain.data_service.match_resonium_by_ocr_full(text)
        if item is not None:
            cards.append((row, item))
    signature = tuple((item.category, item.name, (row.center.x - 300) // 410) for row, item in cards)
    pending = getattr(op, '_pad_resonium_pending', None)
    if pending is not None:
        # Cards fading out may leave frames without text; two changed frames in a row suffice.
        changed = signature != pending['signature']
        pending['changed'] = pending.get('changed', 0) + 1 if changed else 0
        if pending['changed'] >= 2:
            op._pad_resonium_pending = None
            return op.round_success(pending['name'])
        pending['waits'] += 1
        if pending['waits'] >= 6:
            return op.round_fail('鸣徽确认未生效，不重复选择')
        return op.round_wait('等待鸣徽选择结果', wait=.5)
    if not cards:
        return op.round_retry('未识别可选鸣徽名称，未操作', wait=.5)
    positions = _selection_a_positions(rows, screen, word)
    if len(positions) != 1:
        return op.round_retry(f'鸣徽{word}A提示未唯一核验，未操作', wait=.5)
    order = choose_resonium_by_priority([item for _, item in cards], op.ctx.withered_domain.challenge_config.resonium_priority)
    if not order:
        return op.round_fail('鸣徽优先级无返回')
    row, item = cards[order[-1] if lowest else order[0]]
    selected_x = positions[0][0]
    moves = getattr(op, '_pad_resonium_moves', 0)
    if abs(row.center.x - selected_x) < 120:
        pad(op.ctx, 'a')
        op._pad_resonium_pending = dict(signature=signature, name=item.name, waits=0)
        return op.round_wait(f'手柄{word}鸣徽 {item.category} {item.name}', wait=.8)
    if moves >= 6:
        return op.round_fail('手柄定位鸣徽未生效')
    op._pad_resonium_moves = moves + 1
    pad(op.ctx, 'dpad_right' if row.center.x > selected_x else 'dpad_left')
    return op.round_wait(f'手柄定位鸣徽 {item.category} {item.name}', wait=.5)


def remove_corruption(op, screen):
    """The clear panel fills the active 清除 button yellow; A removes one in-run corruption."""
    from src.navigation.menus import label_focused
    rows = ocr_rows(op, screen,Rect(240, 640, 1750, 745))
    buttons = [row for row in rows if _text(row.data) == '清除']
    pending = getattr(op, '_pad_clear_pending', None)
    if pending is not None:
        pending['waits'] += 1
        if not buttons and op.round_by_find_area(screen, '零号空洞-事件', '背包').is_success:
            pending['closed'] += 1
            if pending['closed'] >= 2:
                return op.round_success('已核验侵蚀面板关闭')
        else:
            pending['closed'] = 0
        if pending['waits'] >= 6:
            return op.round_fail('侵蚀清除未生效，不重复确认')
        return op.round_wait('等待侵蚀面板关闭，未重复确认', wait=.5)
    focused = [row for row in buttons if label_focused(screen, row.center, 95)]
    if len(focused) != 1:
        return op.round_retry('未核验唯一可清除按钮，未操作', wait=.5)
    pad(op.ctx, 'a')
    op._pad_clear_pending = dict(waits=0, closed=0)
    return op.round_wait('手柄清除本局侵蚀，等待面板关闭', wait=.8)


def default_card(op, screen, word='选择'):
    """Upstream's fallback picks any card; the pad confirms the focused one under the A prompt.

    Used for cards that are not resonium (e.g. 临时拍档's assist bangboo).
    """
    rows = ocr_rows(op, screen,Rect(300, 120, 1630, 830))
    titles = tuple((_text(r.data), (r.center.x - 300) // 410) for r in rows
                   if 460 < r.center.y < 530 and _text(r.data).startswith('['))
    pending = getattr(op, '_pad_default_pending', None)
    if pending is not None:
        pending['waits'] += 1
        pending['changed'] = pending['changed'] + 1 if titles != pending['titles'] else 0
        if pending['changed'] >= 2:
            op._pad_default_pending = None
            return op.round_success('已核验卡片选择生效')
        if pending['waits'] >= 6:
            return op.round_fail('卡片选择未生效，不重复确认')
        return op.round_wait('等待卡片选择结果', wait=.5)
    if not titles:
        return op.round_retry('未识别可选卡片，未操作', wait=.5)
    if len(_selection_a_positions(rows, screen, word)) != 1:
        return op.round_retry('卡片选择A提示未唯一核验，未操作', wait=.5)
    pad(op.ctx, 'a')
    op._pad_default_pending = dict(titles=titles, waits=0, changed=0)
    return op.round_wait('手柄选择当前焦点卡片（兜底）', wait=.8)


def bottom_button(op, screen, labels, band=Rect(240, 730, 1750, 900)):
    """A row of buttons where the focused one is filled yellow (及时补给, 确认鸣徽, ...)."""
    from src.navigation.menus import label_focused
    rows = ocr_rows(op, screen,band)
    buttons = [r for r in rows if len(_text(r.data)) >= 2]
    pending = getattr(op, '_pad_button_pending', None)
    if pending is not None:
        pending['waits'] += 1
        gone = not any(_text(r.data) == pending['label'] and abs(r.center.x - pending['x']) < 80 for r in buttons)
        pending['gone'] = pending['gone'] + 1 if gone else 0
        if pending['gone'] >= 2:
            op._pad_button_pending = None
            return op.round_success(pending['label'])
        if pending['waits'] >= 8:
            return op.round_fail(f'手柄确认{pending["label"]}未生效，不重复确认')
        if pending['waits'] == 4 and not gone:
            # Popups ignore presses while they animate in (live 2026-10-14 「受到侵蚀」): one spaced retry.
            pad(op.ctx, 'a')
            return op.round_wait(f'{pending["label"]}未变化，间隔后重按一次', wait=.6)
        return op.round_wait(f'等待{pending["label"]}生效，未重复确认', wait=.5)
    wanted = [_text(w) for w in labels]
    target = next((r for w in wanted for r in buttons if _text(r.data) == w), None)
    focused = [r for r in buttons if label_focused(screen, r.center, 110)]
    if target is None or len(focused) != 1:
        return op.round_retry('底部按钮及唯一焦点未核验，未操作', wait=.5)
    if abs(focused[0].center.x - target.center.x) < 60:
        pad(op.ctx, 'a')
        op._pad_button_pending = dict(label=_text(target.data), x=target.center.x, waits=0, gone=0)
        return op.round_wait(f'手柄确认 {_text(target.data)}', wait=.8)
    moves = getattr(op, '_pad_button_moves', 0)
    if moves >= 6:
        return op.round_fail(f'手柄定位按钮 {_text(target.data)} 未生效')
    op._pad_button_moves = moves + 1
    pad(op.ctx, 'dpad_right' if target.center.x > focused[0].center.x else 'dpad_left')
    return op.round_wait(f'手柄定位按钮：{_text(focused[0].data)} → {_text(target.data)}', wait=.5)


def pad_option(op, screen, words, status=None, lcs=.6):
    """Event-panel option chosen by its text, then verified like other event options.

    Without `status` the matched word is reported, so callers can tell which option was taken."""
    pending = pending_option(op, screen)
    if pending is not None:
        return pending
    rows = ocr_rows(op, screen, EVENT)
    best = None  # earlier words win ties
    for word in words:
        for row in rows:
            ratio = SequenceMatcher(None, _text(row.data), _text(word)).ratio()
            if ratio >= lcs and (best is None or ratio > best[0]):
                best = (ratio, row, word)
    if best is None:
        return op.round_retry(f'未识别事件选项 {status or words[0]}，未操作', wait=.5)
    return event_option(op, screen, status or best[2], best[1].rect)


def back_out(op, screen, visible):
    """B leaves a page with a back button (旧都失物); success once `visible` is gone twice."""
    pending = getattr(op, '_pad_back_pending', None)
    if pending is not None:
        pending['waits'] += 1
        pending['gone'] = 0 if visible else pending['gone'] + 1
        if pending['gone'] >= 2:
            op._pad_back_pending = None
            return op.round_success('已返回')
        if pending['waits'] >= 6:
            return op.round_fail('手柄返回未生效，不重复操作')
        return op.round_wait('等待返回生效', wait=.5)
    if not visible:
        return op.round_retry('返回按钮未核验，未操作', wait=.5)
    pad(op.ctx, 'b')
    op._pad_back_pending = dict(waits=0, gone=0)
    return op.round_wait('手柄返回', wait=.8)


def result_confirm(op, screen):
    """挑战结果 (A 确定) and the 结算周期上限 dialog (确认) after a hollow battle."""
    rows = ocr_rows(op, screen,Rect(0, 0, 1920, 1080))

    def inside(row, x1, y1, x2, y2):
        return x1 <= row.center.x < x2 and y1 <= row.center.y < y2

    words = [_text(r.data) for r in rows]
    result = any('挑战结果' in w for w in words) or ('总计用时' in ''.join(words) and '完成关卡' in words)
    dialog = any(_text(r.data) == '确认' and inside(r, 878, 598, 1074, 656) for r in rows)
    confirm = any(_text(r.data) == '确定' and inside(r, 1048, 810, 1268, 1032) for r in rows)
    pending = getattr(op, '_pad_result_pending', None)
    if pending is not None:
        pending['waits'] += 1
        pending['gone'] = 0 if (result or dialog) else pending['gone'] + 1
        if pending['gone'] >= 2:
            op._pad_result_pending = None
            return op.round_success('确定')
        if pending['waits'] >= 8:
            return op.round_fail('战斗结算确认未生效，不重复确认')
        if pending['waits'] % 4 == 0 and (dialog or (result and confirm)):
            # The prompt ignores presses for a moment after it appears; one spaced retry.
            pad(op.ctx, 'a')
        return op.round_wait('等待战斗结算关闭', wait=.6)
    if not (dialog or (result and confirm)):
        return op.round_retry('战斗结算确认未核验，未操作', wait=.6)
    pad(op.ctx, 'a')
    op._pad_result_pending = dict(waits=0, gone=0)
    return op.round_wait('手柄确认战斗结算', wait=1)


def _words(op, screen, rect=Rect(0, 0, 1920, 1080)):
    return [(_text(r.data), r) for r in ocr_rows(op, screen,rect)]


def _dialog(op, screen):
    rows = _words(op, screen, Rect(500, 520, 1420, 680))
    confirm = next((r for w, r in rows if w == '确认'), None)
    cancel = next((r for w, r in rows if w == '取消'), None)
    return confirm, cancel


def exit_open_menu(op, screen):
    """Board → in-run menu whose footer reads X 暂离 / Y 放弃 / A 选择 / B 返回."""
    footer = {w for w, _ in _words(op, screen, Rect(1300, 960, 1920, 1060))}
    if '放弃' in footer and any('暂离' in w for w in footer):
        return op.round_success('菜单已打开')
    if not any(w == '背包' for w, _ in _words(op, screen, Rect(1400, 950, 1600, 1030))):
        return op.round_retry('未核验空洞棋盘，未打开菜单', wait=.6)
    opens = getattr(op, '_pad_exit_menu', 0)
    if opens >= 3:
        return op.round_fail('手柄打开空洞菜单未生效')
    op._pad_exit_menu = opens + 1
    pad(op.ctx, 'start')
    return op.round_wait('手柄打开空洞菜单', wait=1)


def exit_abandon(op, screen):
    confirm, cancel = _dialog(op, screen)
    if confirm is not None and cancel is not None:
        return op.round_success('放弃确认框已出现')
    footer = {w for w, _ in _words(op, screen, Rect(1300, 960, 1920, 1060))}
    if '放弃' not in footer:
        return op.round_retry('未核验空洞菜单的放弃按钮，未操作', wait=.6)
    presses = getattr(op, '_pad_exit_abandon', 0)
    if presses >= 3:
        return op.round_fail('手柄放弃探索未生效')
    op._pad_exit_abandon = presses + 1
    pad(op.ctx, 'y')
    return op.round_wait('手柄选择放弃探索', wait=1)


def exit_confirm(op, screen):
    from src.navigation.menus import label_focused
    confirm, cancel = _dialog(op, screen)
    pending = getattr(op, '_pad_exit_pending', None)
    if pending is not None:
        pending['waits'] += 1
        pending['gone'] = 0 if confirm is not None else pending['gone'] + 1
        if pending['gone'] >= 2:
            op._pad_exit_pending = None
            return op.round_success('已确认放弃')
        if pending['waits'] >= 8:
            return op.round_fail('确认放弃未生效，不重复确认')
        return op.round_wait('等待放弃生效', wait=.6)
    if confirm is None or cancel is None:
        return op.round_retry('放弃确认框未核验，未操作', wait=.6)
    if label_focused(screen, confirm.center, 120):
        pad(op.ctx, 'a')
        op._pad_exit_pending = dict(waits=0, gone=0)
        return op.round_wait('手柄确认放弃探索', wait=1)
    if label_focused(screen, cancel.center, 120):
        moves = getattr(op, '_pad_exit_moves', 0)
        if moves >= 3:
            return op.round_fail('手柄移到确认按钮未生效')
        op._pad_exit_moves = moves + 1
        pad(op.ctx, 'dpad_right' if confirm.center.x > cancel.center.x else 'dpad_left')
        return op.round_wait('手柄移到确认按钮', wait=.6)
    return op.round_retry('放弃确认框焦点未核验，未操作', wait=.6)


def option_enabled(screen, rect):
    """Disabled event options are drawn in grey; enabled ones are white or sit in the yellow focus.

    Only the option column (text from x≈1400) is judged; descriptions start further left.
    """
    if rect.x1 < 1380:
        return True
    focus = _event_focus(screen)
    if focus is not None and focus.y1 <= rect.center.y <= focus.y2:
        return True
    part = screen[max(0, rect.y1):rect.y2, max(0, rect.x1):rect.x2]
    return bool(part.size) and float(np.mean(np.min(part, axis=2) >= 215)) > .02


SHOP_LIST = Rect(1160, 220, 1920, 820)


def shop_items(op, screen):
    """Rows of the 鸣徽交易 list: (title row, resonium or None, price or None).

    The price sits under the icon, left of the title (live 2026-10-14)."""
    rows = ocr_rows(op, screen,SHOP_LIST)
    titles = [r for r in rows if _text(r.data).startswith('[') and r.center.x > 1300]
    items = []
    for title in sorted(titles, key=lambda r: r.center.y):
        item = op.ctx.withered_domain.data_service.match_resonium_by_ocr_full(_text(title.data))
        price = next((int(_text(r.data)) for r in rows if _text(r.data).isdigit()
                      and 1180 < r.center.x < 1400 and 50 < r.center.y - title.center.y < 160), None)
        items.append((title, item, price))
    return items


def shop_focus_y(op, screen):
    """The focused card is outlined in lime (live 2026-10-14; the small A glyph at its right end
    is often lost when the list is cropped for OCR). Its top and bottom borders bracket the title."""
    part = screen[SHOP_LIST.y1:SHOP_LIST.y2, 1400:1800]
    lit = np.mean(focus_mask(part), axis=1) > .4
    runs, start = [], None
    for y, on in enumerate(lit):
        if on and start is None:
            start = y
        elif not on and start is not None:
            runs.append((start + SHOP_LIST.y1, y - 1 + SHOP_LIST.y1))
            start = None
    if start is not None:
        runs.append((start + SHOP_LIST.y1, len(lit) - 1 + SHOP_LIST.y1))
    if not runs:
        return None
    top = runs[0][1]
    bottom = runs[1][0] if len(runs) > 1 else top + 200
    inside = [t for t, _, _ in shop_items(op, screen) if top < t.rect.y1 < bottom]
    return inside[0].center.y if len(inside) == 1 else None


def shop_coins(op, screen):
    rows = ocr_rows(op, screen,Rect(1200, 970, 1300, 1030))
    value = next((_text(r.data) for r in rows if _text(r.data).isdigit()), None)
    return int(value) if value is not None else None


def shop_choose(op, screen, priority, only_priority):
    """Move the focus to the wanted, affordable resonium.

    SUCCESS once it is focused; status '不购买' when nothing is wanted or affordable."""
    from zzz_od.hollow_zero.event.resonium_utils import choose_resonium_by_priority
    items = shop_items(op, screen)
    coins = shop_coins(op, screen)
    focus_y = shop_focus_y(op, screen)
    if not items or focus_y is None or coins is None:
        return op.round_retry('商店列表、余额及焦点未核验，未操作', wait=.6)
    candidates = [(title, item, price) for title, item, price in items
                  if item is not None and price is not None and price <= coins]
    order = choose_resonium_by_priority([item for _, item, _ in candidates], priority, only_priority=only_priority)
    if not order:
        return op.round_success('不购买')
    title = candidates[order[0]][0]
    focused = min(items, key=lambda i: abs(i[0].center.y - focus_y))[0]
    if abs(focused.center.y - title.center.y) < 40:
        return op.round_success(f'已选中 {_text(title.data)}')
    moves = getattr(op, '_pad_shop_moves', 0)
    if moves >= 8:
        return op.round_fail('手柄定位商品未生效')
    op._pad_shop_moves = moves + 1
    pad(op.ctx, 'dpad_down' if title.center.y > focused.center.y else 'dpad_up')
    return op.round_wait(f'手柄定位商品：{_text(title.data)}', wait=.6)


def shop_buy(op, screen):
    """A buys the focused row; success once a confirmation, a changed list or fewer coins show."""
    pending = getattr(op, '_pad_shop_buy', None)
    signature = tuple(_text(t.data) for t, _, _ in shop_items(op, screen))
    coins = shop_coins(op, screen)
    if pending is None:
        focus = shop_focus_y(op, screen)
        items = shop_items(op, screen)
        focused = min(items, key=lambda item: abs(item[0].center.y - focus), default=None) if focus is not None else None
        if focused is None or coins is None or focused[2] is None or focused[2] > coins:
            return op.round_retry('商品焦点、价格或余额未核验，未购买', wait=.6)
        pad(op.ctx, 'a')
        op._pad_shop_buy = dict(signature=signature, coins=coins, waits=0)
        return op.round_wait('手柄购买当前商品，等待实际结果', wait=1)
    pending['waits'] += 1
    words = {_text(r.data) for r in ocr_rows(op, screen,Rect(500, 600, 1500, 900))}
    if '确定' in words or signature != pending['signature'] or (
            coins is not None and pending['coins'] is not None and coins < pending['coins']):
        op._pad_shop_buy = None
        return op.round_success('已购买')
    if pending['waits'] >= 6:
        return op.round_fail('购买后画面未变化，不重复购买')
    return op.round_wait('等待购买结果，未重复按键', wait=.6)


def shop_leave(op, screen):
    """B backs out of the list and the shop menu; success once the board's 背包 shows again."""
    words = [_text(r.data) for r in ocr_rows(op, screen,Rect(0, 0, 1920, 1080))]
    in_shop = any(w.startswith('鸣徽交易[') or w.startswith('鸣徽催化[') or '欢迎光临' in w for w in words) \
        or ('鸣徽交易' in words and '鸣徽催化' in words)
    if not in_shop:
        if '背包' in words:
            op._pad_shop_backs = 0
            return op.round_success('已离开商店')
        return op.round_retry('等待离开商店后的棋盘', wait=.6)
    backs = getattr(op, '_pad_shop_backs', 0)
    if backs >= 5:
        return op.round_fail('手柄离开商店未生效')
    op._pad_shop_backs = backs + 1
    pad(op.ctx, 'b')
    return op.round_wait('手柄返回，离开商店', wait=1)
