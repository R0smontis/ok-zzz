"""矩阵行动自由编队：每次手柄输入后只用下一轮画面决定后续动作。"""
import cv2
import numpy as np

from src.controls.gamepad import press
from src.navigation.common import in_rect, norm_text
from zzz_od.application.hollow_zero.lost_void.matrix_screen import (
    AGENT_LIST, direction_to, main_agents, main_labels, read_team_page, right_slot_focused,
)
from zzz_od.game_data.agent import AgentEnum
from zzz_od.operation.agent_template_matcher import match_team_agent_template

_AGENTS = {item.value.agent_id: item.value for item in AgentEnum}
_FRAME_LIMIT = 4
_MOVE_LIMIT = max(40, len(_AGENTS) * 2)
_ROUND_LIMIT = _MOVE_LIMIT * 12


def _fail(op, state, reason):
    state['phase'] = 'failed'
    state['reason'] = reason
    return op.round_fail(reason)


def _wait(op, state, key, reason):
    state[key] = state.get(key, 0) + 1
    if state[key] >= _FRAME_LIMIT:
        return _fail(op, state, reason)
    return op.round_wait(reason, wait=.35)


def _name(agent_id):
    return _AGENTS[agent_id].agent_name


def _selected(page, focus):
    # 实际 matrix-agent-focused 的克拉蕾徽标被 OCR 识别成了「主点」。
    return any(norm_text(row.data) in ('主战', '主点') for row in page.words(focus))


def _at_top(page):
    # 左摇杆在第一行继续向上会循环到末尾；顶部标题和首行焦点同时可见时即可向下搜索。
    return (page.focus is not None and 150 <= page.focus.y1 <= 180
            and any(norm_text(row.data) == '代理人' and 95 <= row.center.y < 150
                    for row in page.words(AGENT_LIST)))


def _target_match(op, agent_id):
    matches = match_team_agent_template(op.ctx, op.last_screenshot, AGENT_LIST, [agent_id])
    matches = [match for match in matches if in_rect(match.center, AGENT_LIST)]
    return max(matches, key=lambda match: match.confidence) if matches else None


def _view(op, page):
    """焦点坐标不足以判断翻页：贴住底边时左摇杆会滚动列表而不移动边框。"""
    part = op.last_screenshot[AGENT_LIST.y1:AGENT_LIST.y2, AGENT_LIST.x1:AGENT_LIST.x2]
    thumbnail = cv2.resize(cv2.cvtColor(part, cv2.COLOR_RGB2GRAY), (24, 30),
                           interpolation=cv2.INTER_AREA).astype(np.int16)
    return page.focus.center, thumbnail


def _same_view(first, second):
    a, image_a = first
    b, image_b = second
    # 黄框会呼吸，卡片本身不变；不能把黄框明暗当成成功移动。
    return (abs(a.x - b.x) <= 6 and abs(a.y - b.y) <= 6
            and float(np.mean(np.abs(image_a - image_b))) < 3.5)


def _press_open(op, state, button, expectation, reason):
    state['pending'] = {'kind': 'open', 'expectation': expectation, 'waits': 0,
                        'reason': reason}
    press(op.ctx, button)
    return op.round_wait(reason, wait=.4)


def _move(op, state, page, button, boundary):
    if state['moves'] >= _MOVE_LIMIT:
        return _fail(op, state, f'寻找代理人 {_name(state["agent"])} 时超过导航上限')
    view = _view(op, page)
    if not state['seen']:
        state['seen'].append(view)
    state['moves'] += 1
    state['pending'] = {'kind': 'move', 'before': view, 'boundary': boundary, 'waits': 0}
    # 实测十字键在第四行向下会切到协战面板；左摇杆才会自动滚动代理人网格。
    press(op.ctx, button)
    return op.round_wait(f'移动代理人列表焦点：{_name(state["agent"])}', wait=.4)


