"""应用配置、工厂和完成判定共享实时设置，不操作游戏。"""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from onedragon.base.operation.application.application_run_context import ApplicationRunContext
from onedragon.base.operation.application_run_record import AppRunRecord
from onedragon.utils import os_utils
from src.tasks.app_task_base import AppTaskBase
from zzz_od.application.hollow_zero.lost_void.lost_void_app_factory import LostVoidAppFactory
from zzz_od.application.hollow_zero.lost_void.lost_void_config import LostVoidTaskEnum


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.setattr(os_utils, '_work_dir', tmp_path)
    ctx = SimpleNamespace(current_instance_idx=1,
        game_account_config=SimpleNamespace(game_refresh_hour_offset=4),
        lost_void=SimpleNamespace(init_before_run=Mock()))
    ctx.run_context = ApplicationRunContext(ctx)
    ctx.run_context.registry_application(LostVoidAppFactory(ctx))
    return ctx


def apply_options(ctx, **values):
    task = SimpleNamespace(app_id='lost_void', name='迷失之地', ctx=ctx,
        config=values, _option_keys=list(values), _parse_option=lambda _key, value: value,
        log_info=Mock())
    AppTaskBase.apply_options(task)


@pytest.mark.parametrize('first', ['context_config', 'factory_config', 'context_record', 'factory_record'])
def test_config_and_record_are_shared_regardless_of_access_order(context, first):
    run = context.run_context
    factory = run.get_factory('lost_void')
    getters = {
        'context_config': lambda: run.get_config('lost_void', 1),
        'factory_config': lambda: factory.get_config(1, 'one_dragon'),
        'context_record': lambda: run.get_run_record('lost_void', 1),
        'factory_record': lambda: factory.get_run_record(1),
    }
    getters[first]()
    config = getters['context_config']()
    record = getters['context_record']()
    assert config is getters['factory_config']() is record.config
    assert record is getters['factory_record']()
    assert run.get_config('lost_void', 2) is not config
    assert run.get_config('lost_void', 1, 'other_group') is not config
    assert run.get_run_record('lost_void', 2) is not record


def test_switching_completed_bounty_to_weekly_plan_starts_challenge(context):
    run = context.run_context
    # 第一轮使用悬赏模式并完成；随后在同一进程内从界面修改模式。
    apply_options(context, extra_task=LostVoidTaskEnum.BOUNTY_COMMISSION.value.value)
    first_app = run.get_application('lost_void', 1)
    record = first_app.run_record
    record.bounty_commission_complete = True
    record.update_status(AppRunRecord.STATUS_SUCCESS)
    assert record.is_finished_by_day

    apply_options(context, extra_task=LostVoidTaskEnum.WEEKLY_PLAN_TIMES.value.value,
                  daily_plan_times=9999, weekly_plan_times=9999, mission_name='特遣调查')
    app = run.get_application('lost_void', 1)
    app._after_round_wait = lambda **_kwargs: None
    record.check_and_update_status()
    assert not record.is_finished_by_day
    assert record.run_status_under_now == AppRunRecord.STATUS_WAIT
    assert app.init_for_lost_void().status == app.STATUS_AGAIN
    context.lost_void.init_before_run.assert_called_once()
    # 周计划在满悬赏情况下仍继续，且不需要悬赏截图或 OCR。
    assert app.check_bounty_commission_before().status == app.STATUS_AGAIN
    assert record.bounty_commission_complete  # 保留原始奖励记录。


def test_raising_completed_weekly_target_takes_effect_without_restart(context):
    run = context.run_context
    apply_options(context, extra_task=LostVoidTaskEnum.WEEKLY_PLAN_TIMES.value.value,
                  daily_plan_times=5, weekly_plan_times=2)
    record = run.get_run_record('lost_void', 1)
    record.daily_run_times = record.weekly_run_times = 2
    assert record.is_finished_by_day
    apply_options(context, weekly_plan_times=9999)
    assert not record.is_finished_by_day
    # 每日和每周上限仍然有效；提高其中一个不会绕过另一个。
    record.daily_run_times = 5
    assert record.is_finished_by_day
    apply_options(context, daily_plan_times=9999)
    assert not record.is_finished_by_day
    record.weekly_run_times = 9999
    assert record.is_finished_by_day


def test_factory_cache_refresh_is_visible_to_context(context):
    run = context.run_context
    factory = run.get_factory('lost_void')
    old_record = run.get_run_record('lost_void', 1)
    old_config = run.get_config('lost_void', 1)
    factory.clear_cache()
    new_record = run.get_run_record('lost_void', 1)
    new_config = run.get_config('lost_void', 1)
    assert new_config is not old_config and new_record is not old_record
    assert new_record.config is new_config
