from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zzz_od.application.hollow_zero.lost_void.lost_void_app import LostVoidApp
from zzz_od.application.hollow_zero.lost_void.lost_void_challenge_config import LostVoidRegionType
from zzz_od.application.hollow_zero.lost_void.operation import lost_void_run_level as module


@pytest.mark.parametrize('room', [False, True])
def test_loading_operator_does_not_infer_start_room_from_unknown_region(room):
    op = LostVoidApp.__new__(LostVoidApp)
    op.next_region_type = LostVoidRegionType.ENTRY
    lost = SimpleNamespace(in_start_room=room, get_auto_op_name=lambda: '全配队通用')
    op.ctx = SimpleNamespace(lost_void=lost, auto_battle_context=SimpleNamespace(init_auto_op=Mock()))
    op._after_round_wait = lambda **_: None
    assert op.load_auto_op().is_success
    assert lost.in_start_room is room


def operation(monkeypatch, now=100.1, hud=True, start_room=False):
    monkeypatch.setattr(module.time, 'time', lambda: now)
    op = module.LostVoidRunLevel.__new__(module.LostVoidRunLevel)
    op.last_screenshot = object()
    op.last_screenshot_time = 100.
    op.nothing_times = 12
    op.boss_pre_battle = False
    op._after_round_wait = lambda **_: None
    battle = SimpleNamespace(start_auto_battle=Mock(), is_normal_attack_btn_available=Mock(return_value=hud))
    lost = SimpleNamespace(in_start_room=start_room, check_battle_encounter=Mock(return_value=False))
    op.ctx = SimpleNamespace(lost_void=lost, auto_battle_context=battle)
    return op, lost, battle


def test_transient_encounter_starts_on_next_fresh_hud_frame(monkeypatch):
    op, lost, battle = operation(monkeypatch)
    assert op.enter_battle().status == '进入战斗'
    assert op.nothing_times == 12
    op.last_screenshot_time = 100.05
    assert op.init_auto_op().is_success
    battle.start_auto_battle.assert_called_once()
    lost.check_battle_encounter.assert_not_called()
    assert op.nothing_times == 0
    # It cannot be replayed to start another battle without new evidence.
    assert op.init_auto_op().status == '等待战斗信号'
    assert battle.start_auto_battle.call_count == 1


@pytest.mark.parametrize('now,next_frame,hud,room', [
    (100.4, 100.35, True, False),  # expired handoff
    (101., 100.05, True, False),  # stale screenshot
    (100.1, 99.9, True, False),   # time went backwards
    (100.1, 100.05, False, False),
    (100.1, 100.05, True, True),
])
def test_handoff_cannot_bypass_freshness_hud_or_room_guard(monkeypatch, now, next_frame, hud, room):
    op, _, battle = operation(monkeypatch, now, hud, room)
    op.enter_battle()
    op.last_screenshot_time = next_frame
    assert op.init_auto_op().status == '等待战斗信号'
    assert op.nothing_times == 12
    battle.start_auto_battle.assert_not_called()
