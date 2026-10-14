"""巡逻遍历结束不等于路线完成；失败不能计入轮次或丢失续跑进度。"""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml

from onedragon.base.operation.application_run_record import AppRunRecord
from onedragon.base.operation.operation_base import OperationResult
from onedragon.base.operation.operation_round_result import OperationRoundResultEnum as R
from onedragon.utils import os_utils
from zzz_od.application.world_patrol.world_patrol_app import WorldPatrolApp
from zzz_od.application.world_patrol.world_patrol_run_record import WorldPatrolRunRecord
from test_lost_void_background_menus import operation


@pytest.fixture
def record(tmp_path, monkeypatch):
    monkeypatch.setattr(os_utils, 'get_work_dir', lambda: str(tmp_path))
    monkeypatch.setattr(WorldPatrolRunRecord, 'get_current_dt', lambda self: '20261013')
    return WorldPatrolRunRecord(instance_idx=1)


def app(record):
    op = operation(WorldPatrolApp)
    op.config = SimpleNamespace(auto_battle='全配队通用', route_list='', daily_loop_count=1,
                                route_retry_times=1, route_retry_action='skip_on_stuck_again',
                                loop_interval_seconds=1800)
    op.ctx.run_context = SimpleNamespace(is_context_stop=False)
    op.ctx.auto_battle_context = Mock()
    op.run_record = record
    op.route_list = [SimpleNamespace(full_id=name) for name in ('a', 'b')]
    op.route_idx = 0
    op.failed_routes = {}
    op._round_failed = False
    op._round_summary = ''
    record.set_routes_per_round(2)
    return op


def route_results(monkeypatch, *results):
    from zzz_od.application.world_patrol import world_patrol_app as module
    old = module.WorldPatrolRunRoute
    factory = Mock(side_effect=[SimpleNamespace(execute=Mock(return_value=r)) for r in results])
    factory.STATUS_UI_DISAPPEARED = old.STATUS_UI_DISAPPEARED
    factory.STATUS_STUCK_IN_BATTLE = old.STATUS_STUCK_IN_BATTLE
    monkeypatch.setattr(module, 'WorldPatrolRunRoute', factory)
    return factory


def test_partial_round_is_failed_and_keeps_finished_routes(record):
    op = app(record)
    record.add_record('a')
    op.failed_routes['b'] = '子区域尚未适配'
    result = op.decide_next_round()
    assert result.is_fail and result.status == '路线未全部完成'
    assert '1/2' in result.data and 'b：子区域尚未适配' in result.data
    assert record.completed_rounds == 0 and record.finished == ['a']


def test_no_successful_route_does_not_complete_a_round(record):
    op = app(record)
    assert op.decide_next_round().is_fail
    assert record.completed_rounds == 0 and '0/2' in op._round_summary


def test_other_routes_in_record_cannot_hide_a_missing_selected_route(record):
    op = app(record)
    record.add_record('a')
    record.add_record('not-selected')
    assert op.decide_next_round().is_fail
    assert record.completed_rounds == 0


def test_all_selected_routes_complete_the_round_once(record):
    op = app(record)
    for route in op.route_list:
        record.add_record(route.full_id)
    result = op.decide_next_round()
    assert result.is_success and result.status == '全部完成'
    assert record.completed_rounds == 1
    record.current_round = 2
    assert op.decide_next_round().is_success
    assert record.completed_rounds == 1


def test_next_round_resets_only_that_rounds_routes(record):
    op = app(record)
    record.total_rounds = 2
    record.round_start_time = 0
    for route in op.route_list:
        record.add_record(route.full_id)
    assert op.decide_next_round().status == '进入轮间等待'
    assert record.completed_rounds == 1
    assert op.prepare_next_round().status == '进入下一轮'
    assert record.current_round == 2 and record.finished == []
    assert record.completed_rounds == 1 and op.route_idx == 0


