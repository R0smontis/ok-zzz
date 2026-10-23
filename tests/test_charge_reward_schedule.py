from unittest.mock import Mock

import pytest

from zzz_od.application.charge_plan.charge_plan_config import ChargePlanItem
from zzz_od.operation.compendium.expert_challenge import ExpertChallenge
from test_charge_plan_empty_targets import operation, plan_app


def test_old_plan_preserves_single_count_and_identity():
    plan = ChargePlanItem.from_dict({'plan_times': 8, 'run_times': 3, 'plan_id': 'existing'})
    restored = ChargePlanItem.from_dict(plan.to_dict())
    assert (restored.single_times, restored.plan_times, restored.run_times, restored.plan_id) == (8, 8, 3, 'existing')
    assert not restored.use_double_reward


def test_double_then_single_and_loop_reset_have_correct_cost():
    plan = ChargePlanItem(category_name='专业挑战室', double_times=2, single_times=3)
    app = plan_app([plan])
    costs = []
    for _ in range(5):
        costs.append(plan.estimated_charge_power)
        app.config.add_plan_run_times(plan)
    assert costs == [80, 80, 40, 40, 40]
    assert app.config.get_next_plan() is None
    app.config.reset_plans()
    assert plan.run_times == 0 and plan.use_double_reward
    assert app.config.get_next_plan() is plan


def test_mode_boundary_exits_before_reentering_in_single_mode(monkeypatch):
    plan = ChargePlanItem(category_name='专业挑战室', double_times=2, single_times=3, run_times=2)
    op = operation(ExpertChallenge)
    op.plan = plan
    decisions = []
    chooser = Mock()
    chooser.execute.return_value = None
    op.round_by_op_result = lambda result: result
    def choose(ctx, again, **kwargs):
        decisions.append(again)
        return chooser
    monkeypatch.setattr('zzz_od.operation.compendium.expert_challenge.ChooseNextOrFinishAfterBattle', choose)
    op.check_next()
    plan.run_times = 3
    op.check_next()
    assert decisions == [False, True]


@pytest.mark.parametrize(
    ('fallback', 'expected_progress'),
    [
        ('等体力单倍', [(0, 1), (1, 0), (1, 1), (2, 0), (3, 0)]),
        ('等次数单倍', [(1, 0), (2, 0), (3, 0)]),
    ],
)
def test_double_fallback_runs_real_schedule_at_single_cost(fallback, expected_progress):
    plan = ChargePlanItem(
        category_name='专业挑战室', double_times=2, single_times=1,
        double_fallback=fallback,
    )
    app = plan_app([plan])
    assert plan.enable_double_fallback()
    costs = []
    for progress in expected_progress:
        assert app.config.get_next_plan() is plan
        assert not app.config.all_plan_finished()
        assert not plan.use_double_reward
        costs.append(plan.estimated_charge_power)
        app.config.add_plan_run_times(plan)
        assert (plan.run_times, plan.fallback_single_runs) == progress
        assert (plan.double_times, plan.single_times, plan.plan_times) == (2, 1, 3)
    assert costs == [40] * len(expected_progress)
    assert app.config.get_next_plan() is None
    assert app.config.all_plan_finished()
    assert app.config.save.call_count == len(expected_progress)


@pytest.mark.parametrize(
    ('fallback', 'expected_remaining_progress'),
    [
        ('等体力单倍', [(1, 1), (2, 0), (3, 0)]),
        ('等次数单倍', [(2, 0), (3, 0)]),
    ],
)
def test_fallback_only_converts_unfinished_double_runs(fallback, expected_remaining_progress):
    plan = ChargePlanItem(
        category_name='专业挑战室', double_times=2, single_times=1,
        double_fallback=fallback,
    )
    app = plan_app([plan])
    assert plan.estimated_charge_power == 80
    app.config.add_plan_run_times(plan)
    assert plan.run_times == 1
    assert plan.enable_double_fallback()
    for progress in expected_remaining_progress:
        assert app.config.get_next_plan() is plan
        assert plan.estimated_charge_power == 40
        app.config.add_plan_run_times(plan)
        assert (plan.run_times, plan.fallback_single_runs) == progress
    assert app.config.all_plan_finished()
    assert (plan.double_times, plan.single_times) == (2, 1)


def test_half_double_progress_survives_save_and_fallback_reentry():
    plan = ChargePlanItem(
        category_name='专业挑战室', double_times=2, single_times=1,
        double_fallback='等体力单倍',
    )
    app = plan_app([plan])
    assert plan.enable_double_fallback()
    app.config.add_plan_run_times(plan)
    saved = plan.to_dict()
    assert saved['fallback_single_runs'] == 1
    assert saved['double_fallback'] == '等体力单倍'
    assert '_double_unavailable' not in saved
    restored = ChargePlanItem.from_dict(saved)
    assert restored.plan_id == plan.plan_id
    assert not restored.use_double_reward
    assert restored.enable_double_fallback()
    app = plan_app([restored])
    for progress in [(1, 0), (1, 1), (2, 0), (3, 0)]:
        assert app.config.get_next_plan() is restored
        assert restored.estimated_charge_power == 40
        app.config.add_plan_run_times(restored)
        assert (restored.run_times, restored.fallback_single_runs) == progress
    assert app.config.all_plan_finished()


