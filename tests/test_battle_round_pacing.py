"""战斗识别耗时计入轮次间隔，不在截图之后再追加完整等待。"""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from onedragon.base.operation import operation as operation_module
from onedragon.base.operation.operation_round_result import OperationRoundResultEnum as R
from zzz_od.application.intel_board.intel_board_app import IntelBoardApp
from zzz_od.application.shiyu_defense.shiyu_defense_battle import ShiyuDefenseBattle
from zzz_od.application.world_patrol.operation.world_patrol_run_route import WorldPatrolRunRoute
from zzz_od.hollow_zero.hollow_battle import HollowBattle
from zzz_od.operation.battle.base import BattleOpBase
from zzz_od.operation.compendium.area_patrol import AreaPatrol
from zzz_od.operation.compendium.combat_simulation import CombatSimulation
from zzz_od.operation.compendium.expert_challenge import ExpertChallenge
from zzz_od.operation.compendium.notorious_hunt import NotoriousHunt


@pytest.mark.parametrize('cls,method,countdown_due', [
    (CombatSimulation, 'auto_battle', False),
    (ExpertChallenge, 'auto_battle', False),
    (NotoriousHunt, 'auto_battle', False),
    (AreaPatrol, 'auto_battle', False),
    (BattleOpBase, '_do_auto_battle_round', False),
    (HollowBattle, 'auto_battle', False),
    (IntelBoardApp, 'auto_battle', False),
    (ShiyuDefenseBattle, 'auto_battle', False),
    (ShiyuDefenseBattle, 'auto_battle', True),
    (WorldPatrolRunRoute, 'battle_before_start', False),
    (WorldPatrolRunRoute, 'auto_battle', False),
])
@pytest.mark.parametrize('elapsed', [.005, .02, .035])
def test_battle_round_only_waits_for_remaining_interval(monkeypatch, cls, method, countdown_due, elapsed):
    op = cls.__new__(cls)
    battle = SimpleNamespace(last_check_end_result=None, with_distance_times=0,
                             check_battle_state=Mock(return_value=True))
    op.ctx = SimpleNamespace(auto_battle_context=battle,
                             battle_assistant_config=SimpleNamespace(screenshot_interval=.02))
    op.round_start_time = 0.
    op.last_screenshot, op.last_screenshot_time = None, 100.
    op.in_battle = True
    op._pre_battle_started = op.last_check_battle_time = 100.
    op._last_countdown_check_time = 0. if countdown_due else 100.
    op.check_shiyu_countdown = lambda _: True
    op._check_battle_state = lambda: True
    op._check_in_battle_secondary = lambda _: None
    sleeps = []
    monkeypatch.setattr(operation_module.time, 'time', lambda: elapsed)
    monkeypatch.setattr(operation_module.time, 'sleep', sleeps.append)

    assert getattr(op, method)().result == R.WAIT
    assert sum(sleeps) == pytest.approx(max(0., .02 - elapsed))
    assert len(sleeps) == (1 if elapsed < .02 else 0)
