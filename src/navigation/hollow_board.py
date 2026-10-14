"""Closed-loop controller movement of the TV board, one graph-verified neighbour at a time.

Unlike the mouse's distant-cell auto path, the pad moves one adjacent cell. Only a fresh
model result can confirm the move; sending a stick pulse does not change visited/current
map state. Real board input and transition events still need live verification.
"""
from onedragon.base.geometry.rectangle import Rect
from src.controls.gamepad import press as pad
from zzz_od.hollow_zero.hollow_map import hollow_map_utils
from zzz_od.hollow_zero.hollow_map.hollow_zero_map import HollowZeroMapNode


def _rect(rect):
    return Rect(rect.x1, rect.y1, rect.x2, rect.y2)


def _same_position(rect, node):
    scale = min(rect.width, rect.height, node.pos.width, node.pos.height)
    return (scale > 0 and abs(rect.center.x - node.pos.center.x) < scale * .4
            and abs(rect.center.y - node.pos.center.y) < scale * .4)


def _settled(a, b):
    """The board zooms in after loading or resuming; a marker frozen across frames is settled."""
    return max(abs(a.x1 - b.x1), abs(a.y1 - b.y1), abs(a.x2 - b.x2), abs(a.y2 - b.y2)) <= 8


def _current(current_map):
    if current_map is None or current_map.current_idx is None:
        return None
    if not 0 <= current_map.current_idx < len(current_map.nodes):
        return None
    markers = [node for node in current_map.nodes if node.entry.entry_name == '当前']
    node = current_map.nodes[current_map.current_idx]
    return node if len(markers) == 1 and node is markers[0] else None


def _confirm_pending(op, screen, screen_time, pending):
    raw = op.ctx.withered_domain.map_service.cal_current_map_by_screen(screen, screen_time)
    current = _current(raw)
    pending['waits'] += 1
    if current is None or raw.check_time <= pending['sent_at'] or current.check_time <= pending['sent_at']:
        if pending['waits'] >= 8:
            return op.round_fail('无法从新棋盘画面核验当前位置，未计入移动')
        return op.round_wait('等待新棋盘当前位置，未重复移动', wait=.5)
    if _same_position(pending['node'].pos, current):
        entry_name = pending['node'].entry.entry_name
        op._board_unexpected = 0
        blank = pending['node'].entry.need_step == 0
        op._board_blank_moves = getattr(op, '_board_blank_moves', 0) + 1 if blank else 0
        # As upstream: entry cells (商人, 守门人, 门扉) only offer an option on arrival.
        handlers = getattr(op, '_entry_event_handlers', {})
        handler = (handlers.get(entry_name)
                   if not op.ctx.withered_domain.had_been_entry(entry_name) else None)
        op.ctx.withered_domain.update_context_after_move(pending['map'], pending['node'], update_current=False)
        op._board_pending = None
        op._board_stable = None
        op._handled_events.clear()
        if handler is not None:
            result = handler(op.ctx).execute()
            if not result.success:
                return op.round_retry(f'{entry_name} 入口处理失败：{result.status}', wait=.5)
            op._handled_events.update(getattr(op, '_entry_events', {}).get(entry_name, []))
        return op.round_wait(f'已核验移动至 {entry_name}', wait=.3)
    if not _same_position(pending['origin'], current):
        # The camera follows the player on large boards, and some cells relocate it: the
        # marker then sits elsewhere on screen. Do not credit the requested cell; re-plan from
        # the fresh board, and stop if this keeps happening.
        op._board_pending = None
        op._board_stable = None
        jumps = getattr(op, '_board_unexpected', 0) + 1
        op._board_unexpected = jumps
        if jumps > 3:
            return op.round_fail('棋盘位置连续与请求的相邻格不一致，未更新移动记录')
        return op.round_wait('当前位置与请求的相邻格不一致，按新棋盘重新规划', wait=.5)
    # A freshly connected pad can be ignored for a few seconds; space the retries out.
    if pending['waits'] < 3:
        return op.round_wait('等待棋盘移动完成', wait=.5)
    # A closed door (门扉禁闭) keeps the marker in place and offers its option on the right.
    entry_name = pending['node'].entry.entry_name
    handler = getattr(op, '_entry_event_handlers', {}).get(entry_name)
    from src.navigation.hollow_events import _event_focus
    if handler is not None and _event_focus(screen) is not None:
        op._board_pending = None
        op._board_stable = None
        result = handler(op.ctx).execute()
        if not result.success:
            return op.round_retry(f'{entry_name} 入口处理失败：{result.status}', wait=.5)
        return op.round_wait(f'已处理 {entry_name} 入口选项', wait=.5)
    if pending['requests'] >= 4:
        # The marker never moved: the cell is not really passable from here (e.g. a decorative
        # screen the model mistook for a cell, live 2026-10-14). As upstream does for doors it
        # cannot pass, mark it visited so the next plan avoids it; stop after a few such cells.
        skipped = getattr(op, '_board_unreachable', 0) + 1
        op._board_unreachable = skipped
        if skipped > 3:
            return op.round_fail('手柄棋盘移动未生效，未计入移动')
        if pending['node'].entry.is_tp:
            # No position proof: do not advance the level/phase or clear the map cache.
            return op.round_fail('传送格移动未核验，不更新楼层或移动记录')
        op.ctx.withered_domain.update_context_after_move(pending['map'], pending['node'], update_current=False)
        op._board_pending = None
        op._board_stable = None
        return op.round_wait(f'{pending["node"].entry.entry_name} 无法到达，标记后重新规划', wait=.5)
    pending.update(requests=pending['requests'] + 1, waits=0, sent_at=screen_time)
    pad(op.ctx, 'ls_' + pending['direction'], .12)
    return op.round_wait('当前位置未变化，重试同一相邻格', wait=.8)


