"""Verified controller flows for 随便观; its pages ignore window-message clicks.

Every press follows a page and focus read on the current frame. Counters bound each
flow, so an unexpected page ends it instead of pressing on.
"""
import re
from difflib import SequenceMatcher

import numpy as np

from onedragon.base.geometry.rectangle import Rect
from onedragon.base.operation.operation_node import operation_node
from onedragon.base.operation.operation_round_result import OperationRoundResult
from onedragon.utils.log_utils import log
from src.controls.gamepad import press as pad
from src.navigation.common import bump, in_rect, lit, norm_text, ocr_rows, slice_bounds
from src.navigation.menus import focus_mask
from zzz_od.operation.zzz_operation import ZOperation

DURATIONS = ('3分钟', '15分钟', '1小时', '2小时', '6小时', '12小时', '20小时')
LOCATIONS = tuple(f'{area}{i}' for area in ('制造区', '社区旧址', '科研院旧址') for i in (1, 2, 3))


class SuibianPadFlow(ZOperation):
    """One looping node that runs `step(op, screen)` until it succeeds or fails."""

    def __init__(self, ctx, name, step, **state):
        ZOperation.__init__(self, ctx, op_name=name)
        self._step = step
        self.__dict__.update(state)

    @operation_node(name='手柄流程', is_start_node=True, node_max_retry_times=12, timeout_seconds=300)
    def run_step(self) -> OperationRoundResult:
        return self._step(self, self.last_screenshot)


def _text(value):
    return norm_text(value)


def _find(rows, word, rect=None):
    return next((r for r in rows if word in _text(r.data)
                 and (rect is None or in_rect(r.center, rect))), None)


_slice = slice_bounds  # 兼容旧名（测试直接导入）


def _guide(op, rows):
    """First-visit tutorials block every page with 「A 下一步」; advance them, logging what they say.

    The user asked for unexpected windows to be closed and the task continued. A guide can
    walk through a real action (the 开物 guide researches its first good), so this is bounded.
    """
    step = _find(rows, '下一步', Rect(1560, 70, 1860, 140))
    if step is None:
        return None
    if bump(op,'_guide_steps', 20):
        return op.round_fail('新手引导步骤过多，请在游戏中手动完成')
    text = next((_text(r.data) for r in rows if r.center.y < 75 and r.center.x > 900), '')
    log.info('随便观新手引导：%s', text)
    pad(op.ctx, 'a')
    return op.round_wait(f'手柄推进新手引导：{text}', wait=1.2)


def is_entry(rows):
    return _find(rows, '邻里街坊') is not None and (_find(rows, '派驻邦布') or _find(rows, '经营方针')) is not None


def entry_tile_focused(screen, label):
    """经营 / 游历 tiles light both side edges ±108 px around their label when focused."""
    mask = focus_mask(screen)
    x, y = label.center.x, label.center.y
    y0, y1 = slice_bounds(mask.shape[0], y-90, y+10)

    def edge(dx):
        values = []
        for d in (dx-4, dx, dx+4):
            x0, x1 = slice_bounds(mask.shape[1], x+d-4, x+d+4)
            part = mask[y0:y1, x0:x1]
            values.append(float(np.mean(part)) if part.size else 0.0)
        return max(values)
    return edge(-108) > .25 and edge(108) > .25


def open_entry_tile(op, screen, rows, name):
    """Move the entry focus onto 经营/游历 and press A; None while not on the entry page."""
    tiles = {_text(r.data): r for r in rows if 1240 < r.center.x < 1700 and 560 < r.center.y < 615
             and _text(r.data) in ('经营', '游历')}
    if len(tiles) != 2:
        return None
    focused = [name_ for name_, r in tiles.items() if entry_tile_focused(screen, r)]
    if bump(op,'_entry_presses', 4):
        return op.round_fail(f'手柄打开{name}未生效')
    if focused == [name]:
        pad(op.ctx, 'a')
        return op.round_wait(f'手柄打开{name}，等待实际画面', wait=1.5)
    if len(focused) != 1:
        # Keyboard prompts show no outline; a d-pad press reveals the focus.
        pad(op.ctx, 'dpad_down')
        return op.round_wait('手柄显示随便观焦点', wait=.8)
    pad(op.ctx, 'dpad_right' if tiles[name].center.x > tiles[focused[0]].center.x else 'dpad_left')
    return op.round_wait(f'手柄选择{name}', wait=.8)


