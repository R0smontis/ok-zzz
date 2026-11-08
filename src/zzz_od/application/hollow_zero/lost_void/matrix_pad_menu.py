"""矩阵行动后台手柄菜单：每次输入后由下一轮的新截图核验。"""
import re

from onedragon.base.geometry.rectangle import Rect
from onedragon.base.operation.operation_round_result import OperationRoundResult
from src.controls.gamepad import press as pad
from src.navigation.common import focus_mask, in_rect, norm_text, ocr_rows
from zzz_od.application.hollow_zero.lost_void.lost_void_challenge_config import LostVoidRegionType
from zzz_od.application.hollow_zero.lost_void.matrix_screen import (
    AGENT_LIST, SUPPORT_SLOT, detail_visible, direction_to, main_agents, main_labels, read_team_page,
    right_slot_focused,
)
from zzz_od.application.hollow_zero.lost_void.mission_screen import entry_header


_PRESET_TITLES = Rect(185, 150, 780, 1070)
_SUPPORT_WEAPON = Rect(1240, 375, 1820, 445)
_DEPLOY_POPUP = Rect(560, 380, 1360, 720)


def _text(value):
    return re.sub(r'\s+', '', norm_text(value))


def _state(op, node, limit=16):
    state = getattr(op, '_matrix_pad_menu', None)
    if not isinstance(state, dict) or state.get('node') != node:
        state = {'node': node, 'rounds': 0, 'requests': 0, 'limit': limit}
        op._matrix_pad_menu = state
    state['rounds'] += 1
    return state


def _wait(op, state, message):
    if state['rounds'] >= state['limit']:
        return op.round_fail(message + '，画面未在限定轮次内核验')
    return op.round_wait(message + '，未操作', wait=.5)


def _press(op, state, button, message, maximum=8):
    if state['requests'] >= maximum or state['rounds'] >= state['limit']:
        return op.round_fail(message + '未生效，已达到手柄请求上限')
    state['requests'] += 1
    pad(op.ctx, button)
    return op.round_wait(message + '，等待新画面核验', wait=.6)


def _reveal_controls(op, state):
    # 任务开始可能重建虚拟手柄，游戏此时仍显示键鼠界面，手柄焦点尚未出现。
    # 方向输入只激活/移动焦点，绝不用 A 猜测当前选择。
    reveals = state.get('reveals', 0)
    if reveals >= 2:
        return op.round_fail('手柄方向输入后仍未显示矩阵编队焦点，未选择角色')
    state['reveals'] = reveals + 1
    return _press(op, state, 'ls_left', '显示矩阵编队手柄焦点')


def goto_entry(op) -> OperationRoundResult:
    state = _state(op, 'entry', 24)
    if read_team_page(op) is not None:
        return op.round_success('已核验矩阵行动编队页')
    if detail_visible(op):
        return _press(op, state, 'start', '矩阵行动下一步', maximum=8)
    header = entry_header(op.ctx, op.last_screenshot)
    if header == '迷失之地-入口-常规':
        return _press(op, state, 'lb', '切换迷失之地周期入口', maximum=8)
    if header == '迷失之地-入口-周期':
        rows = ocr_rows(op, op.last_screenshot)
        title = any(_text(row.data) == '矩阵行动'
                    and in_rect(row.center, Rect(700, 180, 1830, 360)) for row in rows)
        action = any(_text(row.data) == '前往挑战'
                     and in_rect(row.center, Rect(750, 720, 1800, 850)) for row in rows)
        if title and action:
            return _press(op, state, 'a', '前往矩阵行动挑战', maximum=8)
    return _wait(op, state, '等待矩阵行动周期入口、详情或编队页')


def open_preset(op) -> OperationRoundResult:
    state = _state(op, 'open_preset')
    page = read_team_page(op)
    if page is None:
        return _wait(op, state, '未核验矩阵行动编队页')
    if page.mode == 'preset':
        return op.round_success('已核验预备编队页签')
    if page.focus is not None:
        return _press(op, state, 'b', '从左侧列表返回右侧编队')
    if page.mode == 'support':
        return _press(op, state, 'dpad_up', '返回主战编队')
    return _press(op, state, 'rb', '切换预备编队页签')


def _preset_target(op):
    teams = op.ctx.team_config.team_list
    idx = op.ctx.lost_void.challenge_config.predefined_team_idx
    if idx == -1:
        idx = 0
    if not isinstance(idx, int) or isinstance(idx, bool) or not 0 <= idx < len(teams):
        raise ValueError('预备编队编号超出范围或未配置编队')
    names = [_text(team.name) for team in teams]
    if not names[idx]:
        raise ValueError('目标预备编队名称为空')
    if names.count(names[idx]) != 1:
        raise ValueError('目标预备编队名称不唯一，请配置不同名称')
    members = tuple(agent_id for agent_id in getattr(teams[idx], 'agent_id_list', ())
                    if agent_id and agent_id != 'unknown')
    return idx, names, members


