from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest
import yaml

from zzz_od.auto_battle.battle_presence import (
    align_combat_hud, detect_battle_presence, has_enemy_health_bar, has_target_reticle,
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


@pytest.mark.parametrize('size', [(3024, 1898), (2560, 1080)])
def test_native_combat_hud_matches_reference_without_moving_the_scene(size):
    from onedragon.base.matcher.template_matcher import TemplateMatcher
    from onedragon.base.screen.template_loader import TemplateLoader
    from src.runtime.frame_geometry import FrameGeometry

    recording = Path(__file__).parent / 'fixtures/combat_recording/battle_169.jpg'
    reference = cv2.cvtColor(cv2.imread(str(recording)), cv2.COLOR_BGR2RGB)
    sx, sy = FrameGeometry(*size).ui_scale
    transform = np.float32([[sx, 0, 1919 * (1 - sx)], [0, sy, 1079 * (1 - sy)]])
    stretched = cv2.warpAffine(reference, transform, (1920, 1080))
    aligned = align_combat_hud(stretched, size)
    matcher = TemplateMatcher(TemplateLoader())

    def has_attack(screen):
        return matcher.match_template(screen[916:1017, 1403:1505],
                                      'battle', 'btn_normal_attack', threshold=.9).max is not None

    assert has_attack(reference)
    assert not has_attack(stretched)
    assert has_attack(aligned)
    np.testing.assert_array_equal(aligned[140:740], stretched[140:740])


def test_bright_enemy_panel_survives_green_scenery():
    root = Path(__file__).resolve().parents[1] / 'assets/template/target_state'
    panel = cv2.cvtColor(cv2.imread(str(root / 'enemy_health_panel_shape/raw.png')), cv2.COLOR_BGR2RGB)
    yellow = cv2.inRange(cv2.cvtColor(panel, cv2.COLOR_RGB2HSV), (10, 100, 100), (35, 255, 255))
    panel[yellow > 0] = (72, 72, 72)
    scene = np.full_like(frame(), (62, 117, 90))
    scene[480:480 + panel.shape[0], 1180:1180 + panel.shape[1]] = panel
    assert has_enemy_health_bar(scene)
    scene[480:480 + panel.shape[0], 1180:1180 + panel.shape[1]] = (62, 117, 90)
    assert not has_enemy_health_bar(scene)


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


@pytest.mark.parametrize('seed_kind,height,seed_x,seed_y', [
    ('health', 17, 4, 5),
    ('daze', 7, 32, 14),
])
def test_same_height_candidates_preserve_first_matching_template_and_geometry(seed_kind, height, seed_x, seed_y):
    from zzz_od.auto_battle.battle_presence import _find_world_panel

    # Two candidates share a height; only the second contains a panel.
    hsv = np.full((120, 380, 3), 255, np.uint8)
    x, y = 200, 40
    large = np.random.default_rng(37).integers(0, 256, (12, 22), dtype=np.uint8)
    hsv[y-seed_y:y-seed_y+12, x-seed_x:x-seed_x+22, 2] = 255-large
    small = large[1:11, 1:21].astype(np.float32)
    large = large.astype(np.float32)
    contours = [np.array([[[left, y]], [[left+29, y]], [[left+29, y+height-1]],
                          [[left, y+height-1]]], np.int32) for left in (60, x)]
    panel = _find_world_panel(hsv, contours, seed_kind, shapes=[(1., small), (1., large)])
    assert panel == {'panel_kind': 'world', 'seed_kind': seed_kind, 'confidence': 1.,
                     'rect': [90+x-seed_x+1, 180+y-seed_y+1, 20, 10]}

    # A later call must use its own templates, even for the same height.
    panel = _find_world_panel(hsv, contours, seed_kind, shapes=[(1., large)])
    assert panel == {'panel_kind': 'world', 'seed_kind': seed_kind, 'confidence': 1.,
                     'rect': [90+x-seed_x, 180+y-seed_y, 22, 12]}


def test_height_without_eligible_templates_is_not_enemy_evidence():
    from zzz_od.auto_battle.battle_presence import _find_world_panel

    hsv = np.zeros((100, 200, 3), np.uint8)
    contour = np.array([[[40, 30]], [[89, 30]], [[89, 57]], [[40, 57]]], np.int32)
    template = np.arange(200, dtype=np.float32).reshape(10, 20)
    assert _find_world_panel(hsv, [contour], 'health', shapes=[(1., template)]) is None
