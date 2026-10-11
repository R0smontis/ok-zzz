"""HDD controller entry and chapter selection, verified on current game frames."""
import re

import numpy as np

from onedragon.base.geometry.rectangle import Rect
from src.controls.gamepad import press as pad
from src.navigation.menus import focus_mask

CHAPTERS = ('序章', '第一章', '第二章', '第二章间章', '第三章', '第四章', '第五章',
            '第一季尾音上', '第一季尾音下')


def _text(value):
    return str(value).replace(' ', '').replace('·', '')


def _chapter(value):
    return re.fullmatch(r'第[一二三四五六七八九十]+章(?:间章)?|第[一二三四五六七八九十]+季.+|序章', value) is not None


def _rows(op, screen):
    rows = op.ctx.ocr_service.get_ocr_result_list(image=screen, rect=Rect(0, 0, 1920, 1080))
    return rows if isinstance(rows, (list, tuple)) else []


def hdd_state(op, screen):
    if not isinstance(screen, np.ndarray) or screen.shape[:2] != (1080, 1920):
        return None
    rows = _rows(op, screen)
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