def arrival_step(op, screen):
    """After the teleport: close the daily 经营日志 popup until the entry page is verified."""
    rows = ocr_rows(op, screen)
    guide = _guide(op, rows)
    if guide is not None:
        return guide
    if is_entry(rows):
        return op.round_success('随便观-入口')
    if bump(op,'_arrival_rounds', 12):
        return op.round_fail('未核验随便观入口画面')
    if _find(rows, '经营日志') and _find(rows, '7天内不再自动弹出'):
        pad(op.ctx, 'b')
        return op.round_wait('手柄关闭经营日志弹窗', wait=1.2)
    return op.round_wait('等待随便观入口画面', wait=1)


def auto_manage_step(op, screen):
    """Read the 自动托管 tab state from 经营方针; the manual flow follows unless hosting can run.

    Only a locked tab (随便观 Lv.35) is verified; hosting control itself is left to the game.
    """
    rows = ocr_rows(op, screen)
    guide = _guide(op, rows)
    if guide is not None:
        return guide
    if bump(op,'_manage_rounds', 12):
        return op.round_fail('经营方针画面未核验')
    log_tab = _find(rows, '经营日志', Rect(1150, 90, 1750, 190))
    if log_tab is not None:
        op._manage_locked = _find(rows, 'LOCKED', Rect(1350, 90, 1750, 190)) is not None
        pad(op.ctx, 'b')
        return op.round_wait('已读取自动托管状态，关闭经营方针', wait=1.2)
    if is_entry(rows):
        locked = getattr(op, '_manage_locked', None)
        if locked is not None:
            log.info('随便观：%s，执行手动经营流程', '自动托管未解锁（随便观 Lv.35）' if locked else '后台手柄暂不操作自动托管')
            return op.round_success('未开启自动托管')
        if bump(op,'_manage_opens', 3):
            return op.round_fail('手柄打开经营方针未生效')
        pad(op.ctx, 'x')
        return op.round_wait('手柄打开经营方针', wait=1.5)
    if _find(rows, '未满足解锁条件'):
        pad(op.ctx, 'a')
        return op.round_wait('关闭未解锁提示', wait=1)
    return op.round_wait('等待经营方针画面', wait=.8)


def _squads(rows):
    """('游历小队：n/m') -> (n, m): squads out, squads owned."""
    for r in rows:
        match = re.search(r'游历小队[:：]?(\d)/(\d)', _text(r.data))
        if match and r.center.y < 80:
            return int(match.group(1)), int(match.group(2))
    return None


def _location_name(text):
    """OCR reads the stylised labels loosely (製造区1, 科研院旧址 without its digit)."""
    text = text.replace('製', '制')
    best = max(LOCATIONS, key=lambda name: SequenceMatcher(None, text, name).ratio())
    # Keep the read text as identity: a label missing its digit must not merge with another.
    return best if text == best else text if SequenceMatcher(None, text, best).ratio() >= .75 else None


def adventure_locations(screen, rows):
    """Location labels on the 游历 map: (name, center, unlocked, focused)."""
    mask = focus_mask(screen)
    pills = [r for r in rows if re.search(r'K.?D', _text(r.data).upper())]
    result = []
    for r in rows:
        name = _location_name(_text(r.data))
        if name is None:
            continue
        x, y = r.center.x, r.center.y
        locked = any(abs(p.center.x - x) < 120 and 40 < y - p.center.y < 130 for p in pills)
        # The focused location carries chevrons on both sides of its pill.
        top, bottom = slice_bounds(mask.shape[0], y-120, y-40)
        left0, left1 = slice_bounds(mask.shape[1], x-210, x-140)
        right0, right1 = slice_bounds(mask.shape[1], x+140, x+210)
        focused = (mask[top:bottom, left0:left1].sum() > 300
                   and mask[top:bottom, right0:right1].sum() > 300)
        result.append((name, r.center, not locked, bool(focused)))
    return result


