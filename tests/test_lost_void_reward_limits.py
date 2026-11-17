"""周期奖励模式以悬赏满额为终点，次数仅统计；其他目标保留计划次数约束。"""
from types import SimpleNamespace

import pytest

from onedragon.base.operation.application_run_record import AppRunRecord
from zzz_od.application.hollow_zero.lost_void.lost_void_config import LostVoidTaskEnum
from zzz_od.application.hollow_zero.lost_void.lost_void_run_record import LostVoidRunRecord


def record(mode, daily, weekly, complete=False):
    config = SimpleNamespace(extra_task=mode, daily_plan_times=5, weekly_plan_times=2,
                             is_bounty_commission_mode=mode in (
                                 LostVoidTaskEnum.BOUNTY_COMMISSION.value.value,
                                 LostVoidTaskEnum.PERIOD_REWARD.value.value),
                             mission_name='矩阵行动')
    result = LostVoidRunRecord(config, instance_idx=98)
    result.data.update(daily_run_times=daily, weekly_run_times=weekly, period_reward_complete=complete,
                       bounty_commission_complete=complete, eval_point_complete=False)
    result.dt = result.get_current_dt()
    return result


@pytest.mark.parametrize('daily,weekly', [(0, 0), (5, 5), (50, 100)])
@pytest.mark.parametrize('complete', [False, True])
def test_period_reward_completion_is_independent_of_run_counts(daily, weekly, complete):
    value = record(LostVoidTaskEnum.PERIOD_REWARD.value.value, daily, weekly, complete)
    assert value.is_finished_by_day is complete
    assert value.is_finished_by_week is complete
    assert value.run_status_under_now == (AppRunRecord.STATUS_SUCCESS if complete else AppRunRecord.STATUS_WAIT)


@pytest.mark.parametrize('mode', [LostVoidTaskEnum.EVAL_POINT.value.value,
                                  LostVoidTaskEnum.WEEKLY_PLAN_TIMES.value.value,
                                  LostVoidTaskEnum.BOUNTY_COMMISSION.value.value])
def test_other_targets_keep_daily_cap(mode):
    value = record(mode, 5, 1)
    assert value.is_finished_by_day
    assert not value.is_finished_by_week


@pytest.mark.parametrize('mode', [LostVoidTaskEnum.BOUNTY_COMMISSION.value.value,
                                  LostVoidTaskEnum.PERIOD_REWARD.value.value])
def test_reward_completion_flag_still_requires_entry_verification(mode):
    value = record(mode, 0, 0, complete=True)
    assert value.is_finished_by_day
    assert value.is_reward_verification_pending
    assert not value.should_skip_start
    assert not value.is_done


def test_bounty_verification_still_respects_daily_limit():
    value = record(LostVoidTaskEnum.BOUNTY_COMMISSION.value.value, 5, 1, complete=True)
    assert value.should_skip_start
    assert value.is_done


def test_period_reward_ignores_counts_even_when_complete():
    value = record(LostVoidTaskEnum.PERIOD_REWARD.value.value, 50, 100, complete=True)
    assert not value.should_skip_start
    assert not value.is_done


def test_count_mode_still_skips_when_weekly_target_reached():
    value = record(LostVoidTaskEnum.WEEKLY_PLAN_TIMES.value.value, 0, 2)
    assert value.is_finished_by_week
    assert value.should_skip_start
