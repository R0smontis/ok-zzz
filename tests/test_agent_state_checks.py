"""Gauge batching retains ordered values, clear signals and error isolation."""
import numpy as np
import pytest

from zzz_od.auto_battle.auto_battle_agent_context import AutoBattleAgentContext, CheckAgentState
from zzz_od.game_data.agent import AgentStateCheckWay, AgentStateDef, CommonAgentStateEnum


def test_state_checks_keep_values_clear_signals_and_omit_untriggered_states(ctx):
    agent = AutoBattleAgentContext(ctx)
    screen = np.full((1080, 1920, 3), 255, np.uint8)
    cleared = AgentStateDef('测试-冷却', AgentStateCheckWay.COLOR_RANGE_EXIST,
                            'energy_3_1', lower_color=(0, 0, 0), upper_color=(0, 0, 0),
                            min_value_trigger_state=0, clear_on_zero=True)
    checks = [CommonAgentStateEnum.ENERGY_31.value, cleared,
              CommonAgentStateEnum.LIFE_DEDUCTION_31.value, CommonAgentStateEnum.ENERGY_32.value]

    records = agent._check_agent_states(screen, 123., [CheckAgentState(state) for state in checks])

    assert [(record.state_name, record.value, record.is_clear, record.trigger_time) for record in records] == [
        ('前台-能量', 120, False, 123.),
        ('测试-冷却', None, True, 123.),
        ('后台-1-能量', 120, False, 123.),
    ]


def test_bad_state_does_not_drop_other_gauge_results(ctx):
    agent = AutoBattleAgentContext(ctx)
    screen = np.full((1080, 1920, 3), 255, np.uint8)
    # This malformed definition removes every pixel before measuring length.
    broken = AgentStateDef('测试-无效', AgentStateCheckWay.FOREGROUND_GRAY_RANGE_LENGTH,
                           'energy_3_1', lower_color=0, upper_color=255,
                           split_color_range=[0, 255])
    checks = [CommonAgentStateEnum.ENERGY_31.value, broken, CommonAgentStateEnum.ENERGY_32.value]

    with pytest.warns(RuntimeWarning):
        records = agent._check_agent_states(screen, 456., [CheckAgentState(state) for state in checks])

    assert [(record.state_name, record.value, record.trigger_time) for record in records] == [
        ('前台-能量', 120, 456.), ('后台-1-能量', 120, 456.),
    ]