def _panel_button(rows):
    for word in ('可收获', '提前收获', '派遣'):
        row = _find(rows, word, Rect(1380, 860, 1700, 950))
        if row is not None and (word != '派遣' or _text(row.data) == '派遣'):
            return word
    return None


def duration_tiles(screen, rows):
    """Duration tiles in 游历时间选择: (label, center, unlocked, focused)."""
    mask = focus_mask(screen)
    tiles = []
    for r in rows:
        name = _text(r.data)
        if name not in DURATIONS or not (480 < r.center.y < 760):
            continue
        x, y = r.center.x, r.center.y
        y0, y1 = slice_bounds(screen.shape[0], y-12, y+12)
        x0, x1 = slice_bounds(screen.shape[1], x-30, x+30)
        text = screen[y0:y1, x0:x1].max(axis=2)
        unlocked = bool(text.size) and float(np.percentile(text, 95)) > 180  # locked labels are grey
        focused = lit(mask, x-140, x-128, y-50, y+50, .3) and lit(mask, x+128, x+140, y-50, y+50, .3)
        tiles.append((name, r.center, unlocked, focused))
    return tiles


def _choose_duration(op, screen, rows):
    tiles = duration_tiles(screen, rows)
    unlocked = [t for t in tiles if t[2]]
    focused = [t for t in tiles if t[3]]
    if not unlocked or len(focused) != 1:
        return op.round_retry('游历时间选项或焦点未核验，未操作', wait=.6)
    wanted = op.duration if op.duration in DURATIONS else DURATIONS[-1]
    fitting = [t for t in unlocked if DURATIONS.index(t[0]) <= DURATIONS.index(wanted)]
    # The configured time, else the longest unlocked one within it, else the shortest.
    target = max(fitting, key=lambda t: DURATIONS.index(t[0])) if fitting else min(
        unlocked, key=lambda t: DURATIONS.index(t[0]))
    current = focused[0]
    if current[0] == target[0]:
        pad(op.ctx, 'a')
        op._duration_chosen = target[0]
        return op.round_wait(f'手柄确认游历时间 {target[0]}', wait=1.2)
    dx, dy = target[1].x - current[1].x, target[1].y - current[1].y
    pad(op.ctx, ('dpad_down' if dy > 0 else 'dpad_up') if abs(dy) > 60 else ('dpad_right' if dx > 0 else 'dpad_left'))
    return op.round_wait(f'手柄选择游历时间：{current[0]} → {target[0]}', wait=.6)


def adventure_step(op, screen):
    """游历: claim returned squads and dispatch free squads on every unlocked location.

    State on `op`: claim, dispatch, duration (config text); _done (finished locations),
    _current (location whose panel is open), _results (what happened, for the log).
    """
    rows = ocr_rows(op, screen)
    guide = _guide(op, rows)
    if guide is not None:
        return guide
    if bump(op,'_adventure_rounds', 90):
        return op.round_fail('游历处理轮数过多，已停止')
    op.__dict__.setdefault('_done', set())
    op.__dict__.setdefault('_results', [])
    if _find(rows, '游历完成') and _find(rows, '确认'):
        pad(op.ctx, 'a')
        op._results.append(f'{getattr(op, "_current", "")}收获')
        return op.round_wait('手柄确认游历收获', wait=1.2)
    if _find(rows, '游历时间选择'):
        return _choose_duration(op, screen, rows)
    if _find(rows, '未满足解锁条件'):
        pad(op.ctx, 'a')
        return op.round_wait('关闭未解锁提示', wait=1)
    squads = _squads(rows)
    if squads is not None:
        return _adventure_map(op, screen, rows, squads)
    if is_entry(rows):
        if getattr(op, '_left_map', False):
            return op.round_success('；'.join(op._results) or '没有可收获或可派遣的游历')
        result = open_entry_tile(op, screen, rows, '游历')
        return result if result is not None else op.round_retry('未核验随便观入口按钮', wait=.8)
    return op.round_wait('等待游历画面', wait=.8)