def _first_hop(current_map, goal_idx, avoid=()):
    """First adjacent cell of the cheapest route to the goal.

    Cost is (avoided cells, cells that take a step, cells passed), searched afresh from the
    current cell. The upstream search may overwrite a queued node with a longer equal-cost
    route (the mouse clicks the goal and the game walks), which made the pad bounce between
    blank cells or alternate between two doors.
    """
    import heapq
    start = current_map.current_idx
    best = {start: (0, 0, 0)}
    queue = [(0, 0, 0, start, None)]
    while queue:
        avoided, steps, cells, idx, first = heapq.heappop(queue)
        if idx == goal_idx:
            return first
        if (avoided, steps, cells) > best.get(idx, (avoided, steps, cells)):
            continue
        for nxt in current_map.edges.get(idx, []):
            entry = current_map.nodes[nxt].entry
            if not entry.can_go:
                continue
            cost = (avoided + (entry.entry_name in avoid and nxt != goal_idx),
                    steps + entry.need_step, cells + 1)
            if cost < best.get(nxt, (float('inf'),) * 3):
                best[nxt] = cost
                heapq.heappush(queue, (*cost, nxt, first if first is not None else nxt))
    return None


def board_step(op, screen, screen_time, current_map):
    pending = getattr(op, '_board_pending', None)
    if pending is not None:
        return _confirm_pending(op, screen, screen_time, pending)
    current = _current(current_map)
    if current is None:
        return op.round_retry('未核验唯一棋盘当前位置，未移动', wait=.5)
    if getattr(op, '_board_blank_moves', 0) >= 12:
        return op.round_fail('连续12次只经过空白格，寻路可能在往返，停止移动')
    target = op.ctx.withered_domain.get_next_to_move(current_map)
    # Route to the target ourselves: upstream's first nodes come from a search that can
    # overwrite queued routes, and a repeated target switches it to that faulty first node.
    if target is None:
        return op.round_retry('自动寻路未提供相邻节点，未移动', wait=.5)
    goal_idx = hollow_map_utils.get_node_index(current_map, target)
    avoid = set(getattr(op.ctx.withered_domain, '_get_avoid', lambda: [])())
    hop = _first_hop(current_map, goal_idx, avoid) if goal_idx is not None else None
    step = current_map.nodes[hop] if hop is not None else target.path_first_node
    if step is None:
        return op.round_retry('自动寻路未提供相邻节点，未移动', wait=.5)
    index = hollow_map_utils.get_node_index(current_map, step)
    if index is None or index not in current_map.edges.get(current_map.current_idx, []):
        return op.round_retry('下一格未通过棋盘邻接关系核验，未移动', wait=.5)
    dx, dy = step.pos.center.x - current.pos.center.x, step.pos.center.y - current.pos.center.y
    spacing = min(current.pos.width, current.pos.height, step.pos.width, step.pos.height)
    if spacing <= 0 or max(abs(dx), abs(dy)) < spacing * .5 or min(abs(dx), abs(dy)) > spacing * .4:
        return op.round_retry('相邻格方向不明确，未移动', wait=.5)
    direction = ('right' if dx > 0 else 'left') if abs(dx) > abs(dy) else ('down' if dy > 0 else 'up')
    stable = getattr(op, '_board_stable', None)
    if stable is None or screen_time <= stable[1] or not _settled(stable[0], current.pos):
        op._board_stable = (_rect(current.pos), screen_time)
        return op.round_wait('等待棋盘画面稳定，未移动', wait=.4)
    op.ctx.withered_domain.check_info_before_move(screen, current_map)
    if op._check_extra_task_finished(screen, current_map):
        return op.round_success(op.STATUS_LEAVE)
    # Copy the node: later merged maps may relabel the same object as 当前.
    requested = HollowZeroMapNode(_rect(step.pos), step.entry, step.check_time, step.confidence)
    op._board_pending = dict(map=current_map, node=requested, origin=_rect(current.pos),
                             direction=direction, sent_at=screen_time, requests=1, waits=0)
    op._last_move_time = screen_time
    pad(op.ctx, 'ls_' + direction, .12)
    return op.round_wait(f'手柄前往相邻格 {step.entry.entry_name}，等待真实位置', wait=.8)
