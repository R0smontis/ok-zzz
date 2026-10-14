"""后台拐角等待实测朝向；旋转停留不是平移卡住，不发送真实输入。"""
from types import SimpleNamespace
from unittest.mock import Mock
from onedragon.base.operation.operation_round_result import OperationRoundResultEnum as R

from onedragon.base.geometry.point import Point
from zzz_od.application.world_patrol.operation.world_patrol_run_route import WorldPatrolRunRoute
from test_lost_void_background_menus import operation


def route(background=True):
    op = operation(WorldPatrolRunRoute)
    op.ctx.controller.background_mode = background
    op.current_pos = Point(734, 232)
    op.last_angle = op.last_angle_diff_command = None
    op.turn_compensator = Mock(scale=1.)
    op.turn_compensator.turn.side_effect = lambda angle, **_: max(-45, min(45, angle))
    op.last_screenshot_time = 10.
    op.stuck_pos, op.stuck_pos_start_time = op.current_pos, 1.
    op.is_restarted = True
    return op


def test_recorded_research_corner_rotates_before_resuming_forward():
    op = route()
    target = Point(688, 248)
    op._turn_and_move(target, SimpleNamespace(view_angle=139.5))
    op.ctx.controller.stop_moving_forward.assert_called_once()
    op.ctx.controller.start_moving_forward.assert_not_called()
    assert op._turning_in_place
    op.last_screenshot_time = 13.
    assert not op._process_stuck_with_pos(op.current_pos)
    op._turn_and_move(target, SimpleNamespace(view_angle=190.))
    assert not op._turning_in_place
    op.ctx.controller.start_moving_forward.assert_called_once()


def test_turning_without_heading_progress_has_a_time_limit():
    op = route()
    op._turn_and_move(Point(688, 248), SimpleNamespace(view_angle=139.5))
    op.last_screenshot_time = 19.
    assert op._process_stuck_with_pos(op.current_pos)
    op.ctx.controller.start_moving_forward.assert_not_called()


def test_foreground_mouse_turning_keeps_existing_movement_behavior():
    op = route(background=False)
    op._turn_and_move(Point(688, 248), SimpleNamespace(view_angle=139.5))
    op.ctx.controller.start_moving_forward.assert_called_once()
    assert not op._turning_in_place


def test_already_reached_waypoint_does_not_turn_toward_a_point_behind():
    op = route()
    op.current_pos = Point(688, 248)
    op.current_idx = 0
    op.pos_stuck_attempts = 0
    op.backtrack_active = False
    op._update_current_pos = Mock(return_value=None)
    op._turn_and_move = Mock()
    result = op.handle_move(SimpleNamespace(data=['688', '248']), SimpleNamespace(view_angle=190.), False)
    assert result.result == R.WAIT and op.current_idx == 1
    op._turn_and_move.assert_not_called()


def test_pause_and_battle_clear_the_turning_deadline():
    op = route()
    op.in_battle = False
    op._turning_in_place = True
    op.handle_pause()
    assert not op._turning_in_place
    op._turning_in_place = True
    op.ctx.auto_battle_context = Mock(auto_op=object())
    op.init_auto_battle()
    assert op.in_battle and not op._turning_in_place
