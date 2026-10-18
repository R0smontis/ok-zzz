"""锄大地 start teleports on the controller map, without the mouse.

The map pans under a fixed cursor at (695, 540); a teleport (fan icon) under the cursor shows its
name and 前往 in the detail panel. Every fan is visited once, nearest first, until the panel names
the route's start. Visited icons are remembered by their offset from the first icon that was
centred, which stays constant while the map pans at a fixed zoom.
"""
import numpy as np

from onedragon.base.geometry.rectangle import Rect
from onedragon.utils.log_utils import log
from src.controls.gamepad import press as pad
from src.navigation.common import MAP_CURSOR, focus_mask, ocr_rows
from src.navigation.map import _area_match, _candidates_for_template, _match, map_state, steer_to

CURSOR = MAP_CURSOR
SAME_ICON = 45


def teleport_icons(screen):
    """Screen centres of the fan icons inside the map area."""
    icons = []
    for x, y, _ in _candidates_for_template(screen, '3d_map_tp_icon_1', '', many=True):
        if not any(abs(x - ix) < 30 and abs(y - iy) < 30 for ix, iy in icons):
            icons.append((x, y))
    return icons


def _near(a, b, limit=SAME_ICON):
    return abs(a[0] - b[0]) < limit and abs(a[1] - b[1]) < limit


# Measured on the 3D map at its default zoom: screen x ≈ 1.13·Δlm x; y is foreshortened (≈0.55-1.0).
LM_SCALE = (1.13, .75)


def _lm_pos(op, name):
    for icon in getattr(getattr(op, 'large_map', None), 'icon_list', None) or []:
        if icon.icon_name and _match(name, icon.icon_name):
            return icon.lm_pos.x, icon.lm_pos.y
    return None


def predict_target(op, named):
    """Expected relative position of the target from teleports already identified by name."""
    target = getattr(op, 'target_icon', None)
    if target is None:
        return None
    anchors = [(rel, lm) for name, rel in named.items() if (lm := _lm_pos(op, name)) is not None]
    if not anchors:
        return None
    scale = list(LM_SCALE)
    for axis in (0, 1):
        lms = [lm[axis] for _, lm in anchors]
        if len(anchors) >= 2 and max(lms) - min(lms) > 150:
            mean_l = sum(lms) / len(lms)
            mean_r = sum(rel[axis] for rel, _ in anchors) / len(anchors)
            fitted = (sum((lm[axis] - mean_l) * (rel[axis] - mean_r) for rel, lm in anchors)
                      / sum((a - mean_l) ** 2 for a in lms))
            if .3 < fitted < 2:
                scale[axis] = fitted
    goal = (target.lm_pos.x, target.lm_pos.y)
    guesses = [(rel[0] + scale[0] * (goal[0] - lm[0]), rel[1] + scale[1] * (goal[1] - lm[1]))
               for rel, lm in anchors]
    return sum(g[0] for g in guesses) / len(guesses), sum(g[1] for g in guesses) / len(guesses)


