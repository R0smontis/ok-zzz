"""HDD controller entry and chapter selection, verified on current game frames."""
import re

import numpy as np

from onedragon.base.geometry.rectangle import Rect
from src.controls.gamepad import press as pad
from src.navigation.common import bump, norm_text, ocr_rows
from src.navigation.menus import focus_mask

CHAPTERS = ('序章', '第一章', '第二章', '第二章间章', '第三章', '第四章', '第五章',
            '第一季尾音上', '第一季尾音下')


def _text(value):
    return norm_text(value, 'hdd')


def _chapter(value):
    return re.fullmatch(r'第[一二三四五六七八九十]+章(?:间章)?|第[一二三四五六七八九十]+季.+|序章', value) is not None


def hdd_state(op, screen):
    if not isinstance(screen, np.ndarray) or screen.shape[:2] != (1080, 1920):
        return None
    rows = ocr_rows(op, screen)
    words = {_text(r.data) for r in rows}
    if {'战斗设置', '预备编队', '出战'} <= words:
        return dict(page='deployment', rows=rows)
    if any(_text(r.data) == '下一步' and r.center.y > 980 for r in rows) and any(
            950 < r.center.x < 1600 and 180 < r.center.y < 900 and '【' in _text(r.data).replace('[', '【')
            for r in rows):
        return dict(page='missions', rows=rows)
    # The controller hub no longer contains the old 「街区」 label.
    header = [r for r in rows if 1490 < r.center.x < 1840 and r.center.y < 85
              and any('一' <= c <= '鿿' for c in _text(r.data))]
    title = ''.join(_text(r.data) for r in sorted(header, key=lambda r: r.center.x))
    if not header or not any('委托' in _text(r.data) and 300 < r.center.y < 800 for r in rows):
        return None
    choices = [r for r in rows if 1490 < r.center.x < 1840 and 100 < r.center.y < 500 and _chapter(_text(r.data))]
    return dict(page='chapters' if len(choices) >= 2 else 'hub', rows=rows, title=title, choices=choices)


def enter_hdd(op, screen):
    """SUCCESS on a verified HDD page, else None so world interaction can be checked."""
    state = hdd_state(op, screen)
    return op.round_success('已核验HDD界面') if state is not None else None


def choose_chapter(op, screen):
    count = getattr(op, '_hdd_chapter_rounds', 0)
    if count >= 24:
        return op.round_fail(f'手柄选择HDD章节未生效：{op.chapter}')
    op._hdd_chapter_rounds = count + 1
    state = hdd_state(op, screen)
    if state is None:
        return op.round_retry('未核验HDD章节页面，未操作', wait=.8)
    if state['page'] in ('missions', 'deployment'):
        count = getattr(op, '_hdd_backs', 0)
        if count >= 3:
            return op.round_fail('手柄返回HDD章节页面未生效')
        op._hdd_backs = count + 1
        pad(op.ctx, 'b')
        return op.round_wait('从原委托页面返回章节选择，未出战', wait=1.2)
    target = _text(op.chapter)
    if state['page'] == 'hub':
        if state['title'] == target:
            return op.round_success(f'已核验HDD章节：{op.chapter}')
        opens = getattr(op, '_hdd_chapter_opens', 0)
        if opens >= 3:
            return op.round_fail('手柄打开HDD章节列表未生效')
        op._hdd_chapter_opens = opens + 1
        pad(op.ctx, 'l_thumb')
        return op.round_wait('手柄打开HDD章节列表', wait=1)
    mask = focus_mask(screen)
    focused = [r for r in state['choices'] if np.mean(mask[r.center.y-14:r.center.y+14, 1500:1830]) > .45]
    if len(focused) != 1:
        return op.round_retry('HDD章节焦点未唯一核验，未操作', wait=.6)
    here = focused[0]
    wanted = next((r for r in state['choices'] if _text(r.data) == target), None)
    if wanted is here:
        # A chooses only the chapter. A dialog or transition is not success.
        pad(op.ctx, 'a')
        return op.round_wait(f'手柄选择HDD章节 {op.chapter}，等待实际章节画面', wait=2)
    if wanted is not None:
        up = wanted.center.y < here.center.y
    else:
        name = _text(here.data)
        if name not in CHAPTERS or target not in CHAPTERS:
            return op.round_fail(f'未识别HDD章节顺序：{name} → {target}')
        up = CHAPTERS.index(target) < CHAPTERS.index(name)
    pad(op.ctx, 'dpad_up' if up else 'dpad_down')
    return op.round_wait(f'手柄查找HDD章节：{here.data} → {op.chapter}', wait=.6)


COMMISSIONS = ('剧情委托', '探索委托', '战斗委托')


def _card_focused(screen, label):
    """The hub marks the focused commission with a pulsing chevron ~130 px above its label."""
    # The window stops above the STORY logo, whose yellow would otherwise read as focus.
    part = screen[max(0, label.center.y - 165):label.center.y - 120, max(0, label.center.x - 30):label.center.x + 30]
    return bool(part.size) and int(focus_mask(part).sum()) > 150