def _pending(op, state, page):
    """返回 None 表示前一次输入已经通过新画面核验，其他结果直接交还 Operation。"""
    pending = state.get('pending')
    if pending is None:
        return None
    if pending['kind'] == 'open':
        expected = pending['expectation']
        changed = ((expected == 'main' and page.mode != 'support' and page.focus is None)
                   or (expected == 'right' and page.focus is None)
                   or (expected == 'agents' and page.mode == 'agents')
                   or (expected == 'list' and page.mode == 'agents' and page.focus is not None)
                   or (expected == 'focus' and (page.focus is not None
                       or right_slot_focused(op, support=page.mode == 'support'))))
        if changed:
            state['pending'] = None
            return None
        pending['waits'] += 1
        if pending['waits'] >= _FRAME_LIMIT:
            return _fail(op, state, f'{pending["reason"]}后画面未改变，停止选人')
        return op.round_wait(f'等待{pending["reason"]}', wait=.35)

    if page.mode != 'agents':
        return _fail(op, state, '代理人导航离开了自由编队列表，停止选人')
    if page.focus is None:
        pending['waits'] += 1
        if pending['waits'] >= _FRAME_LIMIT:
            return _fail(op, state, '移动后未识别代理人列表焦点，停止选人')
        return op.round_wait('等待代理人列表焦点', wait=.35)
    current = _view(op, page)
    if not _same_view(pending['before'], current):
        if any(_same_view(previous, current) for previous in state['seen']):
            return _fail(op, state, f'寻找代理人 {_name(state["agent"])} 时列表焦点发生循环')
        state['seen'].append(current)
        state['pending'] = None
        return None
    pending['waits'] += 1
    if pending['waits'] < _FRAME_LIMIT:
        return op.round_wait('等待代理人列表滚动或焦点移动', wait=.35)
    state['pending'] = None
    if pending['boundary'] == 'top':
        state['phase'] = 'seek'
        state['rewound'] = True
        state['seen'] = [current]
        return None
    if pending['boundary'] == 'bottom':
        return _fail(op, state, f'未找到指定角色：{_name(state["agent"])}；列表已到底，请确认已解锁')
    return _fail(op, state, f'代理人 {_name(state["agent"])} 的列表焦点持续未移动，停止选人')


def _begin_agent(state):
    removing = state['clearing']
    if removing and not state['roster']:
        state['clearing'] = removing = False
    state['agent'] = state['roster'][0] if removing else state['target'][len(state['roster'])]
    state['phase'] = 'seek'
    state['rewound'] = False
    state['moves'] = 0
    state['seen'] = []
    state['label_waits'] = 0


def _verify(op, state, page, roster):
    expected = state['expected']
    if roster is not None and roster not in (state['roster'], expected):
        return _fail(op, state, '主战编队角色或顺序校验失败，停止选人')
    matched = _target_match(op, state['agent']) if page.mode == 'agents' and page.focus else None
    focused = matched is not None and in_rect(matched.center, page.focus)
    selected = focused and _selected(page, page.focus)
    if (roster != expected or len(main_labels(page)) != len(expected) or not focused
            or selected == state['clearing']):
        return _wait(op, state, 'verify_waits', '所选角色主战标记或编队顺序未通过核验，停止选人')
    state['roster'] = list(expected)
    state.pop('expected')
    if not state['clearing'] and roster == state['target']:
        state['phase'] = 'done'
        return op.round_success('已按指定顺序组成主战编队')
    _begin_agent(state)
    return op.round_wait('主战角色变更已核验，准备下一位代理人', wait=.2)


