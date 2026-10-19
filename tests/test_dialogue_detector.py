from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
import yaml

from onedragon.base.geometry.point import Point
from onedragon.base.geometry.rectangle import Rect
from zzz_od.application.commission_assistant.dialogue_detector import DialogueDetector


@pytest.fixture
def dialogue_scene(monkeypatch):
    path = Path(__file__).resolve().parents[1] / 'assets/game_data/screen_info/commission_assistant.yml'
    data = yaml.safe_load(path.read_text(encoding='utf-8'))
    areas = {area['area_name']: SimpleNamespace(rect=Rect(*area['pc_rect'])) for area in data['area_list']}
    texts, found = {}, set()

    def ocr(image, rect, **kwargs):
        name = next((name for name, area in areas.items() if area.rect == rect), 'skip_prompt')
        return texts.get(name, [])

    ctx = SimpleNamespace(
        screen_loader=SimpleNamespace(get_area=lambda screen, name: areas[name]),
        ocr_service=SimpleNamespace(get_ocr_result_list=Mock(side_effect=ocr)),
        controller=SimpleNamespace(click=Mock(return_value=True)),
    )
    detector = DialogueDetector(ctx)
    monkeypatch.setattr(DialogueDetector, '_found', lambda self, screen, s, a: (s, a) in found)
    return detector, ctx, texts, found, np.zeros((1080, 1920, 3), np.uint8)


def word(text, x=1000, y=900):
    return SimpleNamespace(data=text, center=Point(x, y))


@pytest.mark.parametrize('mode', ['跳过剧情', '自动点击', '等待剧情自动播放'])
def test_black_or_unknown_frame_does_not_generate_a_click(dialogue_scene, mode):
    detector, ctx, _, _, frame = dialogue_scene
    assert detector.detect(frame, mode=mode) is None
    ctx.controller.click.assert_not_called()


def test_battle_hud_skips_dialogue_ocr(dialogue_scene):
    detector, ctx, texts, found, frame = dialogue_scene
    found.add(('战斗画面', '按键-普通攻击'))
    texts['文本-剧情右上角'] = [word('跳过')]
    assert detector.detect(frame) is None
    ctx.ocr_service.get_ocr_result_list.assert_not_called()


def test_tracker_text_in_option_region_is_not_dialogue(dialogue_scene):
    detector, _, texts, _, frame = dialogue_scene
    texts['右侧选项区域'] = [word('每日任务')]
    assert detector.detect(frame) is None


def test_tutorial_skip_is_not_story_dialogue(dialogue_scene):
    detector, _, texts, _, frame = dialogue_scene
    texts['玩法引导'] = [word('玩法引导')]
    texts['文本-剧情右上角'] = [word('跳过', 1750, 70)]
    assert detector.detect(frame) is None


def test_current_dialogue_has_a_fixed_game_coordinate(dialogue_scene):
    detector, _, texts, _, frame = dialogue_scene
    texts['对话框内容'] = [word('你好，绳匠。')]
    action = detector.detect(frame, mode='自动点击')
    assert action.kind == 'advance'
    assert action.point.tuple() == (959, 905)
    texts.clear()
    assert detector.detect(frame, mode='自动点击') is None


@pytest.mark.parametrize('option, expected', [('第一个', '选项甲'), ('最后一个', '选项乙')])
def test_choices_require_current_dialogue_evidence(dialogue_scene, option, expected):
    detector, _, texts, _, frame = dialogue_scene
    texts['对话框内容'] = [word('请选择你的回答')]
    texts['右侧选项区域'] = [word('选项乙', 1600, 700), word('选项甲', 1600, 600)]
    action = detector.detect(frame, option=option)
    assert action.kind == 'option' and action.text == expected


def test_skip_button_and_confirmation_are_separate_frames(dialogue_scene):
    detector, _, texts, _, frame = dialogue_scene
    texts['文本-剧情右上角'] = [word('跳过', 1750, 70)]
    assert detector.detect(frame).kind == 'skip'
    texts.clear()
    texts['对话框确认'] = [word('确认', 1120, 650)]
    assert detector.detect(frame) is None
    texts['skip_prompt'] = [word('是否跳过当前剧情？', 960, 400)]
    assert detector.detect(frame).kind == 'confirm_skip'


def test_auto_play_menu_is_not_toggled_again(dialogue_scene):
    detector, _, texts, _, frame = dialogue_scene
    texts['文本-剧情右上角'] = [word('菜单', 1750, 70)]
    texts['按钮-自动'] = [word('自动', 1750, 210)]
    assert detector.detect(frame, mode='等待剧情自动播放').kind == 'menu'
    assert detector.detect(frame, mode='等待剧情自动播放', menu_opened=True).kind == 'auto'
    texts['文本-剧情右上角'] = [word('自动', 1750, 70)]
    texts['对话框内容'] = [word('当前正在自动播放')]
    assert detector.detect(frame, mode='等待剧情自动播放') is None


def test_legacy_commission_no_longer_clicks_after_dialogue_disappears(dialogue_scene):
    from zzz_od.application.commission_assistant.commission_assistant_app import CommissionAssistantApp
    detector, ctx, _, _, frame = dialogue_scene
    app = CommissionAssistantApp.__new__(CommissionAssistantApp)
    app.ctx = ctx
    app.config = SimpleNamespace(story_mode='跳过剧情', dialog_option='最后一个', dialog_click_interval=0.5)
    app.last_screenshot = frame
    app.dialog_clicked = True
    app.chosen_opt = '上次选项'
    app.chosen_opt_last_time = 1
    app.round_retry = Mock()
    app._do_dialog_click(check_center_words=False)
    ctx.controller.click.assert_not_called()
    assert not app.dialog_clicked and app.chosen_opt is None


def test_commission_settings_use_the_commission_file(tmp_path, monkeypatch):
    from onedragon.utils import os_utils
    from zzz_od.application.commission_assistant.commission_assistant_config import CommissionAssistantConfig
    monkeypatch.setattr(os_utils, 'get_path_under_work_dir', lambda *args: str(tmp_path))
    config = CommissionAssistantConfig(0, 'one_dragon')
    assert Path(config.file_path).name == 'commission_assistant.yml'


@pytest.mark.parametrize('name', ['coffee-no-order', 'world-no-dialogue', 'title-keyboard-prompt', 'launch-health-advisory', 'title-login-prompt'])
def test_real_non_dialogue_screens_do_not_generate_actions(dialogue_scene, name):
    import json
    import cv2
    detector, ctx, _, _, _ = dialogue_scene
    base = Path(__file__).parent / 'fixtures/dialogue'
    image = cv2.cvtColor(cv2.imread(str(base / f'{name}.png')), cv2.COLOR_BGR2RGB)
    rows = [SimpleNamespace(data=r['text'], center=Point(r['rect'][0]+r['rect'][2]//2,
                                                      r['rect'][1]+r['rect'][3]//2))
            for r in json.loads((base / f'{name}.json').read_text(encoding='utf-8'))['result']['ocr']]
    ctx.ocr_service = SimpleNamespace(get_ocr_result_list=lambda image, rect, **_: [
        r for r in rows if rect.x1 <= r.center.x < rect.x2 and rect.y1 <= r.center.y < rect.y2])
    ctx.controller.background_mode = True
    for mode in ('自动点击', '跳过剧情', '等待剧情自动播放'):
        assert detector.detect(image, mode=mode) is None
    ctx.controller.click.assert_not_called()