def test_run_records_only_success_and_continues_to_other_routes(record, monkeypatch):
    op = app(record)
    factory = route_results(monkeypatch, OperationResult(False, '传送失败'), OperationResult(True, '完成'))
    assert op.run_route().result == R.WAIT
    assert op.failed_routes == {'a': '传送失败'} and record.finished == []
    assert op.run_route().result == R.WAIT
    assert record.finished == ['b'] and op.route_idx == 2
    assert op.run_route().status == '路线已全部完成'
    assert op.decide_next_round().is_fail and record.completed_rounds == 0
    assert factory.call_count == 2


def test_resume_skips_success_and_only_runs_missing_route(record, monkeypatch):
    op = app(record)
    record.add_record('a')
    factory = route_results(monkeypatch, OperationResult(True, '完成'))
    assert '跳过已完成路线 a' in op.run_route().status
    assert factory.call_count == 0
    assert op.run_route().result == R.WAIT
    assert [args.args[1].full_id for args in factory.call_args_list] == ['b']
    assert op.decide_next_round().is_success and record.completed_rounds == 1


def test_manual_stop_does_not_advance_or_record_route(record, monkeypatch):
    op = app(record)
    route_results(monkeypatch, OperationResult(False, '人工结束'))
    op.ctx.run_context.is_context_stop = True
    assert op.run_route().is_fail
    assert record.finished == [] and op.route_idx == 0 and not op.failed_routes
    op.ctx.controller.stop_moving_forward.assert_called_once()


@pytest.mark.parametrize('failed', [False, True])
def test_finish_returns_to_safe_world_and_preserves_round_outcome(record, monkeypatch, failed):
    from zzz_od.application.world_patrol import world_patrol_app as module
    op = app(record)
    op._round_failed, op._round_summary = failed, '本轮路线完成 1/2'
    back = Mock(return_value=SimpleNamespace(execute=Mock(return_value=OperationResult(True, '大世界-普通'))))
    monkeypatch.setattr(module, 'BackToNormalWorld', back)
    result = op.finish()
    assert result.is_fail if failed else result.is_success
    back.assert_called_once_with(op.ctx, ensure_normal_world=True)
    op.ctx.auto_battle_context.stop_auto_battle.assert_called_once()
    if failed:
        assert result.status == op._round_summary


def test_repeated_init_does_not_duplicate_routes_or_keep_failure_counters(record):
    op = app(record)
    service = SimpleNamespace(load_data=Mock(), area_list=[object()],
                              get_world_patrol_routes_by_area=Mock(return_value=op.route_list.copy()))
    op.ctx.world_patrol_service = service
    for _ in range(2):
        op.route_idx = 9
        op.failed_routes = {'b': '旧失败'}
        assert op.init_world_patrol().is_success
        assert len(op.route_list) == 2 and op.route_idx == 0 and not op.failed_routes


def test_empty_selection_is_not_reported_as_completed(record):
    op = app(record)
    op.ctx.world_patrol_service = SimpleNamespace(load_data=Mock(), area_list=[])
    assert op.init_world_patrol().is_fail and record.completed_rounds == 0


def test_record_rejects_partial_increment_and_duplicate_routes(record):
    record.set_routes_per_round(2)
    record.add_record('a')
    record.add_record('a')
    assert record.finished == ['a']
    with pytest.raises(ValueError, match='路线未全部完成'):
        record.inc_completed_rounds()
    assert record.completed_rounds == 0


@pytest.mark.parametrize('finished,rounds,status,expected_rounds,expected_status', [
    (['a'], 1, AppRunRecord.STATUS_SUCCESS, 0, AppRunRecord.STATUS_WAIT),
    ([], 2, AppRunRecord.STATUS_SUCCESS, 1, AppRunRecord.STATUS_WAIT),
    (['a', 'b'], 1, AppRunRecord.STATUS_SUCCESS, 1, AppRunRecord.STATUS_SUCCESS),
    ([], 1, AppRunRecord.STATUS_FAIL, 1, AppRunRecord.STATUS_FAIL),
])
def test_legacy_completion_repair_keeps_routes_and_prior_rounds(
        tmp_path, monkeypatch, finished, rounds, status, expected_rounds, expected_status):
    monkeypatch.setattr(os_utils, 'get_work_dir', lambda: str(tmp_path))
    monkeypatch.setattr(WorldPatrolRunRecord, 'get_current_dt', lambda self: '20261013')
    folder = tmp_path / 'config/01/app_run_record'
    folder.mkdir(parents=True)
    path = folder / 'world_patrol.yml'
    path.write_text(yaml.safe_dump(dict(dt='20261013', run_status=status, routes_per_round=2,
                                       completed_rounds=rounds, finished=finished)), encoding='utf-8')
    migrated = WorldPatrolRunRecord(instance_idx=1)
    assert migrated.completed_rounds == expected_rounds and migrated.run_status == expected_status
    assert migrated.finished == finished and migrated.get('completion_version') == 1
    assert WorldPatrolRunRecord(instance_idx=1).completed_rounds == expected_rounds


