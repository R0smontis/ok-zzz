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
    """下一步 on the menu button until the deployment page shows 出战.

    A suspended run answers 下一步 with 「当前正在处理：…是否继续？」; 确认 resumes it.
    """
    from src.navigation.menus import label_focused
    rows = _rows(op, screen)
    words = {_text(r.data) for r in rows}
    if '出战' in words and '战斗设置' in words:
        return op.round_success('出战')
    resume = any('是否继续' in _text(r.data) for r in rows)
    if getattr(op, '_hollow_resume_pending', False):
        if resume:
            if _bump(op, '_hollow_resume_waits', 6):
                return op.round_fail('确认继续后对话框未关闭，未重复确认')
            return op.round_wait('等待继续探索生效，未重复确认', wait=.6)
        op._hollow_resume_pending = False
        return op.round_success('继续-确认')
    if resume:
        confirm = next((r for r in rows if _text(r.data) == '确认' and 560 < r.center.y < 660), None)
        if confirm is None or not label_focused(screen, confirm.center, 120):
            return op.round_retry('继续探索的确认焦点未核验，未操作', wait=.6)
        if _bump(op, '_hollow_resume_presses', 2):
            return op.round_fail('手柄确认继续探索未生效')
        op._hollow_resume_pending = True
        pad(op.ctx, 'a')
        return op.round_wait('手柄确认继续已暂离的探索', wait=1.2)
    if mission_list(rows):
        if _bump(op, '_hollow_next_presses', 3):
            return op.round_fail('手柄下一步未生效')
        pad(op.ctx, 'start')
        return op.round_wait('手柄下一步，等待出战画面', wait=1.5)
    if _bump(op, '_hollow_next_waits', 8):
        return op.round_fail('下一步后未出现出战画面')
    return op.round_wait('等待出战画面', wait=.8)


def _leader_identity(rows):
    """The character picker prints the focused agent's full name at the bottom left."""
    from zzz_od.game_data.agent import AgentEnum
    text = ''.join(_text(row.data) for row in sorted(rows, key=lambda r: r.center.x)
                   if 50 < row.center.x < 1050 and 850 < row.center.y < 970)
    matches = [a.value for a in AgentEnum if text.startswith(_text(a.value.agent_name))]
    return max(matches, key=lambda a: len(a.agent_name), default=None)


def squad_step(op, screen, targets):
    """Keep an existing leader; an empty squad may select its configured first target with A/X.

    The picker is only operated after this flow verified and opened an empty leader slot.
    A/X delivery never counts as success: the deployment page must show the chosen name.
    """
    from zzz_od.game_data.agent import AgentEnum, AgentTypeEnum
    rows = _rows(op, screen)
    words = {_text(row.data) for row in rows}
    pending = getattr(op, '_leader_pending', None)
    if '领队' in words and '战斗设置' in words and '出战' in words:
        names = {_text(r.data) for r in rows if 300 < r.center.x < 620 and 420 < r.center.y < 510}
        assigned = next((a.value for a in AgentEnum if _text(a.value.agent_name) in names), None)
        if assigned is not None:
            if pending is not None and assigned.agent_id != pending:
                return op.round_fail('确认后领队身份不匹配，未出战')
            return op.round_success(f'已核验领队：{assigned.agent_name}')
        if 'EMPTY' not in names:
            return op.round_retry('领队槽状态未识别，未操作', wait=.6)
        if pending is not None:
            return op.round_fail('选择后领队仍为空，未重复操作')
        if not isinstance(targets, (list, tuple)) or not targets or not isinstance(targets[0], str):
            return op.round_fail('队伍为空：请配置挑战模板的目标代理人或在游戏内配置领队')
        target = targets[0]
        accepted = {a.value.agent_id for a in AgentEnum} | {a.value.agent_name for a in AgentEnum}
        accepted |= {t.value for t in AgentTypeEnum}
        if target not in accepted:
            return op.round_fail(f'领队目标配置无效：{target}')
        focus = screen[242:312, 450:660]
        if not focus.size or float(np.mean(focus_mask(focus))) <= .35:
            return op.round_retry('空领队槽焦点未核验，未操作', wait=.6)
        if _bump(op, '_leader_opens', 3):
            return op.round_fail('手柄打开领队列表未生效')
        op._leader_target = target
        pad(op.ctx, 'a')
        return op.round_wait('手柄打开空领队的角色列表', wait=1.2)
    if '确认阵容' in words and '角色详情' in words and '快捷编队' in words:
        if not getattr(op, '_leader_opens', 0):
            return op.round_fail('未由本流程打开角色列表，不改变已选队伍')
        if pending is not None:
            if _bump(op, '_leader_confirms', 3):
                return op.round_fail('手柄确认阵容未生效')
            pad(op.ctx, 'x')
            return op.round_wait('手柄确认领队阵容，等待实际编队页', wait=1.2)
        current = _leader_identity(rows)
        if current is None:
            return op.round_retry('当前角色姓名未核验，未选择', wait=.6)
        target = op._leader_target
        if target in (current.agent_id, current.agent_name, current.agent_type.value):
            op._leader_pending = current.agent_id
            pad(op.ctx, 'a')
            return op.round_wait(f'手柄选择领队 {current.agent_name}', wait=.8)
        step = getattr(op, '_leader_scan', 0)
        if step >= 36:
            return op.round_fail(f'角色列表中未找到领队目标 {target}，未出战')
        # Three staggered columns; browse each row back and forth, reading the name after every press.
        direction = ('right', 'right', 'down', 'left', 'left', 'down')[step % 6]
        op._leader_scan = step + 1
        pad(op.ctx, 'dpad_' + direction)
        return op.round_wait(f'手柄浏览角色：{current.agent_name} → {target}', wait=.6)
    if _bump(op, '_leader_waits', 8):
        return op.round_fail('未核验枯萎之都编队画面')
    return op.round_wait('等待枯萎之都编队画面', wait=.6)
