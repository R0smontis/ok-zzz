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


@pytest.mark.parametrize('enabled', [False, True])
def test_no_burnout_event_allows_only_normal_plan(monkeypatch, enabled):
    rows = [('挑战奖励', 806, 699), ('挑战等级', 1490, 50), ('下一步', 1734, 1027)]
    op = reward_op('expert-no-burnout', rows)
    pressed = Mock()
    monkeypatch.setattr(menus, 'pad_press', pressed)
    result = menus.verified_reward_mode(op, op.last_screenshot, enabled)
    assert result.is_fail if enabled else result.is_success
    if enabled:
        assert result.status == menus.NO_DOUBLE_REWARD
    pressed.assert_not_called()


@pytest.mark.parametrize('missing', ['挑战奖励', '挑战等级', '下一步'])
def test_no_burnout_requires_loaded_entry(monkeypatch, missing):
    rows = [(text, x, y) for text, x, y in
            [('挑战奖励', 806, 699), ('挑战等级', 1490, 50), ('下一步', 1734, 1027)]
            if text != missing]
    op = reward_op('expert-no-burnout', rows)
    monkeypatch.setattr(menus, 'pad_press', Mock())
    assert menus.verified_reward_mode(op, op.last_screenshot, False).result == OperationRoundResultEnum.RETRY


def test_visible_burnout_control_with_failed_ocr_is_not_absent(monkeypatch):
    op = reward_op('expert-burnout-on',
                   [('挑战奖励', 806, 699), ('挑战等级', 1490, 50), ('下一步', 1734, 1027)])
    pressed = Mock()
    monkeypatch.setattr(menus, 'pad_press', pressed)
    assert menus.verified_reward_mode(op, op.last_screenshot, False).result == OperationRoundResultEnum.RETRY
    pressed.assert_not_called()


@pytest.mark.parametrize('policy,expected', [('停止', False), ('等体力单倍', True), ('等次数单倍', True)])
def test_expert_falls_back_only_after_verified_absent_control(monkeypatch, policy, expected):
    rows = [('挑战奖励', 806, 699), ('挑战等级', 1490, 50), ('下一步', 1734, 1027)]
    op = reward_op('expert-no-burnout', rows)
    op.plan = ChargePlanItem(category_name='专业挑战室', double_times=2, single_times=0,
                             double_fallback=policy)
    pressed = Mock()
    monkeypatch.setattr(menus, 'pad_press', pressed)
    result = op.close_burnout_mode()
    assert result.is_success == expected
    assert op.plan.use_double_reward != expected
    assert op.plan.run_times == 0
    pressed.assert_not_called()


def test_missing_burnout_ocr_does_not_enable_fallback(monkeypatch):
    op = reward_op('expert-burnout-on', [])
    op.plan = ChargePlanItem(category_name='专业挑战室', double_times=2, single_times=0,
                             double_fallback='等次数单倍')
    monkeypatch.setattr(menus, 'pad_press', Mock())
    assert op.close_burnout_mode().result == OperationRoundResultEnum.RETRY
    assert op.plan.use_double_reward


def world_cleanup(monkeypatch):
    cleanup = Mock()
    cleanup.execute.return_value = OperationResult(True, '大世界-普通')
    monkeypatch.setattr('zzz_od.application.charge_plan.charge_plan_app.BackToNormalWorld', lambda ctx: cleanup)


def started(app):
    app.run_record = SimpleNamespace(get_current_dt=lambda: '20261017')
    app.start_charge_plan()
    return app


def finish(app, previous):
    app._init_network()
    app._current_node = app._node_map['返回大世界']
    app._previous_round_result = previous
    return app.back_to_world()


def test_finished_plans_without_any_reset_say_nothing_was_run(monkeypatch):
    world_cleanup(monkeypatch)
    plan = ChargePlanItem(plan_times=1, run_times=1)
    app = plan_app([plan], loop=False)
    app.config.data['reset_plan_times_each_run'] = False
    app = started(app)
    app.battery_charge = 320
    found = app.find_next_plan()
    assert found.status == app.STATUS_ROUND_FINISHED
    result = finish(app, found)
    assert result.is_success
    assert result.status == '计划已全部完成（未开启每次执行重置、每日重置和循环），本次未刷本；剩余电量 320'


def test_by_default_every_run_starts_the_whole_plan_again():
    # User request 2026-10-17: each execution runs the full plan list once.
    done = ChargePlanItem(mission_type_name='音擎改装', plan_times=1, run_times=1)
    half = ChargePlanItem(mission_type_name='基础材料', plan_times=3, run_times=2)
    app = started(plan_app([done, half], loop=False))
    assert (done.run_times, half.run_times) == (0, 0)
    app.config.save.assert_called()
    found = app.find_next_plan()
    assert found.is_success and app.current_plan is done


def test_default_does_not_loop_after_the_whole_plan():
    from zzz_od.application.charge_plan.charge_plan_config import ChargePlanConfig
    config = object.__new__(ChargePlanConfig)
    config.data = {}
    assert config.reset_plan_times_each_run and not config.loop and not config.daily_reset_plan_times


def test_turning_the_per_run_reset_off_keeps_counts_and_daily_reset_applies():
    plan = ChargePlanItem(plan_times=2, run_times=1)
    app = plan_app([plan], loop=False)
    app.config.data.update(reset_plan_times_each_run=False, daily_reset_plan_times=True,
                           last_daily_reset_dt='20261017')
    started(app)
    assert plan.run_times == 1  # Same game day: nothing to reset.
    app.config.data['last_daily_reset_dt'] = '20261016'
    started(app)
    assert plan.run_times == 0


