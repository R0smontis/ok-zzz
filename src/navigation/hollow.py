"""枯萎之都 (零号空洞) in the background: entrance, zone map and mission list with the controller.

Verified on game frames of 2026-10-13: the 零号空洞 entrance shows 迷失之地 | 枯萎之都 with the A
prompt under the focused half; the zone map marks the focused zone with a small chevron above
its icon; the mission list outlines the selected row in yellow; 下一步 is the menu button.
"""
import cv2
import numpy as np

from onedragon.base.geometry.rectangle import Rect
from src.controls.gamepad import press as pad
from src.navigation.menus import focus_mask


def _text(value) -> str:
    return (str(value).replace(' ', '').replace('枯菱', '枯萎').replace('廈', '厦')
            .replace('・', '-').replace('·', '-'))


def _rows(op, screen):
    rows = op.ctx.ocr_service.get_ocr_result_list(image=screen, rect=Rect(0, 0, 1920, 1080))
    return rows if isinstance(rows, (list, tuple)) else []


def _bump(op, name, limit) -> bool:
    value = op.__dict__.get(name, 0) + 1
    op.__dict__[name] = value
    return value > limit


def zone_map(rows) -> bool:
    words = {_text(r.data) for r in rows}
    return '奖励进度' in words and ('资质考核' in words or '旧都列车' in words)


def mission_list(rows) -> bool:
    return (any(_text(r.data) == '下一步' and r.center.y > 980 for r in rows)
            and sum('-' in _text(r.data) and 1100 < r.center.x < 1500 for r in rows) >= 2)


def entrance_step(op, screen):
    """零号空洞 entrance → 枯萎之都 zone map."""
    rows = _rows(op, screen)
    if zone_map(rows) or mission_list(rows):
        return op.round_success('已进入枯萎之都-入口')
    target = next((r for r in rows if _text(r.data) == '枯萎之都' and r.center.y > 700), None)
    prompt = next((r for r in rows if _text(r.data) == 'A' and 880 < r.center.y < 960), None)
    if target is None or prompt is None:
        if _bump(op, '_hollow_entry_waits', 8):
            return op.round_fail('未核验零号空洞入口画面')
        return op.round_wait('等待零号空洞入口画面', wait=.8)
    if abs(prompt.center.x - target.center.x) < 250:
        if _bump(op, '_hollow_entry_opens', 3):
            return op.round_fail('手柄进入枯萎之都未生效')
        pad(op.ctx, 'a')
        return op.round_wait('手柄进入枯萎之都', wait=1.5)
    if _bump(op, '_hollow_entry_moves', 4):
        return op.round_fail('手柄选择枯萎之都未生效')
    pad(op.ctx, 'dpad_right' if target.center.x > prompt.center.x else 'dpad_left')
    return op.round_wait('手柄选择枯萎之都', wait=.8)


def zone_focused(screen, label) -> bool:
    """A chevron about 36x24 px sits 200-300 px above the focused zone's label. The big ENTRY
    emblem is wider and touches the window's edge, so it never counts."""
    x, y = label.center.x, label.center.y
    band = focus_mask(screen[max(0, y - 320):max(0, y - 190), max(0, x - 40):x + 40]).astype(np.uint8)
    if band.size == 0:
        return False
    _, _, stats, _ = cv2.connectedComponentsWithStats(band)
    return any(20 <= w <= 60 and 12 <= h <= 40 and area >= 200 and bx > 0 and bx + w < band.shape[1]
               for bx, _, w, h, area in stats[1:])


def zone_step(op, screen, zone):
    """Zone map → the mission list of `zone` (e.g. 旧都列车)."""
    rows = _rows(op, screen)
    if mission_list(rows):
        return op.round_success('已打开副本列表')
    if not zone_map(rows):
        if _bump(op, '_hollow_zone_waits', 8):
            return op.round_fail('未核验枯萎之都区域图')
        return op.round_wait('等待枯萎之都区域图', wait=.8)
    labels = [r for r in rows if 150 < r.center.y < 900 and len(_text(r.data)) == 4
              and all('一' <= c <= '鿿' for c in _text(r.data)) and _text(r.data) != '未解锁']
    target = next((r for r in labels if _text(r.data) == _text(zone)), None)
    if target is None:
        return op.round_fail(f'枯萎之都区域图中没有 {zone}')
    focused = [r for r in labels if zone_focused(screen, r)]
    if len(focused) != 1:
        return op.round_retry('区域焦点未唯一核验，未操作', wait=.6)
    if focused[0] is target:
        if _bump(op, '_hollow_zone_opens', 3):
            return op.round_fail(f'手柄打开{zone}未生效')
        pad(op.ctx, 'a')
        return op.round_wait(f'手柄打开{zone}', wait=1.5)
    if _bump(op, '_hollow_zone_moves', 10):
        return op.round_fail(f'手柄选择{zone}未生效')
    dx, dy = target.center.x - focused[0].center.x, target.center.y - focused[0].center.y
    if abs(dx) >= abs(dy):
        button = 'dpad_right' if dx > 0 else 'dpad_left'
    else:
        button = 'dpad_down' if dy > 0 else 'dpad_up'
    pad(op.ctx, button)
    return op.round_wait(f'手柄选择区域：{_text(focused[0].data)} → {zone}', wait=.8)


def row_selected(screen, y) -> bool:
    """The selected mission row lights both vertical edges of its frame."""
    y = int(y)
    left = focus_mask(screen[max(0, y - 25):y + 25, 1108:1120])
    right = focus_mask(screen[max(0, y - 25):y + 25, 1824:1836])
    return float(np.mean(left)) > .25 and float(np.mean(right)) > .25


def mission_step(op, screen, mission):
    """Mission list → select `mission` (旧都列车-内部); 下一步 is pressed by the next node."""
    rows = _rows(op, screen)
    if not mission_list(rows):
        if _bump(op, '_hollow_list_waits', 8):
            return op.round_fail('未核验枯萎之都副本列表')
        return op.round_wait('等待枯萎之都副本列表', wait=.8)
    lines = [(r, r.center.y + 13) for r in rows if '-' in _text(r.data) and 1100 < r.center.x < 1500]
    target = next((line for line in lines if _text(line[0].data) == _text(mission)), None)
    selected = [line for line in lines if row_selected(screen, line[1])]
    if target is None:
        return op.round_fail(f'副本列表中没有 {mission}')
    if len(selected) != 1:
        return op.round_retry('副本选择未唯一核验，未操作', wait=.6)
    if selected[0] is target:
        return op.round_success(f'已选中 {mission}')
    if _bump(op, '_hollow_list_moves', 10):
        return op.round_fail(f'手柄选择{mission}未生效')
    pad(op.ctx, 'dpad_down' if target[1] > selected[0][1] else 'dpad_up')
    return op.round_wait(f'手柄选择副本：{_text(selected[0][0].data)} → {mission}', wait=.6)


def next_step(op, screen):
    """下一步 on the menu button until the deployment page shows 出战."""
    rows = _rows(op, screen)
    words = {_text(r.data) for r in rows}
    if '出战' in words and '战斗设置' in words:
        return op.round_success('出战')
    if mission_list(rows):
        if _bump(op, '_hollow_next_presses', 3):
            return op.round_fail('手柄下一步未生效')
        pad(op.ctx, 'start')
        return op.round_wait('手柄下一步，等待出战画面', wait=1.5)
    if _bump(op, '_hollow_next_waits', 8):
        return op.round_fail('下一步后未出现出战画面')
    return op.round_wait('等待出战画面', wait=.8)