def _track(op, icons):
    """Map offset: screen = rel + offset. Follows the last pan, then snaps to known fans."""
    known = op.__dict__.setdefault('_patrol_known', [])
    offset = getattr(op, '_patrol_offset', None)
    if offset is None:
        offset = (0., 0.)
    else:
        shift = getattr(op, '_patrol_shift', (0., 0.))
        offset = (offset[0] + shift[0], offset[1] + shift[1])
        pairs = []
        for icon in icons:
            rel = (icon[0] - offset[0], icon[1] - offset[1])
            near = min(known, key=lambda k: abs(k['rel'][0] - rel[0]) + abs(k['rel'][1] - rel[1]), default=None)
            if near is not None and _near(near['rel'], rel, 60):
                pairs.append((icon[0] - near['rel'][0], icon[1] - near['rel'][1]))
        if pairs:
            pairs.sort()
            offset = pairs[len(pairs) // 2]
    op._patrol_shift = (0., 0.)
    op._patrol_offset = offset
    for icon in icons:
        rel = (icon[0] - offset[0], icon[1] - offset[1])
        if not any(_near(k['rel'], rel) for k in known):
            known.append(dict(rel=rel, name=None, tries=0))
    return offset, known


def _steer(op, state, x, y):
    result = steer_to(op, state, x, y)
    expected = getattr(op, '_background_expected_point', None)
    if expected is not None:
        op._patrol_shift = (expected[0] - x, expected[1] - y)
    return result


def _steer_limit(aim, here):
    """Steers allowed for one fan: 6, or up to 12 while each steer still brings it closer.

    Slow final presses move a fan only ~20 px (live 2026-10-17); a fan 60-90 px away used to
    be abandoned just short of the cursor, and the search moved on to the next one.
    """
    gap = abs(aim['rel'][0] - here[0]) + abs(aim['rel'][1] - here[1])
    if aim.get('gap_steers') != aim.get('steers', 0):
        aim['progress'] = gap < aim.get('gap', float('inf')) - 6
        aim['gap'], aim['gap_steers'] = gap, aim.get('steers', 0)
    return 12 if aim.get('progress') else 6


def choose_patrol_point(op, screen):
    """Put fan icons under the cursor one by one until the detail panel names op.tp_name.

    Every fan seen gets a fixed map position (screen minus the tracked pan offset). Names read
    from the detail panel attach to those positions; a known name seen elsewhere corrects the
    offset. With named fans on the large map the target's position is predicted, and the search
    moves toward it, also past the edge of the current view.
    """
    state = map_state(op, screen)
    if state is None:
        return op.round_retry('未核验地图，暂停传送点搜索', wait=.5)
    if not _area_match(state, op.area_name):
        return op.round_fail(f'搜索传送点时地图区域未核验：{state["title"]} / {state["selected"]}')
    if state['detail'] and _match(state['point'], op.tp_name):
        if state['can_go']:
            return op.round_success(f'已核验目标传送点：{op.area_name} / {op.tp_name}')
        return op.round_fail(f'传送点 {op.tp_name} 尚未解锁')
    steps = getattr(op, '_patrol_steps', 0)
    if steps >= 40:
        return op.round_fail(f'后台未找到传送点 {op.tp_name}')
    op._patrol_steps = steps + 1

    icons = teleport_icons(screen)
    offset, known = _track(op, icons)
    aim = getattr(op, '_patrol_aim', None)
    if getattr(op, '_background_map_stalls', 0) >= 3:
        # The map stopped panning (its edge): the aimed fan cannot reach the cursor.
        if aim is not None:
            aim['tries'] = 99
        op._background_map_stalls = 0
        op.__dict__.pop('_background_map_motion', None)
        op._patrol_aim = aim = None

    here = (CURSOR[0] - offset[0], CURSOR[1] - offset[1])
    under = min(known, key=lambda k: abs(k['rel'][0] - here[0]) + abs(k['rel'][1] - here[1]), default=None)
    if under is not None and not _near(under['rel'], here):
        under = None
    if state['detail'] and state['point']:
        name = state['point']
        seen = next((k for k in known if k['name'] and _match(k['name'], name)), None)
        if seen is not None and (under is None or seen is not under):
            # The same fan read again somewhere else: the tracked offset drifted.
            offset = (CURSOR[0] - seen['rel'][0], CURSOR[1] - seen['rel'][1])
            op._patrol_offset = offset
            if under is not None and under['name'] is None:
                known.remove(under)
            under = seen
            here = seen['rel']
        if under is None:
            under = dict(rel=here, name=None, tries=0)
            known.append(under)
        if under['name'] is None:
            under['name'] = name
            log.info(f'传送点搜索：相对位置 ({under["rel"][0]:.0f}, {under["rel"][1]:.0f}) = {name}')
        if aim is not None and aim is not under and _near(aim['rel'], under['rel'], 60):
            aim['tries'] = 99  # the aimed fan resolved to this one
        op._patrol_aim = aim = None
    elif aim is not None and (_near(aim['rel'], here, 30) or aim.get('steers', 0) >= _steer_limit(aim, here)):
        # Close to the cursor but no panel (or never reached): nudge, then give up on it, and on
        # the duplicate entries the offset error left around the same spot (live 2026-10-14).
        aim['tries'] += 1
        if aim['tries'] > 3 or aim.get('steers', 0) >= _steer_limit(aim, here):
            for k in known:
                if k['name'] is None and _near(k['rel'], aim['rel'], 60):
                    k['name'] = '（无详情）'
            op._patrol_aim = aim = None

    named = {k['name']: k['rel'] for k in known if k['name'] and k['name'] != '（无详情）'}
    goal = predict_target(op, named)
    if aim is None or aim['name'] is not None or aim['tries'] > 3:
        options = [k for k in known if k['name'] is None and k['tries'] <= 3]
        if goal is not None:
            options.sort(key=lambda k: abs(k['rel'][0] - goal[0]) + abs(k['rel'][1] - goal[1]))
            gap = abs(here[0] - goal[0]) + abs(here[1] - goal[1])
            if not options or (abs(options[0]['rel'][0] - goal[0]) + abs(options[0]['rel'][1] - goal[1])) > gap - 60:
                pans = getattr(op, '_patrol_pans', 0)
                if pans < 8:
                    op._patrol_pans = pans + 1
                    dx, dy = goal[0] - here[0], goal[1] - here[1]
                    length = max(1., (dx * dx + dy * dy) ** .5)
                    reach = min(length, 600.)
                    return _steer(op, state, CURSOR[0] + dx / length * reach, CURSOR[1] + dy / length * reach)
        else:
            options.sort(key=lambda k: abs(k['rel'][0] - here[0]) + abs(k['rel'][1] - here[1]))
        if not options:
            names = '、'.join(dict.fromkeys(k['name'] for k in known if k['name']))
            return op.round_fail(f'未找到传送点 {op.tp_name}；已查看：{names or "无"}')
        op._patrol_aim = aim = options[0]
    aim['steers'] = aim.get('steers', 0) + 1
    predicted = (aim['rel'][0] + offset[0], aim['rel'][1] + offset[1])
    # Odometry is only an estimate. If the fan is visible, steer to its measured centre rather
    # than continuing to press toward a stale coordinate beside it.
    measured = min(icons, key=lambda i: abs(i[0] - predicted[0]) + abs(i[1] - predicted[1]), default=None)
    if measured is not None and _near(measured, predicted, 60):
        return _steer(op, state, *measured)
    return _steer(op, state, *predicted)


def as_wait(op, result):
    """Map steps answer RETRY while steering; here the step counter bounds the search instead."""
    if result.result.name == 'RETRY':
        return op.round_wait(result.status, wait=.65)
    return result


def sub_area_state(op, screen):
    """LS opens a filled-focus list above the current sub-area label at the bottom left."""
    state = map_state(op, screen)
    # 列表选中区域后，实际地图标题可能还没更新；不能操作旧地图的同名子区域。
    if state is None or not _match(state['title'], op.area_name):
        return None
    names = [area.area_name for area in op.target_area.parent_area.sub_area_list]
    rows = ocr_rows(op, screen, Rect(40, 580, 415, 1060))
    current = next((name for row in rows if row.center.y > 985
                    for name in names if _match(str(row.data), name)), None)
    choices = [(name, row.center) for row in rows if 600 < row.center.y < 975
               for name in names if _match(str(row.data), name)]
    focused = []
    for name, centre in choices:
        fill = screen[centre.y - 22:centre.y + 22, 75:385]
        if fill.size and float(np.mean(focus_mask(fill))) > .45:
            focused.append((name, centre))
    return dict(current=current, choices=choices, focused=focused)


def open_sub_area(op, screen):
    state = sub_area_state(op, screen)
    if state is None or state['current'] is None:
        return op.round_retry('未核验地图及当前子区域，未操作', wait=.6)
    if state['choices']:
        return op.round_success('子区域列表已打开')
    if _match(state['current'], op.target_area.area_name):
        return op.round_success('无需选择')
    opens = getattr(op, '_subarea_opens', 0)
    if opens >= 3:
        return op.round_fail('手柄打开地图子区域列表未生效')
    op._subarea_opens = opens + 1
    pad(op.ctx, 'l_thumb')
    return op.round_wait('手柄打开地图子区域列表', wait=.8)


def choose_sub_area(op, screen):
    state = sub_area_state(op, screen)
    if state is None:
        return op.round_retry('未核验目标地图，未操作', wait=.6)
    if not state['choices']:
        if state['current'] is not None and _match(state['current'], op.target_area.area_name):
            return op.round_success(f'已核验子区域：{state["current"]}')
        return open_sub_area(op, screen)
    target = next((row for row in state['choices'] if _match(row[0], op.target_area.area_name)), None)
    if target is None:
        return op.round_fail(f'子区域列表中没有 {op.target_area.area_name}')
    if len(state['focused']) != 1:
        return op.round_retry('子区域焦点未唯一核验，未操作', wait=.6)
    current = state['focused'][0]
    if current[0] == target[0]:
        confirms = getattr(op, '_subarea_confirms', 0)
        if confirms >= 3:
            return op.round_fail('手柄确认子区域未生效')
        op._subarea_confirms = confirms + 1
        pad(op.ctx, 'a')
        return op.round_wait(f'手柄切换至 {target[0]}，等待实际标题', wait=1.2)
    moves = getattr(op, '_subarea_moves', 0)
    if moves >= 8:
        return op.round_fail(f'手柄选择子区域 {target[0]} 未生效')
    op._subarea_moves = moves + 1
    pad(op.ctx, 'dpad_up' if target[1].y < current[1].y else 'dpad_down')
    return op.round_wait(f'手柄选择子区域：{current[0]} → {target[0]}', wait=.6)
