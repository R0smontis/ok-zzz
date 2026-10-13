"""锄大地 start teleports on the controller map, without the mouse.

The map pans under a fixed cursor at (695, 540); a teleport (fan icon) under the cursor shows its
name and 前往 in the detail panel. Every fan is visited once, nearest first, until the panel names
the route's start. Visited icons are remembered by their offset from the first icon that was
centred, which stays constant while the map pans at a fixed zoom.
"""
from src.navigation.map import _area_match, _candidates_for_template, _match, map_state, steer_to

CURSOR = (695, 540)
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


def choose_patrol_point(op, screen):
    """Put fan icons under the cursor one by one until the detail panel names op.tp_name."""
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
    if getattr(op, '_background_map_stalls', 0) >= 3:
        # The map stopped panning (its edge): that icon cannot be brought under the cursor.
        blocked = op.__dict__.setdefault('_patrol_blocked', [])
        expected = getattr(op, '_background_expected_point', None)
        if expected is not None and icons:
            blocked.append(min(icons, key=lambda i: abs(i[0] - expected[0]) + abs(i[1] - expected[1])))
        op._background_map_stalls = 0
        op.__dict__.pop('_background_map_motion', None)
    blocked = getattr(op, '_patrol_blocked', [])
    icons = [i for i in icons if not any(_near(i, b, 20) for b in blocked)]
    visited = op.__dict__.setdefault('_patrol_visited', {})
    target_rel = getattr(op, '_patrol_target_rel', None)
    centre = next((i for i in sorted(icons, key=lambda i: abs(i[0] - CURSOR[0]) + abs(i[1] - CURSOR[1]))
                   if _near(i, CURSOR)), None)
    if centre is None and target_rel is not None and state['detail'] and state['point']:
        centre = CURSOR  # A focused fan is enlarged and no longer matches its template.
    if centre is None:
        if target_rel is None:
            # Nothing read yet: start with the icon nearest to the cursor.
            if not icons:
                return op.round_retry('地图上没有可见的传送点图标，未操作', wait=.6)
            first = min(icons, key=lambda i: abs(i[0] - CURSOR[0]) + abs(i[1] - CURSOR[1]))
            op._patrol_target_rel = (0., 0.)
            return steer_to(op, state, *first)
        # Between icons: keep steering to where the last press should have brought the target.
        expected = getattr(op, '_background_expected_point', None)
        if expected is None or not icons:
            return op.round_retry('未找到正在定位的传送点，未操作', wait=.6)
        follow = min(icons, key=lambda i: abs(i[0] - expected[0]) + abs(i[1] - expected[1]))
        return steer_to(op, state, *follow)
    centre_rel = target_rel if target_rel is not None else (0., 0.)
    if not (state['detail'] and state['point']):
        # Near the cursor is not under it: nudge it closer; a fan that never opens its panel
        # (e.g. under the player's own marker) is skipped after a few nudges.
        nudges = op.__dict__.get('_patrol_nudges', 0) + 1
        op._patrol_nudges = nudges
        if nudges <= 3:
            return steer_to(op, state, *centre)
        state = dict(state, point='（无详情）')
    op._patrol_nudges = 0
    visited[centre_rel] = state['point']
    cx, cy = centre
    candidates = []
    for icon in icons:
        rel = (icon[0] - cx + centre_rel[0], icon[1] - cy + centre_rel[1])
        if not any(_near(rel, seen) for seen in visited):
            candidates.append((abs(icon[0] - CURSOR[0]) + abs(icon[1] - CURSOR[1]), icon, rel))
    if not candidates:
        names = '、'.join(dict.fromkeys(visited.values()))
        return op.round_fail(f'未找到传送点 {op.tp_name}；已查看：{names}')
    _, icon, rel = min(candidates)
    op._patrol_target_rel = rel
    return steer_to(op, state, *icon)


def as_wait(op, result):
    """Map steps answer RETRY while steering; here the step counter bounds the search instead."""
    if result.result.name == 'RETRY':
        return op.round_wait(result.status, wait=.65)
    return result
