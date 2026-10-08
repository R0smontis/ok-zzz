import cv2
import numpy as np
import pytest
from zzz_od.auto_battle.battle_presence import find_enemy_direction_arrow


def arrow_frame(color=(255,35,25), location=(220,540), outlined=True):
    screen=np.full((1080,1920,3),150,np.uint8)
    x,y=location
    shape=np.array([[x-15,y],[x+10,y-12],[x+10,y+12]],np.int32)
    if outlined:
        cv2.polylines(screen,[shape],True,(20,20,20),7)
    cv2.fillPoly(screen,[shape],color)
    return screen


def test_outlined_red_outward_arrow_is_a_candidate():
    assert find_enemy_direction_arrow(arrow_frame()) is not None


@pytest.mark.parametrize('color,location,outline', [
    ((255,160,0),(220,540),True), # Yellow objective arrows.
    ((255,35,25),(220,540),False), # Particle triangles without HUD outline.
    ((255,35,25),(960,540),True), # Central damage effects.
    ((255,35,25),(1750,220),True), # Mission UI.
])
def test_non_enemy_triangles_are_rejected(color,location,outline):
    assert find_enemy_direction_arrow(arrow_frame(color,location,outline)) is None


def test_triangle_pointing_toward_center_is_not_an_offscreen_indicator():
    screen=arrow_frame()
    screen[:,160:280]=150
    shape=np.array([[235,540],[210,528],[210,552]],np.int32)
    cv2.polylines(screen,[shape],True,(20,20,20),7)
    cv2.fillPoly(screen,[shape],(255,35,25))
    assert find_enemy_direction_arrow(screen) is None


def test_recorded_npc_crossed_swords_badge_is_not_an_enemy_arrow():
    from pathlib import Path
    screen=cv2.imread(str(Path(__file__).parent/'fixtures/lost_void/npc_route_badge_no_enemy.png'))
    assert screen is not None
    assert find_enemy_direction_arrow(cv2.cvtColor(screen,cv2.COLOR_BGR2RGB)) is None
