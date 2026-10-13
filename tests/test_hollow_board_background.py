"""棋盘后台移动：使用图上的相邻格，只在新模型帧核验位置后记录进度。"""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from onedragon.base.geometry.rectangle import Rect
from onedragon.base.operation.operation_round_result import OperationRoundResultEnum as R
from src.navigation.hollow_board import board_step
from zzz_od.hollow_zero.game_data.hollow_zero_event import HollowZeroEntry
from zzz_od.hollow_zero.hollow_map.hollow_zero_map import HollowZeroMap, HollowZeroMapNode
from zzz_od.hollow_zero.hollow_runner import HollowRunner
from test_lost_void_background_menus import operation


def node(x, y, name='空白未通行', when=1):
    return HollowZeroMapNode(Rect(x, y, x + 100, y + 100), HollowZeroEntry('9000-' + name), when, .99)


def board(dx=110, dy=0):
    start, adjacent = node(400, 400, '当前'), node(400 + dx, 400 + dy)
    adjacent.path_first_node = adjacent
    adjacent.path_first_need_step_node = adjacent
    adjacent.path_node_cnt, adjacent.path_step_cnt = 1, 1
    grid = HollowZeroMap([start, adjacent], 0, {0: [1], 1: [0]}, 1)
    op = operation(HollowRunner)
    op._handled_events = {'旧事件'}
    op._check_extra_task_finished = Mock(return_value=False)
    op._board_stable = (Rect(400, 400, 500, 500), 0)  # settled on an earlier frame
    op.ctx.withered_domain = SimpleNamespace(
        get_next_to_move=Mock(return_value=adjacent), check_info_before_move=Mock(),
        update_context_after_move=Mock(), had_been_entry=Mock(return_value=False),
        map_service=SimpleNamespace(cal_current_map_by_screen=Mock()))
    return op, grid


def test_board_moves_only_after_marker_is_settled_on_two_frames():
    op, grid = board()
    op._board_stable = None
    assert board_step(op, op.last_screenshot, 1, grid).status == '等待棋盘画面稳定，未移动'
    zoomed = HollowZeroMap([node(430, 420, '当前'), grid.nodes[1]], 0, grid.edges, 2)
    assert board_step(op, op.last_screenshot, 2, zoomed).result == R.WAIT
    op.ctx.controller.btn_press.assert_not_called()
    assert board_step(op, op.last_screenshot, 3, zoomed).result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_ls_right', press_time=.12)


@pytest.mark.parametrize('dx,dy,key', [(110, 0, 'right'), (-110, 0, 'left'),
                                      (0, 110, 'down'), (0, -110, 'up')])
def test_one_adjacent_stick_pulse_does_not_record_success(dx, dy, key):
    op, grid = board(dx, dy)
    assert board_step(op, op.last_screenshot, 1, grid).result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_ls_' + key, press_time=.12)
    op.ctx.controller.click.assert_not_called()
    op.ctx.withered_domain.update_context_after_move.assert_not_called()
    assert grid.current_idx == 0 and grid.nodes[0].entry.entry_name == '当前'


def test_fresh_current_marker_acknowledges_without_faking_map_current():
    op, grid = board()
    board_step(op, op.last_screenshot, 1, grid)
    raw = HollowZeroMap([node(400, 400, '空白已通行', 2), node(510, 400, '当前', 2)], 1, {}, 2)
    op.ctx.withered_domain.map_service.cal_current_map_by_screen.return_value = raw
    result = board_step(op, op.last_screenshot, 2, grid)
    assert result.result == R.WAIT and '已核验' in result.status
    op.ctx.withered_domain.update_context_after_move.assert_called_once()
    assert op.ctx.withered_domain.update_context_after_move.call_args.kwargs == {'update_current': False}
    assert op._board_pending is None and not op._handled_events
    assert grid.current_idx == 0


def test_stale_map_never_counts_as_confirmation():
    op, grid = board()
    board_step(op, op.last_screenshot, 1, grid)
    raw = HollowZeroMap([node(510, 400, '当前', 1)], 0, {}, 1)
    op.ctx.withered_domain.map_service.cal_current_map_by_screen.return_value = raw
    for _ in range(7):
        assert board_step(op, op.last_screenshot, 2, grid).result == R.WAIT
    assert board_step(op, op.last_screenshot, 2, grid).is_fail
    op.ctx.withered_domain.update_context_after_move.assert_not_called()
    assert op.ctx.controller.btn_press.call_count == 1


def test_ignored_pulses_are_bounded_and_do_not_complete_cell():
    op, grid = board()
    board_step(op, op.last_screenshot, 1, grid)
    result = None
    for when in range(2, 30):
        raw = HollowZeroMap([node(400, 400, '当前', when), node(510, 400, when=when)], 0, {}, when)
        op.ctx.withered_domain.map_service.cal_current_map_by_screen.return_value = raw
        result = board_step(op, op.last_screenshot, when, grid)
        if result.is_fail:
            break
    assert result.is_fail and op.ctx.controller.btn_press.call_count == 4
    op.ctx.withered_domain.update_context_after_move.assert_not_called()


