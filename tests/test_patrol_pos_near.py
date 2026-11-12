"""锄大地 position matching keeps to the allowed move (live 2026-10-17: a repeated structure 140 px
away kept winning the global match, was discarded as a jump, and the route lost its position)."""
from types import SimpleNamespace

import numpy as np

from onedragon.base.geometry.point import Point
from onedragon.base.geometry.rectangle import Rect
from zzz_od.application.world_patrol.world_patrol_service import WorldPatrolService


def scene():
    rng = np.random.default_rng(7)
    patch = (rng.random((120, 120)) > .7).astype(np.uint8) * 255
    road = np.zeros((900, 900), np.uint8)
    true_center, twin_center = Point(400, 500), Point(400, 360)  # 140 px apart, like the live log
    noisy = patch.copy()
    noisy[::9, ::7] = 255 - noisy[::9, ::7]  # The real spot matches a little worse than its twin.
    road[440:560, 340:460] = noisy
    road[300:420, 340:460] = patch
    large_map = SimpleNamespace(road_mask=road, icon_list=[])
    mini_map = SimpleNamespace(road_mask=patch, rgb=np.zeros((120, 120, 3), np.uint8))
    service = object.__new__(WorldPatrolService)
    return service, large_map, mini_map, true_center, twin_center


def test_global_best_can_be_the_far_twin():
    service, large_map, mini_map, _, twin = scene()
    pos = service.cal_pos(large_map, mini_map, Rect(150, 150, 750, 750))
    assert abs(pos.x - twin.x) <= 2 and abs(pos.y - twin.y) <= 2


def test_match_within_the_allowed_move_wins_over_a_far_twin():
    service, large_map, mini_map, true_center, _ = scene()
    last = Point(405, 520)  # Previous position; the twin is ~160 px away, beyond a 60 px move.
    pos = service.cal_pos(large_map, mini_map, Rect(150, 150, 750, 750), near=(last, 60))
    assert abs(pos.x - true_center.x) <= 2 and abs(pos.y - true_center.y) <= 2


def test_weak_near_match_does_not_hide_a_clearly_better_far_one():
    # The previous position may itself be wrong: junk near it must not be locked onto.
    service, large_map, mini_map, _, twin = scene()
    last = Point(700, 700)
    pos = service.cal_pos(large_map, mini_map, Rect(150, 150, 850, 850), near=(last, 30))
    assert abs(pos.x - twin.x) <= 2 and abs(pos.y - twin.y) <= 2


def test_near_window_at_the_map_edge_is_clipped():
    service, large_map, mini_map, true_center, _ = scene()
    pos = service.cal_pos(large_map, mini_map, Rect(-100, -100, 1000, 1000), near=(Point(400, 505), 40))
    assert abs(pos.x - true_center.x) <= 2 and abs(pos.y - true_center.y) <= 2


def icon_scene(decoy: Point):
    """Two icons of the same template give two tied candidates; only the road overlap separates them."""
    icon = np.random.default_rng(11).integers(0, 256, (16, 16, 3), dtype=np.uint8)
    rgb = np.zeros((120, 120, 3), np.uint8)
    rgb[40:56, 30:46] = icon  # Icon centre at (38, 48) on the mini map.
    mini_road = np.zeros((120, 120), np.uint8)
    mini_road[5:35, 5:35] = 255  # 900 px near the top-left corner.
    mini_road[90:115, 90:115] = 255  # 625 px near the bottom-right corner.
    road = np.zeros((900, 900), np.uint8)
    true_pos = Point(200, 300)
    road[305:335, 205:235] = 255  # The true spot shares the larger part.
    if decoy.x >= 0 and decoy.y >= 0:
        road[decoy.y + 90:decoy.y + 115, decoy.x + 90:decoy.x + 115] = 255  # The decoy shares the smaller one.
    icons = [SimpleNamespace(template_id='icon', lm_pos=pos + Point(38, 48)) for pos in (true_pos, decoy)]
    template = SimpleNamespace(template_id='icon', raw=icon, mask=None)
    service = object.__new__(WorldPatrolService)
    service.ctx = SimpleNamespace(template_loader=SimpleNamespace(get_template=lambda sub_dir, name: template))
    large_map = SimpleNamespace(road_mask=road, icon_list=icons)
    mini_map = SimpleNamespace(road_mask=mini_road, rgb=rgb)
    return service, large_map, mini_map, Point(true_pos.x + 60, true_pos.y + 60)


def test_tied_icon_candidates_are_ranked_by_matching_road_pixels():
    # The decoy overlaps fewer road pixels, but they sit further down-right inside the mask.
    service, large_map, mini_map, expected = icon_scene(Point(500, 600))
    pos = service.cal_pos_by_icon(large_map, mini_map, Rect(0, 0, 900, 900))
    assert abs(pos.x - expected.x) <= 1 and abs(pos.y - expected.y) <= 1


def test_tied_icon_candidate_outside_the_map_does_not_abort_the_route():
    service, large_map, mini_map, expected = icon_scene(Point(-18, -18))
    pos = service.cal_pos_by_icon(large_map, mini_map, Rect(-100, -100, 900, 900))
    assert abs(pos.x - expected.x) <= 1 and abs(pos.y - expected.y) <= 1
