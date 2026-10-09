"""One mapping from Xbox button names to the configured virtual pad's registered keys."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.controls.gamepad import pad_key, press

# Every button the navigation and Lost Void code presses, with the key each pad must receive.
PAIRS = [('a', 'xbox_a', 'ds4_cross'), ('b', 'xbox_b', 'ds4_circle'),
         ('x', 'xbox_x', 'ds4_square'), ('y', 'xbox_y', 'ds4_triangle'),
         ('lb', 'xbox_lb', 'ds4_l1'), ('rb', 'xbox_rb', 'ds4_r1'),
         ('rt', 'xbox_rt', 'ds4_r2'), ('start', 'xbox_start', 'ds4_options'),
         ('dpad_up', 'xbox_dpad_up', 'ds4_dpad_up'), ('dpad_left', 'xbox_dpad_left', 'ds4_dpad_left'),
         ('ls_slow_left', 'xbox_ls_slow_left', 'ds4_ls_slow_left')]


def ctx(kind):
    return SimpleNamespace(game_config=SimpleNamespace(background_gamepad_type=kind),
                           controller=SimpleNamespace(btn_press=Mock()))


@pytest.mark.parametrize('button,xbox,ds4', PAIRS)
def test_button_maps_to_each_pad(button, xbox, ds4):
    assert pad_key(ctx('xbox'), button) == xbox
    assert pad_key(ctx('ds4'), button) == ds4


def test_press_uses_default_duration():
    c = ctx('ds4')
    press(c, 'b')
    c.controller.btn_press.assert_called_once_with('ds4_circle', press_time=.12)
