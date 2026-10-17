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