def _preset_titles(page, names):
    return [(row, names.index(_text(row.data))) for row in page.words(_PRESET_TITLES)
            if _text(row.data) in names and names.count(_text(row.data)) == 1]


def _preset_checked(op, focus):
    part = op.last_screenshot[max(0, focus.y1 + 20):focus.y1 + 69,
                              max(0, focus.x2 - 78):focus.x2 - 25]
    return bool(part.size) and float(focus_mask(part).mean()) > .14


def _empty_preset(page, focus):
    rows = page.words(focus)
    empty = any(_text(row.data) in ('EMPTY', 'EMPT', 'MPT', '待设置编队') for row in rows)
    levels = any(re.fullmatch(r'[1-9]\d?', _text(row.data))
                 and row.center.y > focus.y1 + 160 for row in rows)
    return empty and not levels


def select_preset(op) -> OperationRoundResult:
    try:
        idx, names, members = _preset_target(op)
    except ValueError as exc:
        return op.round_fail(str(exc))
    state = _state(op, 'select_preset', max(24, len(names) * 2 + 12))
    request_limit = max(16, len(names) * 2 + 4)
    target = (idx, names[idx], members)
    if 'target' in state and state['target'] != target:
        return op.round_fail('预备编队配置在选择期间发生变化')
    state['target'] = target
    page = read_team_page(op)
    if page is None or page.mode != 'preset':
        return _wait(op, state, '未核验预备编队页签')
    titles = _preset_titles(page, names)
    wanted = [row for row, index in titles if index == idx]
    if len(wanted) > 1:
        return op.round_fail('画面中的目标预备编队名称不唯一，未选择')
    if state.get('applied'):
        if page.focus is None or len(wanted) != 1 or not in_rect(wanted[0].center, page.focus):
            return _wait(op, state, '等待目标预备编队应用后的焦点核验')
        if not _preset_checked(op, page.focus) or not main_labels(page):
            # 2026-11-08 实机：第一次 A 被吞掉（画面未勾选、主战槽仍为空），再按一次 A 立即应用。
            # 只在画面确实没有任何变化（无勾选、无主战标签）时补按一次，勾选后的 A 不会再发送。
            if (state.get('apply_waits', 0) >= 2 and not state.get('reapplied')
                    and not _preset_checked(op, page.focus) and not main_labels(page)):
                state['reapplied'] = True
                return _press(op, state, 'a', f'应用未生效，再次应用预备编队：{names[idx]}',
                              maximum=request_limit)
            state['apply_waits'] = state.get('apply_waits', 0) + 1
            return _wait(op, state, '等待目标预备编队勾选与主战槽更新')
        roster = main_agents(op, page)
        if not roster:
            return _wait(op, state, '目标预备编队的主战角色尚未全部识别')
        if members and roster != list(members):
            return _wait(op, state, '目标预备编队的主战角色或顺序未匹配')
        op.ctx.lost_void.predefined_team_idx = idx
        return op.round_success(f'已核验应用预备编队：{names[idx]}')
    if page.focus is None:
        if state.get('opened'):
            return _wait(op, state, '等待唯一的预备编队列表焦点')
        if not right_slot_focused(op):
            return _reveal_controls(op, state)
        result = _press(op, state, 'a', '进入预备编队列表', maximum=request_limit)
        state['opened'] = not result.is_fail
        return result
    if wanted:
        # 实际矩阵预备编队是一整行一张卡的竖排列表；绝不左右切列。
        y = wanted[0].center.y
        if page.focus.y1 <= y < page.focus.y2:
            if _empty_preset(page, page.focus):
                return op.round_fail(f'目标预备编队为空：{names[idx]}')
            result = _press(op, state, 'a', f'应用指定预备编队：{names[idx]}', maximum=request_limit)
            state['applied'] = not result.is_fail
            return result
        direction = 'ls_up' if y < page.focus.y1 else 'ls_down'
    elif titles:
        indices = [index for _, index in titles]
        if idx < min(indices):
            direction = 'ls_up'
        elif idx > max(indices):
            direction = 'ls_down'
        else:
            return op.round_fail(f'可见编队顺序中未匹配目标预备编队：{names[idx]}')
    else:
        # 从中途恢复时先向上寻找可识别锚点；之后沿已核验配置顺序继续。
        direction = state.get('direction', 'ls_up')
    state['direction'] = direction
    if state['requests'] >= request_limit or state['rounds'] >= state['limit']:
        return op.round_fail(f'未找到指定预备编队：{names[idx]}，已达到竖向查找上限')
    return _press(op, state, direction, f'竖向查找预备编队：{names[idx]}', maximum=request_limit)


def open_support(op) -> OperationRoundResult:
    state = _state(op, 'open_support')
    page = read_team_page(op)
    if page is None:
        return _wait(op, state, '未核验矩阵行动编队页')
    if page.mode == 'support':
        return op.round_success('已核验协战代理人页')
    if page.focus is not None:
        return _press(op, state, 'b', '从主战左侧列表返回右侧')
    return _press(op, state, 'dpad_down', '切换右侧协战代理人槽')


