"""Real map fixtures verify destination identity before any controller confirm."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import cv2
import numpy as np
import pytest
from onedragon.base.geometry.rectangle import Rect
from onedragon.base.operation.operation_round_result import OperationRoundResultEnum as R
from zzz_od.game_data.map_area import MapAreaService
from zzz_od.operation.map_transport import MapTransport
from src.navigation.map import map_state, choose_area, choose_point, confirm_point, point_candidates, return_from_map
from src.navigation.map import _coffee_occlusion_candidates
from test_lost_void_background_menus import operation

BASE=Path(__file__).parent/'fixtures/daily_map'

def fixture(name, area, point):
    op=operation(MapTransport)
    op.area_name,op.tp_name=area,point
    screen=cv2.cvtColor(cv2.imread(str(BASE/f'{name}.png')),cv2.COLOR_BGR2RGB)
    payload=json.loads((BASE/f'{name}.json').read_text(encoding='utf-8'))
    rows=[SimpleNamespace(data=r['text'],confidence=r['confidence'],center=Rect(r['rect'][0],r['rect'][1],r['rect'][0]+r['rect'][2],r['rect'][1]+r['rect'][3]).center) for r in payload['result']['ocr']]
    def ocr(image,rect):
        if name=='map-counter-hover-real' and rect.x1==1480:
            return [SimpleNamespace(data='柜台',confidence=.9991,center=Rect(1480,132,1540,166).center)]
        return [r for r in rows if rect.x1<=r.center.x<rect.x2 and rect.y1<=r.center.y<rect.y2]
    op.ctx.ocr_service=SimpleNamespace(get_ocr_result_list=ocr)
    op.ctx.map_service=MapAreaService()
    op.ctx.map_service.reload()
    op.ctx.game_config.get_action_keys=lambda mode:{'move_'+a:('ds4_' if mode=='ds4' else 'xbox_')+'ls_'+b for a,b in [('a','left'),('d','right'),('w','up'),('s','down')]}
    return op,screen


def test_real_new_map_reads_selected_region_without_bottom_point_list():
    op,screen=fixture('map-counter-region','录像店','柜台')
    state=map_state(op,screen)
    assert state['selected']=='录像店'
    assert choose_area(op,screen).is_success
    op.ctx.controller.btn_press.assert_not_called()


def test_real_visible_region_target_uses_dpad_and_verifies_next_frame():
    op,screen=fixture('bakery-region-target','澄辉坪','咖啡店')
    assert choose_area(op,screen).result==R.RETRY
    op.ctx.controller.btn_press.assert_called_once_with('xbox_dpad_down',press_time=.12)
    for _ in range(2):assert not choose_area(op,screen).is_success
    assert choose_area(op,screen).is_fail
    assert op.ctx.controller.btn_press.call_count==3


@pytest.mark.parametrize('name,area,point',[('bakery-final-hover','布亚斯特城区','吼吼饼铺'),('map-counter-hover-real','录像店','柜台')])
def test_exact_point_name_and_visible_go_button_are_required(name,area,point):
    op,screen=fixture(name,area,point)
    assert choose_point(op,screen).is_success
    assert confirm_point(op,screen).result==R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_a',press_time=.12)
    assert not confirm_point(op,screen).is_success
    assert not confirm_point(op,screen).is_success
    assert confirm_point(op,screen).is_fail


def test_wrong_point_never_receives_confirm():
    op,screen=fixture('bakery-final-hover','布亚斯特城区','柜台')
    assert confirm_point(op,screen).is_fail
    op.ctx.controller.btn_press.assert_not_called()


def test_loading_only_advances_after_verified_destination_confirm():
    op,screen=fixture('map-counter-confirm','录像店','柜台')
    assert confirm_point(op,screen).is_fail
    op._background_go_requests=1
    assert confirm_point(op,screen).is_success
    op.ctx.controller.btn_press.assert_not_called()


def test_no_valid_map_or_no_target_template_sends_no_move():
    op,screen=fixture('map-counter-region','录像店','未支持的传送点')
    assert choose_point(op,screen).result==R.RETRY
    op.ctx.controller.btn_press.assert_not_called()
    op.ctx.ocr_service.get_ocr_result_list=lambda **_:[]
    assert map_state(op,screen) is None
    assert choose_area(op,screen).result==R.RETRY
    assert choose_point(op,screen).result==R.RETRY
    assert confirm_point(op,screen).is_fail
    op.ctx.controller.btn_press.assert_not_called()


def test_real_bakery_and_coffee_icons_match_correct_map_only():
    op,bakery=fixture('bakery-region-target','布亚斯特城区','吼吼饼铺')
    _,clear_bakery=fixture('bakery-clear-icon','布亚斯特城区','吼吼饼铺')
    _,street=fixture('map-counter-final','六分街','咖啡店')
    found=point_candidates(bakery,'吼吼饼铺')
    assert found and abs(found[0][0]-323)<10 and abs(found[0][1]-256)<10
    found=point_candidates(clear_bakery,'吼吼饼铺')
    assert found and abs(found[0][0]-772)<15 and abs(found[0][1]-550)<15
    assert not point_candidates(street,'吼吼饼铺')
    found=point_candidates(street,'咖啡店')
    assert found and abs(found[0][0]-943)<20 and abs(found[0][1]-453)<20
    assert not point_candidates(bakery,'咖啡店')
    assert not point_candidates(np.zeros_like(street),'咖啡店')


def test_portrait_with_speech_bubble_over_cafe_moves_cursor_but_never_confirms():
    op,screen=fixture('coffee-idle-map','六分街','咖啡店')
    # The sage barrel is not a cafe icon; the cup is hidden by a portrait whose
    # speech bubble is a second, overlapping circle (the live 2026-10-08 failure).
    assert not point_candidates(screen,'咖啡店')
    found=_coffee_occlusion_candidates(screen)
    assert len(found)==1 and abs(found[0][0]-520)<10 and abs(found[0][1]-460)<10
    assert choose_point(op,screen).result==R.RETRY
    assert op.ctx.controller.btn_press.call_args.args[0]=='xbox_ls_left'
    op.ctx.controller.btn_press.reset_mock()
    assert confirm_point(op,screen).is_fail
    op.ctx.controller.btn_press.assert_not_called()


def test_portrait_occluded_cafe_uses_ramen_landmark_but_never_confirms():
    op, screen = fixture('coffee-map-fresh08', '六分街', '咖啡店')
    assert not point_candidates(screen, '咖啡店')
    assert choose_point(op, screen).result == R.RETRY
    assert op.ctx.controller.btn_press.call_args.args[0] == 'xbox_ls_left'
    op.ctx.controller.btn_press.reset_mock()
    assert confirm_point(op, screen).is_fail
    op.ctx.controller.btn_press.assert_not_called()


def test_map_movement_leaves_slow_stick_when_fresh_frames_show_no_motion():
    op, screen = fixture('bakery-clear-icon', '布亚斯特城区', '吼吼饼铺')
    assert choose_point(op, screen).result == R.RETRY
    assert op.ctx.controller.btn_press.call_args.args[0] == 'xbox_ls_slow_right'
    assert choose_point(op, screen).result == R.RETRY
    assert choose_point(op, screen).result == R.RETRY
    assert op.ctx.controller.btn_press.call_args.args[0] == 'xbox_ls_right'
    assert op.ctx.controller.btn_press.call_args.kwargs['press_time'] >= .10
    op.ctx.controller.click.assert_not_called()


def test_real_zoomed_cafe_covers_both_occluded_and_visible_cup():
    occluded = cv2.cvtColor(cv2.imread(str(BASE/'coffee-occluded-zoom.png')), cv2.COLOR_BGR2RGB)
    visible = cv2.cvtColor(cv2.imread(str(BASE/'coffee-visible-zoom.png')), cv2.COLOR_BGR2RGB)
    candidates = _coffee_occlusion_candidates(occluded, focused_ramen=True)
    assert len(candidates) == 1
    assert abs(candidates[0][0]-428) < 5 and abs(candidates[0][1]-485) < 5
    candidates = point_candidates(visible, '咖啡店')
    assert candidates and abs(candidates[0][0]-285) < 10
    assert not _coffee_occlusion_candidates(np.zeros_like(occluded), focused_ramen=True)


def test_real_icon_search_moves_without_confirming_any_other_point():
    op,screen=fixture('bakery-clear-icon','布亚斯特城区','吼吼饼铺')
    result=choose_point(op,screen)
    assert result.result==R.RETRY
    assert op.ctx.controller.btn_press.call_args.args[0]=='xbox_ls_slow_right'
    assert .025<=op.ctx.controller.btn_press.call_args.kwargs['press_time']<=.24
    op.ctx.controller.click.assert_not_called()


def test_occluded_icon_uses_verified_map_zoom_with_bounded_attempts():
    op,screen=fixture('bakery-region-target','布亚斯特城区','吼吼饼铺')
    screen[80:955,40:1370]=0  # Simulate target symbols occluded while verified map UI remains.
    for _ in range(3):assert choose_point(op,screen).result==R.RETRY
    assert op.ctx.controller.btn_press.call_count==3
    assert all(c.args==('xbox_rt',) for c in op.ctx.controller.btn_press.call_args_list)
    assert choose_point(op,screen).result==R.RETRY
    assert op.ctx.controller.btn_press.call_count==3


def test_verified_map_return_is_bounded_and_uses_ds4_when_configured():
    op,screen=fixture('map-counter-hover-real','录像店','柜台')
    op.ctx.game_config.background_gamepad_type='ds4'
    for _ in range(4):assert return_from_map(op,screen).result==R.RETRY
    assert return_from_map(op,screen).is_fail
    assert op.ctx.controller.btn_press.call_count==4
    assert all(c.args==('ds4_circle',) for c in op.ctx.controller.btn_press.call_args_list)


def test_focused_neighbour_covering_target_keeps_steering_instead_of_zooming(monkeypatch):
    import src.navigation.map as navigation
    op,screen=fixture('bakery-clear-icon','布亚斯特城区','吼吼饼铺')
    state={'info':False,'detail':True,'title':'布亚斯特城区','point':'吼吼饼铺','can_go':False,'selected':None,'rows':[]}
    monkeypatch.setattr(navigation,'map_state',lambda op,screen: dict(state))
    found=[[(507.,220.,.9)]]
    monkeypatch.setattr(navigation,'point_candidates',lambda screen,point: found[0])
    assert choose_point(op,screen).result==R.RETRY  # Moves toward the icon (y axis: 320 px away).
    first=op.ctx.controller.btn_press.call_args.args[0]
    assert first=='xbox_ls_up'
    found[0]=[]
    state['point']='算枢广场'  # Cursor now rests on the neighbour; its focus marker hides the bakery.
    for _ in range(4):
        assert choose_point(op,screen).result==R.RETRY
    pressed=[c.args[0] for c in op.ctx.controller.btn_press.call_args_list[1:]]
    assert 'xbox_rt' not in pressed and pressed  # Steered toward the expected spot, did not zoom.
    assert pressed[0] in ('xbox_ls_left','xbox_ls_slow_left','xbox_ls_up','xbox_ls_slow_up')
    assert choose_point(op,screen).result==R.RETRY  # Dead reckoning is bounded; then the old zoom fallback.
    op.ctx.controller.click.assert_not_called()


def test_counter_room_pair_steers_to_the_targets_side_once_partner_is_named(monkeypatch):
    import src.navigation.map as navigation
    op,screen=fixture('bakery-clear-icon','录像店','房间')
    state={'info':False,'detail':True,'title':'录像店','point':'','can_go':False,'selected':None,'rows':[]}
    monkeypatch.setattr(navigation,'map_state',lambda op,screen: dict(state))
    found=[[(697.,683.,.9)]]  # Only the counter icon is visible; the room is cut off at the top.
    monkeypatch.setattr(navigation,'point_candidates',lambda screen,point: found[0])
    assert choose_point(op,screen).result==R.RETRY
    assert op.ctx.controller.btn_press.call_args.args[0] in ('xbox_ls_down','xbox_ls_slow_down')  # Toward it at first.
    state['point']='柜台';found[0]=[]  # Focused counter no longer matches the template.
    for _ in range(3):
        assert choose_point(op,screen).result==R.RETRY
        assert op.ctx.controller.btn_press.call_args.args[0] in ('xbox_ls_up','xbox_ls_slow_up')
    state['point']='';found[0]=[(697.,700.,.9),(700.,180.,.8)]  # Counter below and room above both visible.
    assert choose_point(op,screen).result==R.RETRY
    assert op.ctx.controller.btn_press.call_args.args[0] in ('xbox_ls_up','xbox_ls_slow_up')
    assert 'xbox_rt' not in [c.args[0] for c in op.ctx.controller.btn_press.call_args_list]
    found[0]=[(700.,560.,.8)]  # The room now sits just below centre: still tracked, not filtered away.
    assert choose_point(op,screen).result==R.RETRY
    assert op.ctx.controller.btn_press.call_args.args[0] in ('xbox_ls_down','xbox_ls_slow_down','xbox_ls_left','xbox_ls_slow_left','xbox_ls_right','xbox_ls_slow_right')


def test_player_cone_over_the_target_icon_becomes_a_candidate(monkeypatch):
    import src.navigation.map as navigation
    op,screen=fixture('map-room-player-marker','录像店','房间')
    assert not point_candidates(screen,'房间')  # The room icon is covered by the player cone.
    marks=navigation._player_marker_candidates(screen)
    assert len(marks)==1 and abs(marks[0][0]-1095)<12 and abs(marks[0][1]-728)<12
    state={'info':False,'detail':False,'title':'录像店','point':'','can_go':False,'selected':None,'rows':[]}
    monkeypatch.setattr(navigation,'map_state',lambda op,screen: dict(state))
    assert choose_point(op,screen).result==R.RETRY
    assert op.ctx.controller.btn_press.call_args.args[0] in ('xbox_ls_right','xbox_ls_slow_right')  # Toward x≈1095.


def test_region_grid_selects_store_and_waits_for_verified_point_list():
    op, screen = fixture('map-quick-nav', '录像店', '房间')
    assert map_state(op, screen)['selected'] == '布亚斯特城区'
    assert choose_area(op, screen).result == R.RETRY
    op.ctx.controller.btn_press.assert_called_once_with('xbox_dpad_down', press_time=.12)
    # The next frame must show the new focus before another directional press.
    # Move only the controller outline on the real grid; retain its real OCR.
    from src.navigation.menus import focus_mask
    def focused_grid(col, row):
        frame = screen.copy()
        frame[focus_mask(frame)] = 0
        x0, x1, y0, y1 = 12 + 636 * col, 636 + 636 * col, 102 + 279 * row, 368 + 279 * row
        frame[y0:y1, x0-2:x0+10] = (170, 205, 45)
        frame[y0:y1, x1-10:x1+2] = (170, 205, 45)
        return frame
    for col, row, button in [(0, 1, 'xbox_dpad_down'), (0, 2, 'xbox_dpad_right'), (1, 2, 'xbox_a')]:
        assert choose_area(op, focused_grid(col, row)).result == R.RETRY
        assert op.ctx.controller.btn_press.call_args.args == (button,)
    # Highlighting the target card alone never completes area selection.
    assert op.ctx.controller.btn_press.call_count == 4
    selected_op, selected = fixture('quick-nav-video-store', '录像店', '房间')
    op.ctx.ocr_service = selected_op.ctx.ocr_service
    assert choose_area(op, selected).is_success
    assert op.ctx.controller.btn_press.call_count == 4
    assert choose_point(op, selected).result == R.WAIT
    assert op.ctx.controller.btn_press.call_args.args == ('xbox_dpad_right',)


def test_region_grid_without_unique_focus_or_target_never_sends_input():
    op, screen = fixture('map-quick-nav', '录像店', '房间')
    from src.navigation.menus import focus_mask
    screen[focus_mask(screen)] = 0
    assert choose_area(op, screen).result == R.RETRY
    op.ctx.controller.btn_press.assert_not_called()
    op.ctx.ocr_service.get_ocr_result_list = lambda **_: []
    assert choose_area(op, screen).result == R.RETRY
    assert return_from_map(op, screen) is None
    op.ctx.controller.btn_press.assert_not_called()


def test_verified_region_grid_can_return_without_selecting_destination():
    op, screen = fixture('map-quick-nav', '录像店', '房间')
    assert return_from_map(op, screen).result == R.RETRY
    op.ctx.controller.btn_press.assert_called_once_with('xbox_b', press_time=.12)


def test_unchanged_region_grid_focus_stops_without_blind_search():
    op, screen = fixture('map-quick-nav', '录像店', '房间')
    for _ in range(3):
        assert choose_area(op, screen).result == R.RETRY
    assert choose_area(op, screen).is_fail
    assert op.ctx.controller.btn_press.call_count == 3


def test_region_grid_target_outline_does_not_accept_another_regions_points():
    op, screen = fixture('quick-nav-video-store', '录像店', '房间')
    original = op.ctx.ocr_service.get_ocr_result_list
    def stale_points(image, rect):
        return [SimpleNamespace(data='吼吼饼铺' if row.data == '房间' else row.data,
                                confidence=row.confidence, center=row.center)
                for row in original(image, rect)]
    op.ctx.ocr_service.get_ocr_result_list = stale_points
    assert choose_area(op, screen).result == R.RETRY
    op.ctx.controller.btn_press.assert_not_called()