def select_agents(op, target: list[str]):
    """上游负责运行/暂停、配置及模板守卫；本状态不与前台 _matrix_selection 共用。"""
    state = getattr(op, '_matrix_pad_selection', None)
    if state is None:
        state = {'target': list(target), 'phase': 'prepare', 'roster': None,
                 'clearing': True, 'pending': None, 'rounds': 0}
        op._matrix_pad_selection = state
    if state['target'] != target:
        return _fail(op, state, '编队配置在选人期间发生变化，请重新运行')
    if state['phase'] == 'failed':
        return op.round_fail(state['reason'])
    if not target or any(agent_id not in _AGENTS for agent_id in target):
        return _fail(op, state, '未获得有效的主战代理人配置')
    state['rounds'] += 1
    if state['rounds'] > _ROUND_LIMIT:
        return _fail(op, state, '代理人编队操作超过画面等待上限，停止选人')
    if op.last_screenshot is None:
        return _fail(op, state, '未获得编队画面，停止选人')
    page = read_team_page(op)
    if page is None:
        return _wait(op, state, 'page_waits', '未确认矩阵行动编队页面，停止选人')
    state['page_waits'] = 0
    roster = main_agents(op, page)
    if state['phase'] == 'verify':
        # 核验期间绝不补按 A；未知槽位与 OCR 漏读也不能当成空队伍。
        return _verify(op, state, page, roster)
    if roster is None:
        return _wait(op, state, 'roster_waits', '主战编队有未识别角色，停止选人')
    state['roster_waits'] = 0
    if state['roster'] is None:
        state['roster'] = list(roster)
        if roster == target:
            state['phase'] = 'done'
            return op.round_success('主战编队已符合指定角色及顺序')
    elif roster != state['roster']:
        return _fail(op, state, '主战编队在导航期间发生变化，停止选人')
    if state['phase'] == 'done':
        if roster == target:
            return op.round_success('主战编队已符合指定角色及顺序')
        return _fail(op, state, '主战编队与指定顺序不一致，停止选人')

    result = _pending(op, state, page)
    if result is not None:
        return result
    if state['phase'] == 'prepare':
        if page.focus is None and not right_slot_focused(op, support=page.mode == 'support'):
            return _press_open(op, state, 'ls_left', 'focus', '显示矩阵编队手柄焦点')
        if page.mode == 'support':
            if page.focus is not None:
                return _press_open(op, state, 'b', 'right', '退出协战代理人列表')
            return _press_open(op, state, 'dpad_up', 'main', '切回主战编队')
        if page.mode == 'preset':
            return _press_open(op, state, 'lb', 'agents', '切换自由编队页签')
        if page.focus is None:
            return _press_open(op, state, 'a', 'list', '进入主战代理人列表')
        _begin_agent(state)

    if page.mode != 'agents':
        return _fail(op, state, '代理人导航离开了自由编队列表，停止选人')
    if page.focus is None:
        return _wait(op, state, 'focus_waits', '未识别自由编队代理人列表焦点，停止选人')
    state['focus_waits'] = 0
    at_top = _at_top(page)
    if state['phase'] == 'rewind':
        if not at_top:
            return _move(op, state, page, 'ls_up', 'top')
        state['phase'] = 'seek'
        state['rewound'] = True
        state['seen'] = []
    matched = _target_match(op, state['agent'])
    if matched is None:
        if not state['rewound']:
            state['seen'] = []
            if not at_top:
                state['phase'] = 'rewind'
                return _move(op, state, page, 'ls_up', 'top')
            state['rewound'] = True
        return _move(op, state, page, 'ls_down', 'bottom')
    direction = direction_to(page.focus, matched.center)
    if direction is not None:
        return _move(op, state, page, direction.replace('dpad_', 'ls_'), 'focus')
    if _selected(page, page.focus) != state['clearing']:
        return _wait(op, state, 'label_waits',
                     f'代理人 {_name(state["agent"])} 的当前主战标记与编队不一致，停止选人')
    before = state['roster']
    state['expected'] = ([agent for agent in before if agent != state['agent']]
                         if state['clearing'] else before + [state['agent']])
    state['phase'] = 'verify'
    state['verify_waits'] = 0
    press(op.ctx, 'a')
    return op.round_wait(f'等待核验代理人 {_name(state["agent"])} 的主战变更', wait=.5)
