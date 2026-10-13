import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import pytest

from onedragon.base.geometry.point import Point
from onedragon.base.operation.operation_base import OperationResult
from onedragon.base.operation.operation_round_result import OperationRoundResultEnum
from zzz_od.application.charge_plan.charge_plan_app import ChargePlanApp
from zzz_od.application.charge_plan.charge_plan_config import ChargePlanItem
from zzz_od.operation.compendium.expert_challenge import ExpertChallenge
from src.navigation import menus
from test_charge_plan_empty_targets import operation, plan_app


@pytest.mark.parametrize('cleanup_success', [True, False])
def test_failed_challenge_survives_world_cleanup_without_counting_or_skipping(monkeypatch, cleanup_success):
    plan = ChargePlanItem(category_name='专业挑战室', mission_type_name='「征服者」')
    app = plan_app([plan])
    app._init_network()
    app._current_node = app._node_map['挑战完成']
    app._previous_round_result = app.round_fail('燃竭模式切换未生效')
    failure = app.challenge_complete()
    assert failure.is_fail and '燃竭模式切换未生效' in failure.status
    assert plan.run_times == 0 and not plan.skipped
    assert app._get_next_node(failure).cn == '返回大世界'
    app._previous_round_result = failure
    app._current_node = app._node_map['返回大世界']
    cleanup = Mock()
    cleanup.execute.return_value = OperationResult(cleanup_success, '大世界-普通' if cleanup_success else '返回超时')
    monkeypatch.setattr('zzz_od.application.charge_plan.charge_plan_app.BackToNormalWorld', lambda ctx: cleanup)
    result = app.back_to_world()
    assert result.is_fail and '燃竭模式切换未生效' in result.status
    if not cleanup_success:
        assert '返回超时' in result.status
    assert app._get_next_node(result) is None


@pytest.mark.parametrize('entered,status', [(False, '普通战斗-完成'), (True, '普通战斗-撤退'), (False, None)])
def test_expert_unverified_battle_never_counts_completion(entered, status):
    op = operation(ExpertChallenge)
    op.plan = ChargePlanItem()
    op.config = SimpleNamespace(add_plan_run_times=Mock())
    op.battle_entered = entered
    op._previous_round_result = op.round_success(status)
    assert op.after_battle().is_fail
    op.config.add_plan_run_times.assert_not_called()


def test_verified_victory_counts_once_and_retreat_routes_to_failure(monkeypatch):
    op = operation(ExpertChallenge)
    op.plan = ChargePlanItem()
    op.config = SimpleNamespace(add_plan_run_times=Mock())
    op.battle_entered = True
    op._previous_round_result = op.round_success('普通战斗-完成')
    assert op.after_battle().is_success
    assert op.after_battle().is_fail
    op.config.add_plan_run_times.assert_called_once_with(op.plan)
    op._init_network()
    op._current_node = op._node_map['自动战斗']
    assert op._get_next_node(op.round_success('普通战斗-撤退')).cn == '战斗失败'
    op.ctx.controller.background_mode = True
    monkeypatch.setattr(menus, 'press_labelled', lambda *args: 'b')
    assert op.battle_fail().is_fail


def reward_op(filename, rows):
    op = operation(ExpertChallenge)
    op.ctx.controller.background_mode = True
    path = Path(__file__).parent / 'fixtures' / 'daily_map' / (filename + '.png')
    op.last_screenshot = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
    # Human-labelled visible OCR targets on the preserved real controller frames.
    op.ctx.ocr_service = SimpleNamespace(get_ocr_result_list=lambda **kwargs: [
        SimpleNamespace(data=text, center=Point(x, y)) for text, x, y in rows
    ])
    return op


def labelled_rows(name):
    path = Path(__file__).parent / 'fixtures' / 'daily_map' / (name + '.json')
    labels = json.loads(path.read_text(encoding='utf-8'))['labels']
    return [(item['text'], *item['center']) for item in labels]


ON_ROWS = labelled_rows('expert-burnout-on')
OFF_ROWS = labelled_rows('expert-burnout-off')
CONFIRM_ROWS = labelled_rows('expert-burnout-confirm')


def test_burnout_off_requires_focused_confirmation_and_observed_off(monkeypatch):
    pressed = []
    monkeypatch.setattr(menus, 'pad_press', lambda op, button: pressed.append(button))
    op = reward_op('expert-burnout-on', ON_ROWS)
    assert menus.verified_reward_mode(op, op.last_screenshot, False).result == OperationRoundResultEnum.RETRY
    assert pressed == ['r_thumb']
    confirm = reward_op('expert-burnout-confirm', CONFIRM_ROWS)
    confirm._reward_mode_requests = op._reward_mode_requests
    assert menus.verified_reward_mode(confirm, confirm.last_screenshot, False).result == OperationRoundResultEnum.RETRY
    assert pressed == ['r_thumb', 'a']
    off = reward_op('expert-burnout-off', OFF_ROWS)
    assert menus.verified_reward_mode(off, off.last_screenshot, False).is_success
    assert pressed == ['r_thumb', 'a']


def test_burnout_enable_waits_for_observed_on(monkeypatch):
    pressed = []
    monkeypatch.setattr(menus, 'pad_press', lambda op, button: pressed.append(button))
    op = reward_op('expert-burnout-off', OFF_ROWS)
    assert menus.verified_reward_mode(op, op.last_screenshot, True).result == OperationRoundResultEnum.RETRY
    assert pressed == ['r_thumb']
    on = reward_op('expert-burnout-on', ON_ROWS)
    assert menus.verified_reward_mode(on, on.last_screenshot, True).is_success
    assert pressed == ['r_thumb']


@pytest.mark.parametrize('rows', [[], ON_ROWS[:1], [ON_ROWS[0], ON_ROWS[2]]])
def test_unverified_burnout_control_never_sends_input(monkeypatch, rows):
    pressed = Mock()
    monkeypatch.setattr(menus, 'pad_press', pressed)
    op = reward_op('expert-burnout-on', rows)
    assert menus.verified_reward_mode(op, op.last_screenshot, False).result == OperationRoundResultEnum.RETRY
    pressed.assert_not_called()


def test_unfocused_confirmation_never_sends_a(monkeypatch):
    pressed = Mock()
    monkeypatch.setattr(menus, 'pad_press', pressed)
    op = reward_op('expert-burnout-confirm', CONFIRM_ROWS)
    op.last_screenshot[:] = 0
    assert menus.verified_reward_mode(op, op.last_screenshot, False).result == OperationRoundResultEnum.RETRY
    pressed.assert_not_called()


def test_burnout_changes_stop_at_bounded_attempts(monkeypatch):
    pressed = Mock()
    monkeypatch.setattr(menus, 'pad_press', pressed)
    op = reward_op('expert-burnout-on', ON_ROWS)
    op._reward_mode_requests = 4
    assert menus.verified_reward_mode(op, op.last_screenshot, False).is_fail
    pressed.assert_not_called()