@pytest.mark.parametrize('problem', ['no-marker', 'duplicate-marker', 'no-next', 'not-adjacent', 'diagonal'])
def test_invalid_map_or_step_sends_no_input(problem):
    op, grid = board(110, 110) if problem == 'diagonal' else board()
    if problem == 'no-marker': grid.current_idx = None
    if problem == 'duplicate-marker': grid.nodes[1].entry = HollowZeroEntry('9000-当前')
    if problem == 'no-next': op.ctx.withered_domain.get_next_to_move.return_value = None
    if problem == 'not-adjacent': grid.edges = {}
    assert board_step(op, op.last_screenshot, 1, grid).result == R.RETRY
    op.ctx.controller.btn_press.assert_not_called()
    op.ctx.withered_domain.update_context_after_move.assert_not_called()


def test_unexpected_position_is_not_attributed_to_the_requested_cell():
    op, grid = board()
    board_step(op, op.last_screenshot, 1, grid)
    op.ctx.withered_domain.map_service.cal_current_map_by_screen.return_value = HollowZeroMap(
        [node(700, 700, '当前', 2)], 0, {}, 2)
    assert board_step(op, op.last_screenshot, 2, grid).is_fail
    op.ctx.withered_domain.update_context_after_move.assert_not_called()


def test_foreground_missing_next_node_retries_instead_of_dereferencing_none():
    op, grid = board()
    op.ctx.controller.background_mode = False
    grid.nodes[1].path_first_need_step_node = None
    assert op.try_move_by_map(op.last_screenshot, 1, grid).result == R.RETRY
    op.ctx.controller.click.assert_not_called()


def test_recorded_real_board_down_pulse_is_verified_by_new_current_marker():
    import json
    from pathlib import Path
    import cv2
    from zzz_od.hollow_zero.hollow_zero_data_service import HallowZeroDataService
    service = HallowZeroDataService()
    service.reload()
    base = Path(__file__).parent / 'fixtures/withered'

    def recorded(name):
        payload = json.loads((base / (name + '.json')).read_text(encoding='utf-8'))
        when = payload['frame_id']
        nodes = [HollowZeroMapNode(Rect(*row['rect']), service.name_2_entry[row['name']], when, row['confidence'])
                 for row in payload['board']['nodes']]
        grid = HollowZeroMap(nodes, payload['board']['current_idx'],
                             {int(k): v for k, v in payload['board']['edges'].items()}, when)
        image = cv2.cvtColor(cv2.imread(str(base / (name + '.png'))), cv2.COLOR_BGR2RGB)
        return grid, when, image

    before, t1, image1 = recorded('hollow-board-map-ready')
    after, t2, image2 = recorded('hollow-board-down-test')
    target = next(n for n in before.nodes if n.entry.entry_name == '齿轮硬币箱' and 250 < n.pos.y1 < 300)
    target.path_first_node = target.path_first_need_step_node = target
    op = operation(HollowRunner)
    op._handled_events = set()
    op._check_extra_task_finished = Mock(return_value=False)
    op._board_stable = (before.nodes[before.current_idx].pos, t1 - 1)
    op.ctx.withered_domain = SimpleNamespace(get_next_to_move=Mock(return_value=target),
        check_info_before_move=Mock(), update_context_after_move=Mock(), had_been_entry=Mock(return_value=False),
        map_service=SimpleNamespace(cal_current_map_by_screen=Mock(return_value=after)))
    assert board_step(op, image1, t1, before).result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_ls_down', press_time=.12)
    assert '已核验' in board_step(op, image2, t2, before).status
    assert op.ctx.withered_domain.update_context_after_move.call_count == 1


def _recorded_grid(current_rect):
    import json
    from pathlib import Path
    from zzz_od.hollow_zero.hollow_zero_data_service import HallowZeroDataService
    service = HallowZeroDataService()
    service.reload()
    payload = json.loads((Path(__file__).parent / 'fixtures/withered/hollow-resumed-board.json').read_text(encoding='utf-8'))
    nodes = []
    for row in payload['board']['nodes']:
        name = '空白已通行' if row['name'] == '当前' else row['name']
        name = '当前' if row['rect'] == current_rect else name
        nodes.append(HollowZeroMapNode(Rect(*row['rect']), service.name_2_entry[name], 1, row['confidence']))
    current = next(i for i, n in enumerate(nodes) if n.entry.entry_name == '当前')
    return HollowZeroMap(nodes, current, {int(k): v for k, v in payload['board']['edges'].items()}, 1)


def test_hop_reaches_goal_directly_instead_of_bouncing_between_blank_cells():
    from src.navigation.hollow_board import _first_hop
    # Recorded live: the queued 临时拍档 inherited a longer route, so the pad went back and forth.
    above = _recorded_grid([495, 257, 669, 404])
    assert above.nodes[_first_hop(above, 7)].entry.entry_name == '临时拍档'
    start = _recorded_grid([497, 425, 671, 571])
    hop = _first_hop(start, 7)
    assert hop in start.edges[start.current_idx] and hop in start.edges[7]


