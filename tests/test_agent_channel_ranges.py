"""Channel maxima preserve inclusive thresholds, masks and NaN exclusion."""
from types import SimpleNamespace

import numpy as np
import pytest

from onedragon.base.geometry.rectangle import Rect
from zzz_od.auto_battle.agent_state.agent_state_checker import check_cnt_by_color_channel_max_range
from zzz_od.game_data.agent import AgentStateCheckWay, AgentStateDef


def check(screen, mask):
    template = SimpleNamespace(mask=mask, get_template_rect_by_point=lambda: Rect(0, 0, 80, 48))
    ctx = SimpleNamespace(template_loader=SimpleNamespace(get_template=lambda *args: template))
    state = AgentStateDef('测试-颜色', AgentStateCheckWay.COLOR_CHANNEL_MAX_RANGE_EXIST,
                          'test', lower_color=150, upper_color=200, connect_cnt=5)
    return check_cnt_by_color_channel_max_range(ctx, screen, state)


def screen(dtype):
    result = np.zeros((48, 80, 3), dtype)
    result[3:6, 3:6, 0] = 150
    result[26:29, 60:63, 2] = 200
    result[30:33, 4:7, 1] = 175
    result[10:13, 20:23, 1] = 149
    result[34:37, 25:28, 0] = 201
    return result


@pytest.mark.parametrize('dtype', [np.uint8, np.float32])
@pytest.mark.parametrize('hide_first', [False, True])
def test_each_channel_and_inclusive_bounds_count_only_unmasked_islands(dtype, hide_first):
    source = screen(dtype)
    original = source.copy()
    source.setflags(write=False)
    mask = np.full((48, 80), 255, np.uint8)
    if hide_first:
        mask[3:6, 3:6] = 0
    assert check(source, mask) == (2 if hide_first else 3)
    np.testing.assert_array_equal(source, original)


def test_nan_in_any_channel_does_not_become_a_valid_color():
    source = screen(np.float32)
    source[3:6, 3:6, 1] = np.nan
    assert check(source, np.full((48, 80), 255, np.uint8)) == 2
