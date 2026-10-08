from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest
import yaml

from zzz_od.auto_battle.battle_presence import (
    detect_battle_presence, has_enemy_health_bar, has_target_reticle,
)


def frame():
    return np.zeros((1080, 1920, 3), np.uint8)


def asset_frame(name):
    root = Path(__file__).resolve().parents[1] / 'assets/template/target_state' / name
    config = yaml.safe_load((root / 'config.yml').read_text(encoding='utf-8'))
    x, y = map(int, config['point_list'][0].split(','))
    image = cv2.cvtColor(cv2.imread(str(root / 'raw.png')), cv2.COLOR_BGR2RGB)
    screen = frame()
    screen[y:y+image.shape[0], x:x+image.shape[1]] = image
    return screen


def test_existing_game_assets_provide_enemy_evidence():
    assert has_target_reticle(asset_frame('target_lock'))
    assert has_enemy_health_bar(asset_frame('target_context'))


def test_boss_health_does_not_require_a_filled_stun_gauge():
    screen = asset_frame('target_context')
    hsv = cv2.cvtColor(screen, cv2.COLOR_RGB2HSV)
    yellow = cv2.inRange(hsv, (20, 140, 150), (35, 255, 255))
    screen[yellow > 0] = (80, 80, 80)
    assert has_enemy_health_bar(screen)


def test_attack_hud_alone_is_not_a_fight():
    battle = SimpleNamespace(is_normal_attack_btn_available=Mock(return_value=True))
    assert detect_battle_presence(frame(), battle) is None
    assert not has_enemy_health_bar(frame())
    assert not has_target_reticle(frame())


def test_enemy_bar_pair_detected_but_isolated_effect_is_not():
    screen = frame()
    screen[400:404, 700:800] = (240, 20, 20)
    assert not has_enemy_health_bar(screen)
    screen[407:410, 700:800] = (20, 200, 240)
    assert not has_enemy_health_bar(screen)  # Colored stripes alone are effects too.
    icon = cv2.cvtColor(cv2.imread(str(Path(__file__).resolve().parents[1] /
                                     'assets/template/target_state/enemy_attribute_icon/raw.png')),
                        cv2.COLOR_BGR2RGB)
    screen[384:404, 810:830] = cv2.resize(icon, (20, 20))
    assert not has_enemy_health_bar(screen)  # A badge cannot turn effects into an enemy.
    # Local player/UI bars outside the enemy ROI are not enemy evidence.
    screen = frame()
    screen[100:104, 100:200] = (240, 20, 20)
    screen[107:110, 100:200] = (20, 200, 240)
    assert not has_enemy_health_bar(screen)


@pytest.mark.parametrize('shape', ['line', 'filled_circle', 'square_ring'])
def test_yellow_effects_are_not_lock_markers(shape):
    screen = frame()
    yellow = (255, 160, 0)
    if shape == 'line':
        cv2.line(screen, (800, 400), (800, 700), yellow, 5)
    elif shape == 'filled_circle':
        cv2.circle(screen, (800, 400), 13, yellow, -1)
    else:
        cv2.rectangle(screen, (785, 385), (815, 415), yellow, 4)
    assert not has_target_reticle(screen)


def test_chain_ui_counts_as_battle_without_publishing_or_input():
    cv_service = SimpleNamespace(run_pipeline=Mock(return_value=SimpleNamespace(
        is_success=True, contours=[object()])))
    match = Mock(return_value=object())
    battle = SimpleNamespace(
        is_normal_attack_btn_available=Mock(return_value=False),
        ctx=SimpleNamespace(cv_service=cv_service),
        area_chain_1=SimpleNamespace(rect=SimpleNamespace(x1=479, y1=828, x2=597, y2=946)),
        area_chain_2=SimpleNamespace(rect=SimpleNamespace(x1=1323, y1=828, x2=1441, y2=946)),
        agent_context=SimpleNamespace(get_possible_agent_list=lambda: []),
        _match_chain_agent_in=match,
    )
    assert detect_battle_presence(frame(), battle) == '连携技'
    match.return_value = None
    assert detect_battle_presence(frame(), battle) is None
    match.side_effect = [None, object()]
    assert detect_battle_presence(frame(), battle) == '连携技'