def test_route_start_in_battle_fights_first_then_teleports(monkeypatch):
    from zzz_od.application.world_patrol.operation import world_patrol_run_route as module
    op = operation(module.WorldPatrolRunRoute)
    op.ctx.controller.background_mode = True
    op.config = SimpleNamespace(auto_battle='全配队通用')
    op.in_battle = False
    op.last_check_battle_time = 0
    op.last_screenshot, op.last_screenshot_time = None, 10.
    battle = Mock(auto_op=None, last_check_in_battle=True)
    op.ctx.auto_battle_context = battle
    op.ctx.battle_assistant_config = SimpleNamespace(screenshot_interval=.02)
    op.ctx.world_patrol_service = SimpleNamespace(cut_mini_map=Mock(return_value=SimpleNamespace(play_mask_found=True)))
    monkeypatch.setattr(module.time, 'sleep', lambda _: None)
    assert op.battle_before_start().result == R.WAIT
    battle.start_auto_battle.assert_called_once()
    battle.last_check_in_battle = False
    op.last_screenshot_time = 12.
    result = op.battle_before_start()
    assert result.is_success and not op.in_battle
    battle.stop_auto_battle.assert_called_once()


def test_endless_pre_start_battle_stops_the_round_without_losing_progress(record, monkeypatch):
    from zzz_od.application.world_patrol import world_patrol_app as module
    op = app(record)
    record.add_record('a')
    op.route_idx = 1
    status = module.WorldPatrolRunRoute.STATUS_STUCK_IN_BATTLE
    route_results(monkeypatch, OperationResult(False, status))
    result = op.run_route()
    assert result.is_fail and status in result.status
    assert record.finished == ['a'] and op.failed_routes == {'b': status}
    op.ctx.auto_battle_context.stop_auto_battle.assert_called()


def test_pre_start_battle_is_time_bounded(monkeypatch):
    from zzz_od.application.world_patrol.operation import world_patrol_run_route as module
    op = operation(module.WorldPatrolRunRoute)
    op.config = SimpleNamespace(auto_battle='全配队通用')
    op.in_battle = False
    op.last_check_battle_time = 0
    op.last_screenshot, op.last_screenshot_time = None, 0.
    battle = Mock(auto_op=object(), last_check_in_battle=True)
    op.ctx.auto_battle_context = battle
    op.ctx.battle_assistant_config = SimpleNamespace(screenshot_interval=.02)
    monkeypatch.setattr(module.time, 'sleep', lambda _: None)
    escape = Mock(return_value=SimpleNamespace(execute=Mock(return_value=OperationResult(True, '大世界-勘域'))))
    monkeypatch.setattr(module, 'BackToNormalWorld', escape)
    assert op.battle_before_start().result == R.WAIT
    op.last_screenshot_time = module.WorldPatrolRunRoute.PRE_BATTLE_SECONDS + 1
    result = op.battle_before_start()
    assert result.is_success and result.status == '脱离卡死后出发'
    battle.stop_auto_battle.assert_called_once()
    escape.assert_called_once_with(op.ctx)
    op.in_battle = False
    escape.return_value.execute.return_value = OperationResult(False, '手柄打开菜单脱离卡死未生效')
    op.last_screenshot_time = 0.
    op.battle_before_start()
    op.last_screenshot_time = module.WorldPatrolRunRoute.PRE_BATTLE_SECONDS + 1
    result = op.battle_before_start()
    assert result.is_fail and result.status.startswith(module.WorldPatrolRunRoute.STATUS_STUCK_IN_BATTLE)