def _adventure_map(op, screen, rows, squads):
    out, owned = squads
    button = _panel_button(rows) if _find(rows, '探索进程') else None
    current = getattr(op, '_current', None)
    reading = (button, out, owned)
    if button is not None and getattr(op, '_panel_reading', None) != reading:
        # The panel slides in and refreshes its button: act on a reading two frames agree on.
        op._panel_reading = reading
        return op.round_wait('等待游历详情稳定', wait=.5)
    op._panel_reading = None
    if button is not None and current is not None:
        if button == '可收获' and op.claim:
            if bump(op,'_claims', 6):
                return op.round_fail('游历收获未生效')
            pad(op.ctx, 'start')
            return op.round_wait(f'手柄收获 {current}', wait=1.5)
        if button == '派遣' and op.dispatch and out < owned and current not in getattr(op, '_dispatched', set()):
            if getattr(op, '_duration_chosen', None) is None:
                pad(op.ctx, 'a')  # opens 游历时间选择
                return op.round_wait('手柄打开游历时间选择', wait=1.2)
            if not getattr(op, '_auto_chosen', False):
                op._auto_chosen = True
                pad(op.ctx, 'y')  # 自动选择邦布
                return op.round_wait('手柄自动选择邦布', wait=1)
            op.__dict__.setdefault('_dispatched', set()).add(current)
            pad(op.ctx, 'start')
            return op.round_wait(f'手柄派遣 {current}（{op._duration_chosen}）', wait=1.5)
        if current in getattr(op, '_dispatched', set()):
            op._results.append(f'{current}派遣' if button == '提前收获' else f'{current}派遣未生效')
        # 提前收获 is never pressed: it ends a running trip early.
        op._done.add(current)
        op._current, op._duration_chosen, op._auto_chosen = None, None, False
        pad(op.ctx, 'b')
        return op.round_wait(f'{current} 已处理，关闭详情', wait=1)
    if button is not None:
        pad(op.ctx, 'b')  # a panel opened by someone else: start from the map
        return op.round_wait('关闭未经核验的游历详情', wait=1)
    locations = adventure_locations(screen, rows)
    pending = [loc for loc in locations if loc[2] and loc[0] not in op._done]
    if not pending:
        if not locations:
            return op.round_retry('未识别游历地点', wait=.8)
        if not getattr(op, '_nothing_seen', False):
            # The map fades in over the entry page: decide on a second, settled frame.
            op._nothing_seen = True
            names = '、'.join(loc[0] + ('' if loc[2] else '(未解锁)') for loc in locations)
            return op.round_wait(f'再次核验没有待处理的游历地点：{names}', wait=1)
        op._left_map = True
        if bump(op,'_map_backs', 4):
            return op.round_fail('手柄返回随便观未生效')
        pad(op.ctx, 'b')
        return op.round_wait('游历处理完成，返回随便观', wait=1.2)
    op._nothing_seen = False
    focused = [loc for loc in locations if loc[3]]
    if not focused and not getattr(op, '_focus_revealed', False):
        # Closing a detail hides the map focus until the next d-pad press.
        op._focus_revealed = True
        pad(op.ctx, 'dpad_up')
        return op.round_wait('手柄显示游历地点焦点', wait=.8)
    if len(focused) != 1:
        return op.round_retry('游历地点焦点未核验，未操作', wait=.6)
    op._focus_revealed = False
    target, here = pending[0], focused[0]
    if bump(op,'_map_moves', 30):
        return op.round_fail(f'手柄选择游历地点 {target[0]} 未生效')
    if here[0] == target[0]:
        op._current = target[0]
        pad(op.ctx, 'a')
        return op.round_wait(f'手柄打开游历地点 {target[0]}', wait=1.2)
    dx, dy = target[1].x - here[1].x, target[1].y - here[1].y
    pad(op.ctx, ('dpad_down' if dy > 0 else 'dpad_up') if abs(dy) > abs(dx) else ('dpad_right' if dx > 0 else 'dpad_left'))
    return op.round_wait(f'手柄选择游历地点：{here[0]} → {target[0]}', wait=.8)


