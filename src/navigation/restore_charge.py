"""Read the real restore-source and quick-use dialogs before controller input."""
import re

import cv2

from onedragon.base.geometry.rectangle import Rect
from src.controls.gamepad import press as pad
from src.navigation.common import norm_text, ocr_rows
from src.navigation.menus import label_focused

SOURCES = ('储蓄电量', '以太电池')
CARDS = SOURCES + ('菲林',)
NO_SOURCE = '没有可用的电量来源'


def quick_use(op):
    screen = op.last_screenshot
    titles = ocr_rows(op, screen, Rect(570, 290, 780, 365))
    if not any(norm_text(row.data) == '快捷使用' for row in titles):
        return None
    title_rows = ocr_rows(op, screen, Rect(775, 420, 1190, 480))
    title = ''.join(norm_text(row.data) for row in sorted(title_rows, key=lambda row: row.center.x))
    match = re.fullmatch(r'(储蓄电量|以太电池)[xX×*](\d+)', title)
    if match is None:
        return None
    numbers = ocr_rows(op, screen, Rect(940, 595, 1090, 650))
    value = ''.join(norm_text(row.data) for row in sorted(numbers, key=lambda row: row.center.x))
    if not re.fullmatch(r'\d+', value):
        return None
    return match.group(1), int(match.group(2)), int(value)


def source_page(op):
    """The restore dialog's cards, counts, card focus and button focus; None when it is not showing.

    The dialog lists 储蓄电量, 以太电池 and 菲林. A source the account has none of may be shown
    with 0 or not shown at all (以太电池 at 0 since 2026-10-25), so neither the number of cards
    nor their positions are assumed: the title and at least one readable card are enough.
    """
    screen = op.last_screenshot
    rows = ocr_rows(op, screen, Rect(650, 335, 1270, 810))
    if not any(norm_text(row.data) == '恢复电量' for row in rows):
        return None
    cards = {}
    for row in rows:
        name = norm_text(row.data)
        if name in CARDS and 590 < row.center.y < 650 and name not in cards:
            cards[name] = row
    if not cards:
        return None
    counts = {}
    for name, card in cards.items():
        numbers = [row for row in rows if 560 < row.center.y < 605 and abs(row.center.x - card.center.x) < 45
                   and re.fullmatch(r'\d+', norm_text(row.data))]
        if len(numbers) == 1:
            counts[name] = int(norm_text(numbers[0].data))
    # Card focus is a 132px yellow rounded outline. The smaller item's colored
    # artwork is not sufficient evidence of selection.
    mask = ((screen[:, :, 0] > 75) & (screen[:, :, 1] > 75)
            & (screen[:, :, 2] < 100)
            & (screen[:, :, 1].astype('int16') - screen[:, :, 2] > 35))
    contours, _ = cv2.findContours(mask[430:590, 650:1270].astype('uint8'),
                                   cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = [cv2.boundingRect(contour) for contour in contours]
    focused = [name for name, row in cards.items() if any(
        115 < w < 150 and 115 < h < 150 and abs(x + 650 + w / 2 - row.center.x) < 35
        for x, y, w, h in boxes)]
    selected = focused[0] if len(focused) == 1 else None
    confirm = next((row for row in rows if norm_text(row.data) == '确认'
                    and 1000 < row.center.x < 1240 and 730 < row.center.y < 810), None)
    cancel = next((row for row in rows if norm_text(row.data) == '取消'
                   and 700 < row.center.x < 940 and 730 < row.center.y < 810), None)
    button = ('confirm' if confirm is not None and label_focused(screen, confirm.center, 110)
              else 'cancel' if cancel is not None and label_focused(screen, cancel.center, 110) else None)
    return dict(cards=cards, counts=counts, selected=selected, button=button)


def usable_sources(state, targets):
    """Configured sources, in order, that the dialog shows and that are not read as 0."""
    return [name for name in targets if name in SOURCES and name in state['cards']
            and state['counts'].get(name) != 0]


def choose_source(op, targets):
    """Focus the first usable configured source; never 菲林. Success status is the chosen source."""
    state = source_page(op)
    if state is None:
        return op.round_retry('未核验恢复电量来源页，未操作', wait=.5)
    usable = usable_sources(state, targets)
    if not usable:
        shown = '、'.join(f'{name} {state["counts"].get(name, "?")}' for name in SOURCES if name in state['cards'])
        return op.round_success(NO_SOURCE, data=shown or '无')
    target = usable[0]
    op._restore_source = target
    if state['button'] is not None:
        pad(op.ctx, 'dpad_up')
        return op.round_wait('返回电量来源卡片，等待焦点', wait=.5)
    selected = state['selected']
    if selected is None:
        return op.round_retry('未核验电量来源卡片焦点，未操作', wait=.5)
    if selected != target:
        left = state['cards'][target].center.x < state['cards'][selected].center.x
        pad(op.ctx, 'dpad_left' if left else 'dpad_right')
        return op.round_wait(f'选择电量来源：{selected} → {target}', wait=.5)
    return op.round_success(target)


def confirm_source(op, target):
    quick = quick_use(op)
    if quick is not None:
        if quick[0] != target:
            return op.round_fail('快捷使用来源与配置不一致，未消耗')
        return op.round_success(target)
    state = source_page(op)
    if state is None:
        return op.round_retry('等待实际快捷使用页，未重复确认', wait=.5)
    if state['selected'] != target:
        return op.round_fail('电量来源未通过核验，未确认')
    if state['button'] == 'confirm':
        pad(op.ctx, 'a')
    elif state['button'] == 'cancel':
        pad(op.ctx, 'dpad_right')
    else:
        pad(op.ctx, 'dpad_down')
    return op.round_wait('定位并确认电量来源，等待快捷使用页', wait=.5)