def wait_support(op) -> OperationRoundResult:
    state = _state(op, 'wait_support', 12)
    page = read_team_page(op)
    if page is not None and page.mode == 'support':
        return op.round_success('已核验协战代理人列表')
    return _wait(op, state, '等待完整的协战代理人页')


def _support_cell(point):
    if not in_rect(point, AGENT_LIST):
        return None
    column = int((point.x - 185) // 157)
    row = int((point.y - 90) // 200)
    return row, column


def _support_target(page):
    rows = page.words(AGENT_LIST)
    candidates = [row for row in rows if _text(row.data).upper() == 'UP']
    if not candidates:
        candidates = [row for row in rows if _text(row.data) == '60']
    cells = [_support_cell(row.center) for row in candidates]
    return min((cell for cell in cells if cell is not None), default=None)


def _support_rect(cell):
    row, column = cell
    return Rect(185 + column * 157, 90 + row * 200,
                334 + column * 157, min(1070, 285 + row * 200))


def _support_category(page):
    for row in page.words(_SUPPORT_WEAPON):
        text = _text(row.data).replace('昇常', '异常').replace('異常', '异常')
        match = re.search(r'[\[【［]([^\]】］:：]+)[:：]', text)
        if match is not None and re.fullmatch(r'[\u4e00-\u9fff]{1,8}', match[1]):
            return match[1]
    return None


def select_support(op) -> OperationRoundResult:
    state = _state(op, 'select_support', 24)
    page = read_team_page(op)
    if page is None or page.mode != 'support':
        return _wait(op, state, '未核验协战代理人列表')
    if 'target' not in state:
        cell = _support_target(page)
        if cell is None:
            return _wait(op, state, '未找到协战 UP 或等级 60 的目标')
        state['target'] = cell
    target = _support_rect(state['target'])
    selected_left = any(_text(row.data) == '协战' for row in page.words(target))
    selected_right = any(_text(row.data) == '协战' for row in page.words(SUPPORT_SLOT))
    if selected_left and selected_right:
        if not state.get('verified'):
            config = op.ctx.lost_void.challenge_config
            config.clear_artifact_priority_in_battle()
            category = _support_category(page)
            if category:
                config.artifact_priority_in_battle.append(category)
            state['verified'] = True
        return op.round_success('已核验指定协战代理人与右侧协战槽')
    # 左侧已选却缺右侧核验时只能等待，不能再次 A 把目标取消。
    if selected_left or state.get('applied'):
        return _wait(op, state, '等待目标协战代理人与右侧协战槽同步')
    if selected_right and not any(_text(row.data) == '协战' for row in page.words(AGENT_LIST)):
        return _wait(op, state, '右侧协战已选，等待左侧已选角色身份核验')
    if page.focus is None:
        if state.get('opened'):
            return _wait(op, state, '等待唯一的协战列表焦点')
        if not right_slot_focused(op, support=True):
            return _reveal_controls(op, state)
        result = _press(op, state, 'a', '进入协战代理人列表', maximum=12)
        state['opened'] = not result.is_fail
        return result
    direction = direction_to(page.focus, target.center)
    if direction is not None:
        return _press(op, state, direction.replace('dpad_', 'ls_'), '移动至目标协战代理人', maximum=12)
    result = _press(op, state, 'a', '选择目标协战代理人', maximum=12)
    state['applied'] = not result.is_fail
    return result


def _deployment_rejection(op):
    rows = ocr_rows(op, op.last_screenshot, _DEPLOY_POPUP)
    text = ''.join(_text(row.data) for row in rows)
    if '至少选择' in text or '至少一名代理人' in text:
        return '出战队伍为空或未满足代理人要求'
    if ('请选择' in text or '未选择' in text) and '协战代理人' in text:
        return '开始挑战被拒绝：未选择协战代理人'
    if '驱动盘数量已达到可拥有上限' in text:
        return '驱动盘数量已达到可拥有上限'
    return None


def start_challenge(op) -> OperationRoundResult:
    state = _state(op, 'start_challenge', 32)
    rejection = _deployment_rejection(op)
    if rejection is not None:
        return op.round_fail(rejection)
    if op.ctx.lost_void.in_normal_world(op.last_screenshot):
        op.next_region_type = LostVoidRegionType.ENTRY
        op.ctx.lost_void.in_start_room = True
        return op.round_success('已核验矩阵行动进入大世界')
    page = read_team_page(op)
    if page is None:
        return _wait(op, state, '等待挑战部署后的大世界，尚未核验进入')
    if not main_labels(page):
        return op.round_fail('主战编队为空，未开始挑战')
    if not any(_text(row.data) == '协战' for row in page.words(SUPPORT_SLOT)):
        return op.round_fail('协战代理人未选择，未开始挑战')
    return _press(op, state, 'start', '开始矩阵行动挑战', maximum=3)