def neighbourhood_focused(screen, label):
    """邻里街坊 tiles: a bright yellow outline ±162 px around the label; the panel itself is orange."""
    x, y = label.center.x, label.center.y
    top, bottom = slice_bounds(screen.shape[0], y-300, y-20)
    part = screen[top:bottom]
    yellow = (part[:, :, 0] > 200) & (part[:, :, 1] > 190) & (part[:, :, 2] < 90)

    def edge(dx):
        x0, x1 = slice_bounds(screen.shape[1], x+dx-5, x+dx+5)
        column = yellow[:, x0:x1]
        return bool(column.size) and float(np.mean(column)) > .25
    return edge(-162) and edge(162)


def yum_cha_step(op, screen):
    """饮茶仙: only 定期采办 is automated upstream; 邻里心愿 orders spend collectibles and are left alone.

    The 定期采办 tab could not be verified on a controller on the test account,
    so the step reports it instead of pressing anything there.
    """
    rows = ocr_rows(op, screen)
    guide = _guide(op, rows)
    if guide is not None:
        return guide
    if bump(op,'_yum_rounds', 30):
        return op.round_fail('饮茶仙处理轮数过多，已停止')
    tiles = [r for r in rows if 640 < r.center.y < 720 and _text(r.data) in ('饮茶仙', '好物铺', '德丰大押', '邦巢')]
    if _find(rows, '邻里心愿', Rect(1450, 80, 1900, 180)) or _find(rows, '定期采办', Rect(1250, 80, 1900, 180)):
        if getattr(op, '_yum_result', None) is None:
            op._yum_result = ('后台手柄暂不处理定期采办' if _find(rows, '定期采办', Rect(1250, 80, 1900, 180))
                              else '定期采办入口未核验')
        if bump(op,'_yum_backs', 4):
            return op.round_fail('手柄离开饮茶仙未生效')
        pad(op.ctx, 'b')
        return op.round_wait(f'饮茶仙：{op._yum_result}，返回', wait=1.2)
    if len(tiles) >= 2:
        if getattr(op, '_yum_result', None) is not None:
            pad(op.ctx, 'b')
            return op.round_wait('关闭邻里街坊', wait=1)
        wanted = next((r for r in tiles if _text(r.data) == '饮茶仙'), None)
        focused = [r for r in tiles if neighbourhood_focused(screen, r)]
        if wanted is None or len(focused) != 1:
            return op.round_retry('邻里街坊焦点未核验，未操作', wait=.6)
        if bump(op,'_yum_moves', 6):
            return op.round_fail('手柄选择饮茶仙未生效')
        if focused[0] is wanted:
            pad(op.ctx, 'a')
            return op.round_wait('手柄打开饮茶仙', wait=1.5)
        pad(op.ctx, 'dpad_left' if wanted.center.x < focused[0].center.x else 'dpad_right')
        return op.round_wait('手柄选择饮茶仙', wait=.6)
    if is_entry(rows):
        if getattr(op, '_yum_result', None) is not None:
            return op.round_success(op._yum_result)
        if bump(op,'_yum_opens', 3):
            return op.round_fail('手柄打开邻里街坊未生效')
        pad(op.ctx, 'start')
        return op.round_wait('手柄打开邻里街坊', wait=1.5)
    return op.round_wait('等待饮茶仙画面', wait=.8)


_PAGES = {'制造': '制造坊', '售卖': '售卖铺', '开物': '开物'}


def manage_page(rows):
    """On a 经营 sub-page: (page, left neighbour, right neighbour) read from the scene labels."""
    title = next((_text(r.data).replace('製', '制') for r in rows
                  if 1380 < r.center.x < 1600 and 480 < r.center.y < 530 and len(_text(r.data)) >= 2), None)
    side = lambda inside: next((name for name in (_text(r.data).replace('製', '制') for r in rows
                                                  if inside(r.center.x) and 490 < r.center.y < 545)
                                if name in _PAGES), None)  # NEW! badges sit beside the labels
    left, right = side(lambda x: x < 260), side(lambda x: x > 1650)
    if title is None or left is None or right is None:
        return None
    return title, left, right