def test_blank_only_loop_is_bounded():
    op, grid = board()
    op._board_blank_moves = 12
    assert board_step(op, op.last_screenshot, 1, grid).is_fail
    op.ctx.controller.btn_press.assert_not_called()


def test_repeated_target_still_heads_for_its_step_cell_not_upstream_first_hop():
    from zzz_od.hollow_zero.hollow_zero_data_service import HallowZeroDataService
    grid = _recorded_grid([497, 425, 671, 571])
    goal = grid.nodes[7]  # 临时拍档
    goal.path_first_need_step_node = goal
    goal.path_first_node = grid.nodes[15]
    goal.path_go_way = 0  # upstream: same target twice → next_node_to_move is path_first_node
    op, _ = board()
    op._board_stable = (grid.nodes[grid.current_idx].pos, 0)
    op.ctx.withered_domain.get_next_to_move.return_value = goal
    assert '开启的门' in board_step(op, op.last_screenshot, 1, grid).status
    op.ctx.controller.btn_press.assert_called_once_with('xbox_ls_right', press_time=.12)


def test_arriving_on_an_entry_cell_runs_its_upstream_handler_once():
    op, grid = board()
    grid.nodes[1].entry = HollowZeroEntry('0048-守门人')
    handler = Mock(return_value=SimpleNamespace(execute=Mock(return_value=SimpleNamespace(success=True, status='ok'))))
    op._entry_event_handlers = {'守门人': handler}
    op._entry_events = {}
    board_step(op, op.last_screenshot, 1, grid)
    op.ctx.withered_domain.map_service.cal_current_map_by_screen.return_value = HollowZeroMap(
        [node(510, 400, '当前', 2)], 0, {}, 2)
    assert '已核验' in board_step(op, op.last_screenshot, 2, grid).status
    handler.assert_called_once_with(op.ctx)
    op.ctx.withered_domain.had_been_entry.return_value = True
    op._board_stable = (Rect(400, 400, 500, 500), 2)
    board_step(op, op.last_screenshot, 3, grid)
    op.ctx.withered_domain.map_service.cal_current_map_by_screen.return_value = HollowZeroMap(
        [node(510, 400, '当前', 4)], 0, {}, 4)
    board_step(op, op.last_screenshot, 4, grid)
    assert handler.call_count == 1


def test_closed_door_runs_its_entry_handler_instead_of_pulsing_again():
    import cv2
    from pathlib import Path
    image = cv2.cvtColor(cv2.imread(str(Path(__file__).parent / 'fixtures/withered/hollow-door-prompt.png')), cv2.COLOR_BGR2RGB)
    op, grid = board()
    grid.nodes[1].entry = HollowZeroEntry('0050-门扉禁闭-善战')
    handler = Mock(return_value=SimpleNamespace(execute=Mock(return_value=SimpleNamespace(success=True, status='开门'))))
    op._entry_event_handlers = {'门扉禁闭-善战': handler}
    board_step(op, image, 1, grid)
    for when in (2, 3, 4):
        op.ctx.withered_domain.map_service.cal_current_map_by_screen.return_value = HollowZeroMap(
            [node(400, 400, '当前', when)], 0, {}, when)
        result = board_step(op, image, when, grid)
    assert '入口选项' in result.status
    handler.assert_called_once_with(op.ctx)
    assert op.ctx.controller.btn_press.call_count == 1
    op.ctx.withered_domain.update_context_after_move.assert_not_called()


def test_route_to_a_target_behind_two_equal_doors_does_not_alternate():
    import json
    from pathlib import Path
    from src.navigation.hollow_board import _first_hop
    from zzz_od.hollow_zero.hollow_zero_data_service import HallowZeroDataService
    service = HallowZeroDataService()
    service.reload()
    payload = json.loads((Path(__file__).parent / 'fixtures/withered/hollow-two-doors.json').read_text(encoding='utf-8'))

    def grid(current_rect):
        nodes = []
        for row in payload['board']['nodes']:
            name = '空白已通行' if row['name'] == '当前' else row['name']
            name = '当前' if row['rect'] == current_rect else name
            nodes.append(HollowZeroMapNode(Rect(*row['rect']), service.name_2_entry[name], 1, row['confidence']))
        current = next(i for i, n in enumerate(nodes) if n.entry.entry_name == '当前')
        return HollowZeroMap(nodes, current, {int(k): v for k, v in payload['board']['edges'].items()}, 1)

    # Live: 邦布商人 (7) lies behind door 8 (above) or door 9 (lower left); the pad bounced.
    cur = [1060, 425, 1235, 571]
    seen = []
    for _ in range(4):
        g = grid(cur)
        hop = _first_hop(g, 7)
        seen.append(hop)
        if g.nodes[hop].entry.need_step > 0:
            break
        cur = payload['board']['nodes'][hop]['rect']
    assert g.nodes[seen[-1]].entry.entry_name == '门扉禁闭-侵蚀'
    assert len(seen) == len(set(seen))
