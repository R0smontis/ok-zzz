"""矩阵行动编队页的实际页签、列表焦点与主战槽核验（1920×1080）。"""
from dataclasses import dataclass

import cv2
import numpy as np

from onedragon.base.geometry.rectangle import Rect
from src.navigation.common import focus_mask, in_rect, norm_text, ocr_rows
from zzz_od.operation.agent_template_matcher import match_team_agent_template

MAIN_SLOTS = Rect(1028, 162, 1430, 299)
SUPPORT_SLOT = Rect(1020, 350, 1180, 510)
AGENT_LIST = Rect(185, 90, 966, 1070)


@dataclass
class TeamPage:
    mode: str  # agents / preset / support
    rows: list
    focus: Rect | None

    def words(self, rect):
        return [row for row in self.rows if in_rect(row.center, rect)]


def list_focus(screen, mode):
    """只接受完整的黄绿矩形边框，排除页签填充、头像及右侧槽位圆环。"""
    mask = focus_mask(screen[90:1070, 175:975]).astype(np.uint8)
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    found = []
    for x, y, width, height, area in stats[1:]:
        valid_size = (740 <= width <= 810 and 250 <= height <= 300) if mode == 'preset' else (
            130 <= width <= 165 and 175 <= height <= 210)
        if not valid_size or area < (3500 if mode == 'preset' else 1500):
            continue
        # A coloured portrait can be large, but cannot supply both straight side borders.
        left = mask[y + 20:y + height - 20, x:x + 6]
        right = mask[y + 20:y + height - 20, x + width - 6:x + width]
        if np.mean(left) > .25 and np.mean(right) > .25:
            found.append(Rect(int(x + 175), int(y + 90), int(x + width + 175), int(y + height + 90)))
    return found[0] if len(found) == 1 else None


def read_team_page(op):
    rows = ocr_rows(op, op.last_screenshot, Rect(180, 0, 1860, 1070))
    def has(text, rect):
        return any(norm_text(row.data) == text and in_rect(row.center, rect) for row in rows)
    if not (has('主战编队', Rect(1000, 100, 1200, 165))
            and has('协战代理人', Rect(1000, 300, 1250, 365))
            and has('开始挑战', Rect(1600, 980, 1850, 1070))):
        return None
    tabs = has('自由编队', Rect(200, 0, 950, 95)) and has('预备编队', Rect(200, 0, 950, 95))
    if tabs:
        active = focus_mask(op.last_screenshot[20:75, 240:915])
        agents = float(np.mean(active[:, :320])) > .35
        preset = float(np.mean(active[:, 320:])) > .35
        if agents == preset:
            return None
        mode = 'agents' if agents else 'preset'
    elif has('代理人', Rect(200, 0, 950, 90)):
        mode = 'support'
    else:
        return None
    return TeamPage(mode, rows, list_focus(op.last_screenshot, mode))


def main_labels(page):
    return [row for row in page.words(MAIN_SLOTS) if norm_text(row.data) in ('主战', '主点')]


def main_agents(op, page):
    """识别主战槽角色及顺序；有槽位未识别时返回 None，而不是误报空队伍。"""
    matches = match_team_agent_template(op.ctx, op.last_screenshot, MAIN_SLOTS)
    best = {}
    for match in matches:
        agent_id = match.data.agent_id
        if agent_id not in best or match.confidence > best[agent_id].confidence:
            best[agent_id] = match
    ordered = sorted(best.values(), key=lambda match: match.center.x)
    if len(ordered) != len(main_labels(page)):
        return None
    return [match.data.agent_id for match in ordered]


def detail_visible(op):
    title = ocr_rows(op, op.last_screenshot, Rect(950, 150, 1220, 300))
    if not any(norm_text(row.data) == '矩阵行动' for row in title):
        return False
    footer = ocr_rows(op, op.last_screenshot, Rect(1600, 980, 1850, 1070))
    return '下一步' in ''.join(norm_text(row.data) for row in sorted(footer, key=lambda row: row.center.x))


def direction_to(focus, point):
    """一次只移动一个方向；下一轮必须重新读取实际焦点。"""
    if in_rect(point, focus):
        return None
    if point.x < focus.x1:
        return 'dpad_left'
    if point.x >= focus.x2:
        return 'dpad_right'
    return 'dpad_up' if point.y < focus.y1 else 'dpad_down'


def right_slot_focused(op, support=False):
    """没有列表框还不足以确认右侧焦点；核验槽位圆环的两段亮弧。"""
    y = 197 if support else 0
    for x in ((0,) if support else (0, 135, 270, 405)):
        top = focus_mask(op.last_screenshot[177 + y:199 + y, 1055 + x:1125 + x])
        side = focus_mask(op.last_screenshot[205 + y:253 + y, 1041 + x:1059 + x])
        if int(top.sum()) > 80 and int(side.sum()) > 80:
            return True
    return False