def card_focused(screen, label):
    """经营 cards: the focused card's side edges turn bright yellow; the page itself is orange."""
    x = label.center.x
    part = screen[300:800]
    yellow = (part[:, :, 0] > 200) & (part[:, :, 1] > 190) & (part[:, :, 2] < 90)
    column = yellow.mean(axis=0)
    edge = lambda x0, x1: float(column[max(0, x0):x1].max(initial=0))
    return edge(x - 240, x - 195) > .5 and edge(x + 195, x + 240) > .5


def goto_manage_page(op, screen, rows, target):
    """From the entry or any 经营 page to the target sub-page (制造坊 / 售卖铺); None once there."""
    page = manage_page(rows)
    if page is not None:
        if page[0] == target:
            return None
        if bump(op,'_page_switches', 4):
            return op.round_fail(f'手柄切换到{target}未生效')
        pad(op.ctx, 'lb' if _PAGES[page[1]] == target else 'rb')
        return op.round_wait(f'手柄切换经营页面：{page[0]} → {target}', wait=1.2)
    cards = [r for r in rows if 680 < r.center.y < 730 and _text(r.data) in ('开物清单', '制造台', '货架')]
    if len(cards) == 3:
        wanted = next((r for r in cards
                       if _text(r.data) == {'制造坊': '制造台', '售卖铺': '货架'}[target]), None)
        if wanted is None:
            # OCR merged one card with its neighbour and dropped another: decide on a new frame.
            return op.round_retry(f'未识别{target}卡片，未操作', wait=.6)
        focused = [r for r in cards if card_focused(screen, r)]
        if bump(op,'_card_moves', 5):
            return op.round_fail(f'手柄选择{target}未生效')
        if focused and focused[0] is not wanted:
            pad(op.ctx, 'dpad_right' if wanted.center.x > focused[0].center.x else 'dpad_left')
            return op.round_wait(f'手柄选择{target}', wait=.6)
        if not focused and not getattr(op, '_card_waited', False):
            op._card_waited = True  # the cards slide in; read a settled frame first
            return op.round_wait('等待经营卡片焦点', wait=.6)
        # Unverified focus still lands on a 经营 page, which LB/RB then corrects.
        pad(op.ctx, 'a')
        return op.round_wait('手柄进入经营页面', wait=1.5)
    if is_entry(rows):
        result = open_entry_tile(op, screen, rows, '经营')
        return result if result is not None else op.round_retry('未核验随便观入口按钮', wait=.8)
    return op.round_wait('等待经营画面', wait=.8)


def back_to_entry(op, rows, result):
    """B until the entry page shows, then succeed with the given result."""
    if is_entry(rows):
        return op.round_success(result)
    if bump(op,'_entry_backs', 5):
        return op.round_fail('手柄返回随便观入口未生效')
    pad(op.ctx, 'b')
    return op.round_wait('手柄返回随便观入口', wait=1.2)


def slot_focused(screen, label):
    """制造台 / 货架 slots: outline on both edges, 160 px either side of the slot centre."""
    mask = focus_mask(screen)
    x = label.center.x
    return lit(mask, x-166, x-154, 700, 1020, .3) and lit(mask, x+154, x+166, 700, 1020, .3)


