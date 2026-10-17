from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from onedragon.base.geometry.rectangle import Rect
from onedragon.base.operation.operation_round_result import OperationRoundResultEnum
from zzz_od.application.charge_plan.charge_plan_app import ChargePlanApp
from zzz_od.application.charge_plan.charge_plan_config import ChargePlanConfig, ChargePlanItem
from zzz_od.operation.compendium.compendium_choose_mission_type import CompendiumChooseMissionType
from zzz_od.operation.compendium.combat_simulation import CombatSimulation


def operation(cls):
    op = object.__new__(cls)
    op.last_screenshot = np.zeros((1080, 1920, 3), np.uint8)
    op._after_round_wait = lambda **kwargs: None
    op.ctx = SimpleNamespace(
        controller=SimpleNamespace(background_mode=False, drag_to=Mock(), click=Mock()),
        ocr=SimpleNamespace(crop_and_run_ocr=Mock()),
        screen_loader=SimpleNamespace(get_area=lambda *args: SimpleNamespace(
            rect=Rect(498, 334, 1646, 894), left_top=Rect(498, 334, 1646, 894).left_top,
            center=Rect(498, 334, 1646, 894).center)),
    )
    op.need_check_game_win = False
    op._node_map = {}
    op._node_edges_map = {}
    op.op_to_enter_game = None
    op._previous_node = None
    op._previous_round_result = None
    op._current_node = None
    return op


@pytest.fixture
def agent_picker(monkeypatch):
    monkeypatch.setattr(
        'zzz_od.operation.compendium.compendium_choose_mission_type.cv2_utils.find_character_avatar_center_with_offset',
        lambda *args, **kwargs: None,
    )
    op = operation(CompendiumChooseMissionType)
    op.mission_type = SimpleNamespace(is_agent_plan=True, mission_type_name='代理人方案培养',
        category=SimpleNamespace(category_name='实战模拟室', tab=SimpleNamespace(tab_name='训练')))
    return op


@pytest.mark.parametrize('message', ['暂无特训目标', '暂无培养目标', '暂无目标', '未设置特训目标'])
def test_explicit_empty_target_finishes_without_scroll_or_transport(agent_picker, message):
    agent_picker.ctx.ocr.crop_and_run_ocr.return_value = {message: None}
    result = agent_picker.choose_mission_type_by_agent()
    assert result.is_success and result.status == CompendiumChooseMissionType.STATUS_NO_AGENT_TARGETS
    agent_picker.ctx.controller.drag_to.assert_not_called()
    agent_picker.ctx.controller.click.assert_not_called()

    agent_picker._init_network()
    agent_picker._current_node = agent_picker._node_map['选择代理人方案']
    next_node = agent_picker._get_next_node(result)
    assert next_node.cn == '无特训目标'
    terminal_result = next_node.op_method(agent_picker)
    agent_picker._current_node = next_node
    assert terminal_result.status == CompendiumChooseMissionType.STATUS_NO_AGENT_TARGETS
    assert agent_picker._get_next_node(terminal_result) is None

@pytest.mark.parametrize('words', [{}, {'特训目标': None}, {'基础材料': None}, {'暂无奖励': None}])
def test_missing_avatar_without_empty_message_remains_recognition_retry(agent_picker, words):
    agent_picker.ctx.ocr.crop_and_run_ocr.return_value = words
    result = agent_picker.choose_mission_type_by_agent()
    assert result.result == OperationRoundResultEnum.RETRY
    assert result.status == '找不到 代理人方案培养'
    agent_picker.ctx.controller.drag_to.assert_called_once()


def test_ocr_error_is_not_misreported_as_empty_target(agent_picker):
    agent_picker.ctx.ocr.crop_and_run_ocr.side_effect = RuntimeError('OCR failed')
    with pytest.raises(RuntimeError, match='OCR failed'):
        agent_picker.choose_mission_type_by_agent()


