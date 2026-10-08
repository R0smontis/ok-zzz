"""Real recorded pixels and native coordinate mapping at 16:9 window sizes."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest
from onedragon.base.geometry.point import Point
from onedragon.base.geometry.rectangle import Rect
from onedragon.base.controller.pc_game_window import PcGameWindow
from onedragon.base.controller.pc_screenshot.pc_screenshot_controller import PcScreenshotController
from zzz_od.auto_battle.auto_battle_context import AutoBattleContext
from zzz_od.auto_battle.auto_battle_agent_context import TeamInfo
from zzz_od.auto_battle.battle_presence import has_enemy_health_bar, detect_chain_presence
from zzz_od.controller.zzz_controller import ZzzController
from src.frame_geometry import FrameGeometry

SIZES = [(1280,720),(1600,900),(1920,1080),(2560,1440),(3840,2160)]
FIXTURES = Path(__file__).parent/'fixtures/combat_recording'


def controller():
    obj = ZzzController.__new__(ZzzController)
    obj.standard_width, obj.standard_height = 1920,1080
    return obj


@pytest.mark.parametrize('size', SIZES)
def test_scaled_recording_preserves_attack_hud_enemy_panel_and_rgb(ctx, size):
    bgr = cv2.imread(str(FIXTURES/'battle_169.jpg'))
    resized = cv2.resize(bgr,size,interpolation=cv2.INTER_AREA)
    original = resized.copy()
    capture = controller()
    rgb = capture.normalize_frame(resized)
    battle = AutoBattleContext(ctx)
    battle.init_screen_area()
    assert rgb.shape == (1080,1920,3)
    assert capture.frame_geometry['source'] == list(size)
    assert battle.is_normal_attack_btn_available(rgb)
    assert has_enemy_health_bar(rgb)
    assert np.array_equal(resized,original)


@pytest.mark.parametrize('size', SIZES)
def test_distant_low_health_recording_is_detected_without_using_badge(size):
    bgr = cv2.resize(cv2.imread(str(FIXTURES/'low_health_far.jpg')),size,interpolation=cv2.INTER_AREA)
    rgb = controller().normalize_frame(bgr)
    assert has_enemy_health_bar(rgb)


@pytest.mark.parametrize('size', SIZES)
def test_chain_with_unknown_party_slot_matches_at_scaled_resolution(ctx,size):
    bgr = cv2.resize(cv2.imread(str(FIXTURES/'chain_rina_claret.jpg')),size)
    battle = AutoBattleContext(ctx)
    battle.init_screen_area()
    battle.agent_context.team_info = TeamInfo(['克拉蕾',None,'丽娜'])
    assert detect_chain_presence(controller().normalize_frame(bgr),battle) == '连携技'


@pytest.mark.parametrize('size', SIZES)
def test_client_and_screen_clicks_use_current_size_and_window_origin(monkeypatch,size):
    dimensions = list(size)
    monkeypatch.setattr(PcGameWindow,'win_rect',property(lambda self:Rect(
        -2600,180,-2600+dimensions[0],180+dimensions[1])))
    monkeypatch.setattr(PcGameWindow,'get_win',lambda self:object())
    window = PcGameWindow()
    point = Point(1750,70)
    client = window.get_scaled_game_pos(point)
    expected = tuple(map(int,FrameGeometry(*size).to_client(point.x,point.y)))
    assert (client.x,client.y) == expected
    desktop = window.game2win_pos(point)
    assert (desktop.x,desktop.y) == (expected[0]-2600,expected[1]+180)
    assert window.get_scaled_game_pos(Point(1920,1080)) is None
    dimensions[:] = [1280,720]
    resized = window.get_scaled_game_pos(point)
    assert (resized.x,resized.y) == tuple(map(int,FrameGeometry(1280,720).to_client(1750,70)))


@pytest.mark.parametrize('size', SIZES)
def test_background_dialogue_click_uses_scaled_client_pixels(monkeypatch,size):
    import zzz_od.controller.zzz_controller as module
    monkeypatch.setattr(PcGameWindow,'win_rect',property(lambda self:Rect(0,0,*size)))
    monkeypatch.setattr(PcGameWindow,'get_win',lambda self:object())
    monkeypatch.setattr(PcGameWindow,'get_hwnd',lambda self:101)
    monkeypatch.setattr(PcGameWindow,'is_win_valid',property(lambda self:True))
    monkeypatch.setattr(PcGameWindow,'is_win_active',property(lambda self:False))
    post = Mock()
    monkeypatch.setattr(module.win32gui,'PostMessage',post)
    capture = controller()
    capture.game_win = PcGameWindow()
    assert capture.click_dialogue_event(Point(1750,70),expected_hwnd=101,allow_background=True)
    x,y = map(int,FrameGeometry(*size).to_client(1750,70))
    assert post.call_count == 3
    assert all(call.args[3] == (x|(y<<16)) for call in post.call_args_list)


@pytest.mark.parametrize('size', [(1280,720),(2560,1440),(3840,2160)])
def test_fallback_capture_scales_actual_pixels_even_if_window_size_changed(size):
    capture = PcScreenshotController.__new__(PcScreenshotController)
    capture.standard_width,capture.standard_height = 1920,1080
    capture.active_strategy_name = 'test'
    capture._get_method_priority_list = lambda method:['test']
    capture.game_win = SimpleNamespace(win_rect=Rect(0,0,1920,1080),is_win_scale=False)
    raw = np.full((size[1],size[0],3),(10,40,220),np.uint8)
    capture.strategies = {'test':SimpleNamespace(capture=lambda *a:raw)}
    result = capture.get_screenshot()
    assert result.shape == (1080,1920,3) and tuple(result[0,0]) == (10,40,220)
    assert capture.get_screenshot(resize=False) is raw


@pytest.mark.parametrize('invalid',[None,np.empty((0,0,3),np.uint8),np.zeros((8,8,2),np.uint8)])
def test_invalid_capture_clears_geometry_and_never_reaches_recognition(invalid):
    capture = controller()
    capture.normalize_frame(np.zeros((720,1280,3),np.uint8))
    assert capture.normalize_frame(invalid) is None
    assert capture.frame_geometry is None


def test_partial_party_prioritizes_known_characters_without_losing_catalogue(ctx):
    from zzz_od.game_data.agent import AgentEnum
    battle = AutoBattleContext(ctx)
    battle.agent_context.team_info = TeamInfo(['克拉蕾',None,'丽娜'])
    candidates = battle.agent_context.get_possible_agent_list()
    assert [a.agent_name for a,_ in candidates[:2]] == ['克拉蕾','丽娜']
    assert {a.agent_id for a,_ in candidates} == {a.value.agent_id for a in AgentEnum}
    assert len(candidates) == len(AgentEnum)


@pytest.fixture(scope='module')
def warning_model(ctx):
    from zzz_od.yolo.flash_classifier import FlashClassifier
    return FlashClassifier(model_name=ctx.model_config.flash_classifier,
        model_parent_dir_path=str(Path('assets/models/flash_classifier').resolve()),
        model_download_url='',gpu=False)


@pytest.mark.parametrize('size', SIZES)
@pytest.mark.parametrize('name,expected',[('red_warning',1),('yellow_warning',2)])
def test_scaled_real_warning_reaches_model_in_rgb(warning_model,size,name,expected):
    bgr=cv2.resize(cv2.imread(str(FIXTURES/(name+'.png'))),size,interpolation=cv2.INTER_AREA)
    result=warning_model.run(controller().normalize_frame(bgr))
    assert result.class_idx==expected and result.confidence>=.9