def craft_step(op, screen):
    """制造坊: collect finished goods (Y 一键收获), then start the first craftable good on idle 开工 slots."""
    rows = ocr_rows(op, screen)
    guide = _guide(op, rows)
    if guide is not None:
        return guide
    if bump(op,'_craft_rounds', 60):
        return op.round_fail('制造处理轮数过多，已停止')
    op.__dict__.setdefault('_craft_results', [])
    if getattr(op, '_craft_done', False):
        return back_to_entry(op, rows, '；'.join(op._craft_results) or '没有可收获或可开工的制造台')
    if _find(rows, '获得', Rect(700, 360, 1220, 460)) and _find(rows, '确认'):
        pad(op.ctx, 'a')
        return op.round_wait('手柄确认制造收获', wait=1.2)
    if _find(rows, '号制造台的目标货品'):
        return _choose_good(op, screen, rows)
    moving = goto_manage_page(op, screen, rows, '制造坊')
    if moving is not None:
        return moving
    if any('制造完毕' in _text(r.data) for r in rows):
        if bump(op,'_craft_collects', 3):
            return op.round_fail('一键收获未生效')
        pad(op.ctx, 'y')
        op._craft_results.append('制造收获')
        return op.round_wait('手柄一键收获制造台', wait=1.5)
    idle = [r for r in rows if _text(r.data) == '开工' and r.center.y > 900]
    if not idle or getattr(op, '_craft_tried', 0) >= len(idle):
        op._craft_done = True
        return op.round_wait('制造台已处理', wait=.3)
    slot = idle[0]
    if not slot_focused(screen, slot):
        if bump(op,'_slot_moves', 6):
            return op.round_fail('手柄选择制造台未生效')
        focused = [r for r in rows if r.center.y > 900 and slot_focused(screen, r)]
        pad(op.ctx, 'dpad_left' if not focused or focused[0].center.x > slot.center.x else 'dpad_right')
        return op.round_wait('手柄选择空闲制造台', wait=.6)
    op._craft_tried = getattr(op, '_craft_tried', 0) + 1
    pad(op.ctx, 'a')
    return op.round_wait('手柄打开制造台货品列表', wait=1.5)


def _good_name(row):
    return re.sub(r'[\d（(].*$', '', _text(row.data))


def _choose_good(op, screen, rows):
    craftable = [r for r in rows if '可制造' in _text(r.data) and r.center.x < 1150]
    mask = focus_mask(screen)
    focused = next((r for r in rows if r.center.x < 1150 and re.search(r'[一-鿿]{2,}', _text(r.data))
                    and 250 < r.center.y < 820 and lit(mask, 92, 104, r.center.y + 10, r.center.y + 130, .4)
                    and lit(mask, 1140, 1152, r.center.y + 10, r.center.y + 130, .4)), None)
    start = _find(rows, '开始制造', Rect(1300, 900, 1700, 1000))
    if not craftable:
        op._craft_results.append('没有可制造的货品')
        op._craft_done = True
        pad(op.ctx, 'b')
        return op.round_wait('没有可制造的货品，返回', wait=1.2)
    target = craftable[0]
    if focused is None:
        return op.round_retry('货品焦点未核验，未操作', wait=.6)
    name = _good_name(target)
    if focused is target and start is not None and _find(rows, name, Rect(1380, 380, 1800, 430)):
        if bump(op,'_craft_starts', 3):
            return op.round_fail('开始制造未生效')
        pad(op.ctx, 'a')
        op._craft_results.append(f'开始制造{name}')
        return op.round_wait(f'手柄开始制造 {name}', wait=1.5)
    if bump(op,'_good_moves', 12):
        return op.round_fail(f'手柄选择货品 {name} 未生效')
    pad(op.ctx, 'dpad_down' if target.center.y > focused.center.y else 'dpad_up')
    return op.round_wait(f'手柄选择货品 {name}', wait=.6)


def sales_step(op, screen):
    """售卖铺: pick up dropped coins (RS 拾遗) and report shelves; refilling shelves is not automated yet."""
    rows = ocr_rows(op, screen)
    guide = _guide(op, rows)
    if guide is not None:
        return guide
    if bump(op,'_sales_rounds', 30):
        return op.round_fail('售卖处理轮数过多，已停止')
    if getattr(op, '_sales_done', None) is not None:
        return back_to_entry(op, rows, op._sales_done)
    moving = goto_manage_page(op, screen, rows, '售卖铺')
    if moving is not None:
        return moving
    picks = next((re.search(r'(\d+)/(\d+)', _text(r.data)) for r in rows if '拾遗次数' in _text(r.data)), None)
    if picks and int(picks.group(1)) < int(picks.group(2)) and not getattr(op, '_picked', False):
        op._picked = True
        pad(op.ctx, 'r_thumb')
        return op.round_wait(f'手柄拾遗（今日 {picks.group(1)}/{picks.group(2)}）', wait=1.5)
    short = any('库存不足' in _text(r.data) for r in rows)
    op._sales_done = '货架库存不足，后台暂不更换货品' if short else '货架售卖中'
    return op.round_wait(op._sales_done, wait=.3)
