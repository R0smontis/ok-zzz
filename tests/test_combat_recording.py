"""Regressions from the user's real game recording, with no device input."""
import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest

from onedragon.base.conditional_operation.state_recorder import StateRecord
from onedragon.base.matcher.ocr.ok_ocr_matcher import OkOcrMatcher
from zzz_od.auto_battle.auto_battle_context import AutoBattleContext
from zzz_od.auto_battle.auto_battle_agent_context import TeamInfo
from zzz_od.auto_battle.battle_presence import detect_battle_presence, has_enemy_health_bar
from zzz_od.controller.zzz_controller import ZzzController

FIXTURES = Path(__file__).parent / 'fixtures/combat_recording'
CASES = json.loads((FIXTURES / 'cases.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case', CASES, ids=[c['name'] for c in CASES])
def test_real_enemy_panels_and_empty_scene_objects(case):
    image = cv2.imread(str(FIXTURES / case['file']))
    bgr = np.zeros((1080, 1920, 3), np.uint8)
    x, y = case['x'], case['y']
    bgr[y:y+image.shape[0], x:x+image.shape[1]] = image
    controller = ZzzController.__new__(ZzzController)
    controller.standard_width, controller.standard_height = 1920, 1080
    rgb = controller.normalize_frame(bgr)
    battle = SimpleNamespace(is_normal_attack_btn_available=Mock(return_value=True))
    assert has_enemy_health_bar(rgb) is case['enemy']
    assert bool(detect_battle_presence(rgb, battle)) is case['enemy']


def test_orange_circle_alone_never_grants_combat_input():
    # The old geometry test also sees circular Bangboo features/object markers.
    rgb = np.zeros((1080, 1920, 3), np.uint8)
    cv2.circle(rgb, (850, 400), 13, (255, 160, 0), 3)
    battle = SimpleNamespace(is_normal_attack_btn_available=Mock(return_value=True))
    assert detect_battle_presence(rgb, battle) is None


@pytest.mark.parametrize('name,expected', [('yellow_warning', 2), ('red_warning', 1)])
def test_real_warning_frames_reach_model_in_rgb(ctx, name, expected):
    from zzz_od.yolo.flash_classifier import FlashClassifier
    model = FlashClassifier(model_download_url=ctx.model_config.get_model_download_base_url('flash_classifier'),
                            model_name=ctx.model_config.flash_classifier, gpu=False)
    bgr = cv2.imread(str(FIXTURES / (name + '.png')))
    controller = ZzzController.__new__(ZzzController)
    controller.standard_width, controller.standard_height = 1920, 1080
    rgb = controller.normalize_frame(bgr)
    result = model.run(rgb)
    assert result.class_idx == expected and result.confidence >= 0.9
    assert model.run(cv2.resize(bgr, (1920, 1080))).class_idx == 0


def test_rgb_engine_frame_is_converted_back_for_ok_ocr():
    lib = SimpleNamespace(ocr=Mock(return_value=[]))
    rgb = np.full((8, 10, 3), (240, 40, 15), np.uint8)
    OkOcrMatcher(lambda: lib).ocr(rgb)
    assert tuple(lib.ocr.call_args.args[0][0, 0]) == (15, 40, 240)
    assert tuple(rgb[0, 0]) == (240, 40, 15)


def test_ocr_adapter_preserves_grayscale_images():
    lib = SimpleNamespace(ocr=Mock(return_value=[]))
    grey = np.full((8, 10), 180, np.uint8)
    assert OkOcrMatcher(lambda: lib).ocr(grey) == []
    assert lib.ocr.call_args.args[0] is grey


def test_claret_warning_executes_dodge_before_counterattack(ctx, stubbed_controller, monkeypatch):
    context, recorder = stubbed_controller
    battle = AutoBattleContext(context)
    monkeypatch.setitem(context.__dict__, '_auto_battle_context', battle)
    monkeypatch.setattr(context.controller, 'battle_input_guard', None)
    monkeypatch.setattr(context.controller, 'background_mode', False)
    battle.init_screen_area()
    battle.init_auto_op('全配队通用')
    battle.agent_context.team_info = TeamInfo(['克拉蕾', '妮可', '比利'])
    battle.auto_op.auto_lock_interval = -1
    battle.auto_op.auto_turn_interval = -1
    try:
        now = time.time()
        battle.state_record_service.batch_update_states([
            StateRecord('前台-克拉蕾', now), StateRecord('自定义-红光闪避', now),
            StateRecord('按键可用-普通攻击', now)])
        battle.auto_op.start_running_async()
        keys = context.game_config.get_action_keys('keyboard')
        attack = ('tap', keys['normal_attack'])
        deadline = time.monotonic() + 2
        while attack not in recorder.events and time.monotonic() < deadline:
            time.sleep(0.01)
        dodge = ('tap', keys['dodge'])
        assert dodge in recorder.events and attack in recorder.events
        assert recorder.events.index(dodge) < recorder.events.index(attack)
    finally:
        battle.auto_op.stop_running()
        battle.auto_op.dispose()