def test_half_double_progress_does_not_finish_or_reset_loop_early():
    plan = ChargePlanItem(
        category_name='专业挑战室', double_times=1, single_times=0,
        double_fallback='等体力单倍',
    )
    app = plan_app([plan], loop=True)
    assert plan.enable_double_fallback()
    app.config.add_plan_run_times(plan)
    app.config.reset_plans()
    assert (plan.run_times, plan.fallback_single_runs) == (0, 1)
    assert not plan.use_double_reward
    assert not app.config.all_plan_finished()
    assert app.config.get_next_plan() is plan
    app.config.add_plan_run_times(plan)
    assert app.config.all_plan_finished()
    app.config.reset_plans()
    assert (plan.run_times, plan.fallback_single_runs) == (0, 0)
    assert plan.use_double_reward
    assert app.config.get_next_plan() is plan


def test_reset_for_run_clears_half_progress_even_without_a_completed_run():
    plan = ChargePlanItem(
        category_name='专业挑战室', double_times=2, single_times=1,
        double_fallback='等体力单倍',
    )
    app = plan_app([plan])
    assert plan.enable_double_fallback()
    app.config.add_plan_run_times(plan)
    assert plan.run_times == 0
    app.config.save.reset_mock()
    assert app.config.reset_plan_times_for_run()
    assert (plan.run_times, plan.fallback_single_runs) == (0, 0)
    assert plan.use_double_reward
    assert plan.double_fallback == '等体力单倍'
    app.config.save.assert_called_once()


def test_loop_reset_rejects_inconsistent_completed_half_progress():
    with pytest.raises(ValueError, match='进度与双倍计划不一致'):
        ChargePlanItem(category_name='专业挑战室', double_times=2, single_times=1,
                       double_fallback='等体力单倍', run_times=3, fallback_single_runs=1)


def test_default_stop_policy_keeps_double_mode_and_progress_unchanged():
    plan = ChargePlanItem(category_name='专业挑战室', double_times=2, single_times=1)
    assert plan.double_fallback == '停止'
    assert not plan.enable_double_fallback()
    assert plan.use_double_reward
    assert plan.estimated_charge_power == 80
    assert (plan.run_times, plan.fallback_single_runs) == (0, 0)


@pytest.mark.parametrize('fallback', ['等体力单倍', '等次数单倍'])
def test_fallback_does_not_activate_after_double_stage(fallback):
    plan = ChargePlanItem(
        category_name='专业挑战室', double_times=2, single_times=1,
        run_times=2, double_fallback=fallback,
    )
    assert not plan.enable_double_fallback()
    plan.record_completed_run()
    assert (plan.run_times, plan.fallback_single_runs) == (3, 0)


@pytest.mark.parametrize(
    ('fallback', 'expected_progress'),
    [('等体力单倍', (0, 1)), ('等次数单倍', (1, 0))],
)
def test_verified_victory_counts_once_in_fallback_mode(fallback, expected_progress):
    plan = ChargePlanItem(
        category_name='专业挑战室', double_times=2, single_times=1,
        double_fallback=fallback,
    )
    assert plan.enable_double_fallback()
    app = plan_app([plan])
    op = operation(ExpertChallenge)
    op.plan = plan
    op.config = app.config
    op.battle_entered = True
    op._previous_round_result = op.round_success('普通战斗-完成')
    assert op.after_battle().is_success
    assert (plan.run_times, plan.fallback_single_runs) == expected_progress
    assert op.after_battle().is_fail
    assert (plan.run_times, plan.fallback_single_runs) == expected_progress
    app.config.save.assert_called_once()


@pytest.mark.parametrize('half_progress', [0, 1])
@pytest.mark.parametrize(
    ('entered', 'status'),
    [(False, '普通战斗-完成'), (True, '普通战斗-失败'), (True, None)],
)
def test_unverified_battle_does_not_consume_fallback_progress(entered, status, half_progress):
    plan = ChargePlanItem(
        category_name='专业挑战室', double_times=2, single_times=1,
        double_fallback='等体力单倍',
    )
    assert plan.enable_double_fallback()
    app = plan_app([plan])
    if half_progress:
        app.config.add_plan_run_times(plan)
        app.config.save.reset_mock()
    op = operation(ExpertChallenge)
    op.plan = plan
    op.config = app.config
    op.battle_entered = entered
    op._previous_round_result = op.round_success(status)
    assert op.after_battle().is_fail
    assert (plan.run_times, plan.fallback_single_runs) == (0, half_progress)
    app.config.save.assert_not_called()