def test_empty_targets_after_entry_skip_without_clicking_cards(monkeypatch):
    monkeypatch.setattr(
        'zzz_od.operation.compendium.combat_simulation.cv2_utils.find_character_avatar_center_with_offset',
        lambda *args, **kwargs: None,
    )
    op = operation(CombatSimulation)
    op.plan = ChargePlanItem(mission_type_name='代理人方案培养', mission_name='代理人方案培养')
    op.scroll_count = 0
    op.ctx.ocr.crop_and_run_ocr.return_value = {'暂无特训目标': None}
    result = op.choose_mission()
    assert result.is_success and result.status == CompendiumChooseMissionType.STATUS_NO_AGENT_TARGETS
    op.ctx.controller.click.assert_not_called()
    op.ctx.controller.drag_to.assert_not_called()


def plan_app(plans, loop=True):
    app = operation(ChargePlanApp)
    config = object.__new__(ChargePlanConfig)
    config.data = {'loop': loop, 'skip_plan': False}
    config.plan_list = plans
    config.save = Mock()
    app.config = config
    app.temp_plan = None
    app.last_tried_plan = None
    app.current_plan = plans[0] if plans else None
    app._previous_node = None
    app._previous_round_result = app.round_success(CompendiumChooseMissionType.STATUS_NO_AGENT_TARGETS)
    return app


def test_empty_game_target_skips_only_target_plan_and_continues_material_plan():
    agent = ChargePlanItem(mission_type_name='代理人方案培养')
    material = ChargePlanItem(mission_type_name='基础材料', mission_name='调查专项')
    app = plan_app([agent, material])
    result = app.skip_plan_or_finish()
    assert result.is_success and result.status == app.STATUS_FIND_NEXT_PLAN
    assert agent.skipped and agent.run_times == 0
    result = app.find_next_plan()
    assert result.is_success and result.status is None
    assert app.current_plan is material and not material.skipped


@pytest.mark.parametrize('loop', [True, False])
def test_only_empty_target_plan_ends_successfully_even_in_loop_mode(loop):
    agent = ChargePlanItem(mission_type_name='代理人方案培养')
    app = plan_app([agent], loop=loop)
    app.skip_plan_or_finish()
    result = app.find_next_plan()
    assert result.is_success and result.status == app.STATUS_ROUND_FINISHED
    assert agent.skipped and agent.run_times == 0


@pytest.mark.parametrize('loop', [True, False])
def test_empty_user_plan_list_fails_instead_of_reporting_success(loop):
    # Live 2026-10-17: an empty plan list read 320 charge, ran nothing and was reported as success.
    app = plan_app([], loop=loop)
    result = app.find_next_plan()
    assert result.is_fail and result.status == app.STATUS_EMPTY_PLAN
    app._init_network()
    app._current_node = app._node_map['查找候选计划']
    assert app._get_next_node(result).cn == '返回大世界'


def test_material_transport_does_not_read_agent_targets(agent_picker):
    agent_picker.mission_type.is_agent_plan = False
    agent_picker.mission_type.mission_type_name = '基础材料'
    agent_picker.ctx.compendium_service = SimpleNamespace(get_same_category_mission_type_list=lambda name: [
        SimpleNamespace(mission_type_name='基础材料', alias_list=[])])
    agent_picker.ctx.ocr.crop_and_run_ocr.return_value = {'暂无特训目标': SimpleNamespace(max=None)}
    result = agent_picker.choose_mission_type()
    assert result.result == OperationRoundResultEnum.RETRY
    assert result.status == '找不到 基础材料'
    agent_picker.ctx.controller.drag_to.assert_called_once()


def test_empty_target_transport_routes_to_skip_but_other_failures_do_not():
    app = plan_app([ChargePlanItem(mission_type_name='代理人方案培养')])
    app._init_network()
    app._current_node = app._node_map['传送']
    empty_result = app.round_success(CompendiumChooseMissionType.STATUS_NO_AGENT_TARGETS)
    next_node = app._get_next_node(empty_result)
    assert next_node.cn == '跳过或结束计划'
    app._previous_round_result = empty_result
    assert next_node.op_method(app).status == app.STATUS_FIND_NEXT_PLAN
    # A missing avatar is a recognition failure, not evidence of an empty game list.
    assert app._get_next_node(app.round_fail('找不到 代理人方案培养')) is None
    assert app._get_next_node(app.round_fail('异常')) is None