def choose_mission_type(op, screen):
    """Hub → the commission card named op.mission_type (LB/RB would change the chapter)."""
    state = hdd_state(op, screen)
    if state is None:
        if bump(op,'_hdd_type_waits', 6):
            return op.round_fail('未核验HDD委托画面')
        return op.round_wait('等待HDD委托画面', wait=.8)
    if state['page'] == 'missions':
        return op.round_success('下一步')
    if state['page'] != 'hub':
        return op.round_retry('未核验HDD章节画面，未操作', wait=.8)
    cards = [r for r in state['rows'] if _text(r.data) in COMMISSIONS and 150 < r.center.y < 900]
    target = next((r for r in cards if _text(r.data) == op.mission_type), None)
    if target is None:
        if any('未解锁' in _text(r.data) for r in state['rows']):
            # Live 2026-10-13: 第二章间章 shows only 剧情/探索 and a LOCKED card on this account.
            return op.round_fail(f'{op.chapter} 的 {op.mission_type} 未解锁')
        return op.round_retry(f'未找到委托 {op.mission_type}，未操作', wait=.8)
    focused = [r for r in cards if _card_focused(screen, r)]
    if len(focused) != 1:
        return op.round_retry('委托焦点未唯一核验，未操作', wait=.6)
    if focused[0] is target:
        if bump(op,'_hdd_type_opens', 3):
            return op.round_fail(f'手柄打开{op.mission_type}未生效')
        pad(op.ctx, 'a')
        return op.round_wait(f'手柄打开{op.mission_type}', wait=1.5)
    if bump(op,'_hdd_type_moves', 8):
        return op.round_fail(f'手柄选择{op.mission_type}未生效')
    pad(op.ctx, 'dpad_left' if target.center.x < focused[0].center.x else 'dpad_right')
    return op.round_wait(f'手柄选择委托：{_text(focused[0].data)} → {op.mission_type}', wait=.6)


def _mission_key(value):
    return re.sub(r'[\[\]【】\s·:：]', '', value)


def mission_rows(screen, rows):
    """(name, centre, selected) for each commission row; the selected row has a red fill."""
    lines = []
    for r in sorted((r for r in rows if 950 < r.center.x < 1600 and 180 < r.center.y < 880), key=lambda r: r.center.y):
        if lines and abs(lines[-1][1] - r.center.y) < 30:
            lines[-1][0].append(r)
        else:
            lines.append(([r], r.center.y))
    result = []
    for parts, y in lines:
        name = _mission_key(''.join(_text(p.data) for p in sorted(parts, key=lambda p: p.center.x)))
        band = screen[max(0, int(y) - 18):int(y) + 18, 1180:1500].astype(int)
        red = (band[:, :, 0] > 170) & (band[:, :, 1] < 120) & (band[:, :, 2] < 100)
        if any('一' <= c <= '鿿' for c in name):
            result.append((name, parts[0].center, float(np.mean(red)) > .3))
    return result


def choose_mission(op, screen):
    """Mission list: move the red selection to op.mission_name; the list scrolls with the focus."""
    state = hdd_state(op, screen)
    if state is None or state['page'] != 'missions':
        if bump(op,'_hdd_list_waits', 6):
            return op.round_fail('未核验HDD副本列表')
        return op.round_wait('等待HDD副本列表', wait=.8)
    lines = mission_rows(screen, state['rows'])
    selected = [line for line in lines if line[2]]
    wanted = _mission_key(op.mission_name)
    target = next((line for line in lines if wanted in line[0]), None)
    if len(selected) != 1:
        return op.round_retry('副本选择未唯一核验，未操作', wait=.6)
    if target is not None and target is selected[0]:
        return op.round_success(f'已选中副本 {op.mission_name}')
    if bump(op,'_hdd_list_moves', 16):
        return op.round_fail(f'HDD副本列表中未找到 {op.mission_name}')
    down = target is None or target[1].y > selected[0][1].y
    pad(op.ctx, 'dpad_down' if down else 'dpad_up')
    return op.round_wait(f'手柄选择副本：{selected[0][0]} → {wanted}', wait=.6)


def press_next(op, screen):
    """下一步 sits on the menu button (≡); success once the deployment page shows."""
    state = hdd_state(op, screen)
    if state is not None and state['page'] == 'deployment':
        return op.round_success('出战画面')
    if state is None or state['page'] != 'missions':
        if bump(op,'_hdd_next_waits', 6):
            return op.round_fail('下一步后未出现出战画面')
        return op.round_wait('等待出战画面', wait=.8)
    if bump(op,'_hdd_next_presses', 3):
        return op.round_fail('手柄下一步未生效')
    pad(op.ctx, 'start')
    return op.round_wait('手柄下一步，等待出战画面', wait=1.5)
