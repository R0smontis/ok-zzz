from unittest.mock import Mock

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
