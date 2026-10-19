from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from onedragon.base.operation.operation_base import OperationResult
from onedragon.base.operation.operation_round_result import OperationRoundResultEnum
from zzz_od.application.charge_plan.charge_plan_config import ChargePlanConfig, ChargePlanItem
from zzz_od.operation.compendium.area_patrol import AreaPatrol
from zzz_od.operation.compendium.combat_simulation import CombatSimulation
from zzz_od.operation.compendium.notorious_hunt import NotoriousHunt
from test_charge_plan_empty_targets import operation


CATEGORIES = [CombatSimulation, AreaPatrol, NotoriousHunt]


def category_op(cls, use_charge_power=True):
    op = operation(cls)
    op.plan = ChargePlanItem(plan_times=2)
    config = object.__new__(ChargePlanConfig)
    config.plan_list = [op.plan]
    config.save = Mock()
    op.config = config
    op.charge_plan_config = config
    op.battle_entered = False
    op.use_charge_power = op.pursuit = use_charge_power
    op.can_run_times = 2 if not use_charge_power else -1
    op.run_record = SimpleNamespace(left_times=2)
    op.ctx.auto_battle_context = SimpleNamespace(
        last_check_end_result='普通战斗-完成', init_auto_op=Mock(), stop_auto_battle=Mock()
    )
    return op


@pytest.mark.parametrize('cls', CATEGORIES)
@pytest.mark.parametrize('entered,status', [(False, '普通战斗-完成'), (True, '普通战斗-撤退'), (True, None)])
def test_only_entered_verified_victory_counts(cls, entered, status):
    op = category_op(cls, use_charge_power=False)
    op.battle_entered = entered
    op._previous_round_result = op.round_success(status)
    assert op.after_battle().is_fail
    assert op.plan.run_times == 0
    assert (op.can_run_times, op.run_record.left_times) == (2, 2)
    op.config.save.assert_not_called()


@pytest.mark.parametrize('cls,use_charge_power', [(CombatSimulation, True), (AreaPatrol, True), (NotoriousHunt, True), (NotoriousHunt, False)])
def test_verified_victory_consumes_one_run_once(cls, use_charge_power):
    op = category_op(cls, use_charge_power)
    op.battle_entered = True
    op._previous_round_result = op.round_success('普通战斗-完成')
    assert op.after_battle().is_success
    assert op.plan.run_times == 1
    assert op.after_battle().is_fail
    assert op.plan.run_times == 1
    op.config.save.assert_called_once()
    if cls is NotoriousHunt:
        assert (op.can_run_times, op.run_record.left_times) == ((-1, 2) if use_charge_power else (1, 1))


@pytest.mark.parametrize('cls', CATEGORIES)
def test_completed_plan_does_not_overcount_late_victory(cls):
    op = category_op(cls)
    op.plan.run_times = op.plan.plan_times
    op.battle_entered = True
    op._previous_round_result = op.round_success('普通战斗-完成')
    assert op.after_battle().is_fail
    assert op.plan.run_times == 2
    op.config.save.assert_not_called()


@pytest.mark.parametrize('available,left', [(0, 2), (2, 0)])
def test_weekly_hunt_cannot_make_reward_counters_negative(available, left):
    op = category_op(NotoriousHunt, use_charge_power=False)
    op.can_run_times = available
    op.run_record.left_times = left
    op.battle_entered = True
    op._previous_round_result = op.round_success('普通战斗-完成')
    assert op.after_battle().is_fail
    assert op.plan.run_times == 0
    assert (op.can_run_times, op.run_record.left_times) == (available, left)


@pytest.mark.parametrize('cls', CATEGORIES)
def test_next_battle_requires_fresh_entry_and_end_detection(cls):
    op = category_op(cls)
    op.battle_entered = True
    assert op.init_auto_battle().is_success
    assert not op.battle_entered
    assert op.ctx.auto_battle_context.last_check_end_result is None
    op.round_by_find_area = Mock(return_value=op.round_retry('加载中'))
    assert op.wait_battle_screen().result == OperationRoundResultEnum.RETRY
    assert not op.battle_entered
    op.round_by_find_area.return_value = op.round_success('按键-普通攻击')
    assert op.wait_battle_screen().is_success
    assert op.battle_entered


@pytest.mark.parametrize('cls', CATEGORIES)
def test_retreat_routes_to_failure_not_completion(cls):
    op = category_op(cls)
    op._init_network()
    op._current_node = op._node_map['自动战斗']
    assert op._get_next_node(op.round_success('普通战斗-撤退')).cn == '战斗失败'


@pytest.mark.parametrize('cls', [CombatSimulation, AreaPatrol])
@pytest.mark.parametrize('background_mode', [True, False])
def test_retreat_is_reported_as_failure(cls, background_mode, monkeypatch):
    op = category_op(cls)
    op.ctx.controller.background_mode = background_mode
    monkeypatch.setattr('src.navigation.menus.press_labelled', lambda *args: 'b')
    op.round_by_find_and_click_area = Mock(return_value=op.round_success('战斗结果-撤退'))
    assert op.battle_fail().is_fail
    assert op.plan.run_times == 0


@pytest.mark.parametrize('success', [True, False])
def test_energy_hunt_finish_does_not_erase_weekly_reward_record(monkeypatch, success):
    op = category_op(NotoriousHunt)
    op.can_run_times = 2
    chooser = SimpleNamespace(execute=lambda: OperationResult(success, '战斗结果-完成'))
    monkeypatch.setattr('zzz_od.operation.compendium.notorious_hunt.ChooseNextOrFinishAfterBattle', lambda *args, **kwargs: chooser)
    op.check_next()
    assert op.run_record.left_times == 2


def test_energy_plan_free_run_counts_into_the_plan_and_spends_a_free_reward(monkeypatch):
    op = category_op(NotoriousHunt)
    op.pursuit = False  # The plan found free rewards left, so this run used one of them.
    op.can_run_times = 1
    op.battle_entered = True
    op._previous_round_result = op.round_success('普通战斗-完成')
    assert op.after_battle().is_success
    assert op.plan.run_times == 1 and op.charge_plan_config.save.called
    assert (op.can_run_times, op.run_record.left_times) == (0, 1)
    tried = []
    def chooser(ctx, try_next, **kwargs):
        tried.append(try_next)
        return SimpleNamespace(execute=lambda: OperationResult(True, '战斗结果-完成'))
    monkeypatch.setattr('zzz_od.operation.compendium.notorious_hunt.ChooseNextOrFinishAfterBattle', chooser)
    op.check_next()
    # Free rewards ran out with the plan unfinished: finish here, the plan's next pass uses 深度追猎.
    assert tried == [False]


def test_energy_plan_free_runs_continue_to_level_choice():
    op = category_op(NotoriousHunt)
    op._init_network()
    op._current_node = op._node_map['抉择深度追猎']
    assert op._get_next_node(op.round_success(NotoriousHunt.STATUS_WITH_LEFT_TIMES)).cn == '选择难度'