def test_low_charge_names_the_plan_and_requirement(monkeypatch):
    world_cleanup(monkeypatch)
    plan = ChargePlanItem(category_name='实战模拟室', mission_type_name='音擎改装', plan_times=1)
    app = started(plan_app([plan]))
    app.battery_charge = 10
    app.current_plan = plan
    app.config.data['restore_charge'] = '不使用'
    checked = app.check_before_transport()
    assert checked.status == app.STATUS_ROUND_FINISHED
    assert finish(app, checked).status == '电量不足：实战模拟室 音擎改装需要 20，本次未刷本；剩余电量 10'


def test_completed_challenge_keeps_plain_charge_status(monkeypatch):
    world_cleanup(monkeypatch)
    plan = ChargePlanItem(plan_times=1, run_times=1)
    app = started(plan_app([plan], loop=False))
    app.battery_charge = 220
    app._init_network()
    app._current_node = app._node_map['挑战完成']
    app._previous_round_result = app.round_success('战斗结果-完成')
    assert app.challenge_complete().is_success
    found = app.find_next_plan()
    assert finish(app, found).status == '剩余电量 220'


def test_charge_found_short_inside_the_mission_is_named(monkeypatch):
    # The pre-check estimates 20 for 实战模拟室 默认数量, but one run took 100 live (320 → 220).
    from zzz_od.operation.compendium.combat_simulation import CombatSimulation
    world_cleanup(monkeypatch)
    plan = ChargePlanItem(category_name='实战模拟室', mission_type_name='音擎改装', plan_times=1)
    app = started(plan_app([plan]))
    app.battery_charge = 60
    app.current_plan = plan
    app._init_network()
    app._current_node = app._node_map['实战模拟室']
    app._previous_round_result = app.round_success(CombatSimulation.STATUS_CHARGE_NOT_ENOUGH)
    ended = app.skip_plan_or_finish()
    assert ended.status == app.STATUS_ROUND_FINISHED
    assert finish(app, ended).status == '实战模拟室 音擎改装：电量不足，本次未刷本；剩余电量 60'


def test_report_failure_explains_unverified_burnout_toggle(monkeypatch):
    # Report 2026-10-22: 「未核验燃竭模式及ON/OFF文字，未操作」 was shown verbatim.
    world_cleanup(monkeypatch)
    plan = ChargePlanItem(category_name='专业挑战室', mission_type_name='「征服者」')
    app = started(plan_app([plan]))
    app.current_plan = plan
    app._init_network()
    app._current_node = app._node_map['挑战完成']
    app._previous_round_result = app.round_retry('未核验燃竭模式及ON/OFF文字，未操作')
    failure = app.challenge_complete()
    assert failure.status.startswith('专业挑战室 「征服者」失败：未能识别燃竭模式开关，未进入副本')
    assert finish(app, failure).is_fail


@pytest.mark.parametrize('stage,status,expected', [
    ('传送', '找不到 音擎改装', '传送到 实战模拟室 音擎改装失败：找不到 音擎改装'),
    ('打开快捷手册', '未能识别当前画面', '打开快捷手册失败：未能识别当前游戏画面'),
    ('前往大世界', '返回大世界失败：操作超时', '返回大世界失败：操作超时'),
])
def test_early_stage_failure_names_the_stage(monkeypatch, stage, status, expected):
    world_cleanup(monkeypatch)
    plan = ChargePlanItem(category_name='实战模拟室', mission_type_name='音擎改装', plan_times=1)
    app = started(plan_app([plan]))
    app.current_plan = plan
    app._init_network()
    app._current_node = app._node_map[stage]
    failed = app.round_fail(status)
    next_node = app._get_next_node(failed)
    if stage == '前往大世界':
        assert next_node is None  # Nothing opened yet: the failure itself ends the run.
        return
    assert next_node.cn == '返回大世界'
    app._previous_node = app._current_node
    app._previous_round_result = failed
    app._current_node = next_node
    result = app.back_to_world()
    assert result.is_fail and result.status == expected


def test_every_plan_skipped_for_low_charge_is_success_with_reasons(monkeypatch):
    world_cleanup(monkeypatch)
    first = ChargePlanItem(category_name='实战模拟室', mission_type_name='音擎改装', plan_times=1)
    second = ChargePlanItem(category_name='区域巡防', mission_type_name='巡防', plan_times=1)
    app = started(plan_app([first, second]))
    app.config.data.update(skip_plan=True, restore_charge='不使用')
    app.battery_charge = 10
    for _ in range(2):
        assert app.find_next_plan().is_success
        assert app.check_before_transport().status == app.STATUS_FIND_NEXT_PLAN
    ended = app.find_next_plan()
    assert ended.is_success and ended.status == app.STATUS_ROUND_FINISHED
    result = finish(app, ended)
    assert result.is_success
    assert '电量不足：实战模拟室 音擎改装需要 20，已跳过' in result.status
    assert '电量不足：区域巡防 巡防需要 ' in result.status and result.status.endswith('本次未刷本；剩余电量 10')
    assert app.result_notice == result.status


def test_low_charge_after_some_runs_is_still_reported(monkeypatch):
    from zzz_od.operation.compendium.combat_simulation import CombatSimulation
    world_cleanup(monkeypatch)
    plan = ChargePlanItem(category_name='实战模拟室', mission_type_name='音擎改装', plan_times=3)
    app = started(plan_app([plan]))
    app.current_plan = plan
    app.battery_charge = 15
    app.challenge_count = 2
    app._init_network()
    app._current_node = app._node_map['实战模拟室']
    app._previous_round_result = app.round_success(CombatSimulation.STATUS_CHARGE_NOT_ENOUGH)
    result = finish(app, app.skip_plan_or_finish())
    assert result.is_success and result.status == '实战模拟室 音擎改装：电量不足；剩余电量 15'
    assert app.result_notice == result.status
