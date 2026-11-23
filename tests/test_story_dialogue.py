import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest
import yaml

from onedragon.base.geometry.point import Point
from onedragon.base.geometry.rectangle import Rect
from zzz_od.application.commission_assistant import story_dialogue as story_module
from zzz_od.application.commission_assistant.commission_assistant_config import StoryMode
from zzz_od.application.commission_assistant.story_dialogue import (
    MODE_AUTO,
    MODE_CLICK,
    MODE_SKIP,
    StoryDialogue,
)


@pytest.fixture
def scene(monkeypatch):
    path = Path(__file__).resolve().parents[1] / 'assets/game_data/screen_info/commission_assistant.yml'
    data = yaml.safe_load(path.read_text(encoding='utf-8'))
    areas = {area['area_name']: SimpleNamespace(rect=Rect(*area['pc_rect'])) for area in data['area_list']}
    texts, found = {}, set()
    clock = {'now': 1000.0}

    def ocr(image, rect, **kwargs):
        extra_regions = {Rect(418, 415, 1500, 615): 'centered_narration',
                         Rect(600, 300, 1320, 780): 'skip_prompt',
                         Rect(418, 155, 1500, 930): 'cinematic_dialogue',
                         Rect(400, 200, 660, 275): 'system_upgrade_title'}
        name = next((name for name, area in areas.items() if area.rect == rect), extra_regions.get(rect))
        return list(texts.get(name, []))

    ctx = SimpleNamespace(
        screen_loader=SimpleNamespace(get_area=lambda screen, name: areas[name]),
        ocr_service=SimpleNamespace(get_ocr_result_list=Mock(side_effect=ocr)),
        controller=SimpleNamespace(background_mode=False),
    )
    core = StoryDialogue(ctx)
    monkeypatch.setattr(StoryDialogue, '_found', lambda self, screen, s, a: (s, a) in found)
    monkeypatch.setattr(story_module.time, 'monotonic', lambda: clock['now'])
    return SimpleNamespace(
        core=core, ctx=ctx, texts=texts, found=found, clock=clock,
        frame=np.zeros((1080, 1920, 3), np.uint8),
    )


def word(text, x=1000, y=900):
    return SimpleNamespace(data=text, center=Point(x, y))


def tick(scene, seconds):
    scene.clock['now'] += seconds


def set_dialogue(scene, body=('你好，绳匠。',), speaker='妮可', controls=('菜单',)):
    scene.texts.clear()
    scene.texts['对话框内容'] = [word(text, 1000, 890 + index * 40)
                                 for index, text in enumerate(body)]
    if speaker is not None:
        scene.texts['对话框标题'] = [word(speaker, 960, 800)]
    if controls:
        scene.texts['文本-剧情右上角'] = [word(label, 1750, 70 + index * 50)
                                          for index, label in enumerate(controls)]


def mode_value(mode):
    return getattr(getattr(mode, 'value', mode), 'value', mode)


def test_attack_hud_is_excluded_before_story_ocr(scene):
    scene.found.add(('战斗画面', '按键-普通攻击'))
    assert scene.core.detect(scene.frame) is None
    scene.ctx.ocr_service.get_ocr_result_list.assert_not_called()
    assert '战斗' in scene.core.status


def test_same_dialogue_advances_after_every_configured_interval(scene):
    set_dialogue(scene, body=('同一句台词。',), controls=('菜单',))
    for _ in range(4):
        action = scene.core.detect(scene.frame, mode=MODE_CLICK, click_interval=0.5)
        assert action is not None
        assert action.kind == 'advance'
        assert action.text == '继续对话'
        assert action.wait == 0.5
        assert action.point.tuple() == (959, 905)
        scene.core.feedback(action, True)

        # 间隔未到：不重复点击，但上一次动作的状态仍可供界面显示。
        assert scene.core.detect(scene.frame, mode=MODE_CLICK, click_interval=0.5) is None
        assert scene.core.status == '继续对话'
        tick(scene, 0.5)


def test_original_story_mode_enum_values_behave_like_strings(scene):
    set_dialogue(scene, body=('模式转换。',), controls=('菜单',))
    for enum_mode in (StoryMode.CLICK, StoryMode.AUTO, StoryMode.SKIP):
        string_mode = mode_value(enum_mode)
        assert string_mode in (MODE_CLICK, MODE_AUTO, MODE_SKIP)

        enum_action = scene.core.detect(scene.frame, mode=enum_mode, click_interval=0.5)
        scene.core.reset()
        string_action = scene.core.detect(scene.frame, mode=string_mode, click_interval=0.5)
        assert enum_action is not None and string_action is not None
        assert (enum_action.kind, enum_action.point.tuple(), enum_action.text, enum_action.wait) == \
               (string_action.kind, string_action.point.tuple(), string_action.text, string_action.wait)


def test_skip_menu_is_clicked_once_and_five_seconds_later_dialogue_advances(scene):
    set_dialogue(scene, body=('先跳过这段。',), controls=('跳过', '菜单'))
    skip = scene.core.detect(scene.frame, mode=MODE_SKIP, click_interval=0.5)
    assert skip is not None and skip.kind == 'skip'
    scene.core.feedback(skip, True)

    scene.texts['文本-剧情右上角'] = [word('菜单', 1750, 70)]
    tick(scene, 0.5)
    menu = scene.core.detect(scene.frame, mode=MODE_SKIP, click_interval=0.5)
    assert menu is not None and menu.kind == 'menu'
    scene.core.feedback(menu, True)
    assert scene.core.status == '等待跳过键和确认框'

    tick(scene, 1.0)
    assert scene.core.detect(scene.frame, mode=MODE_SKIP, click_interval=0.5) is None
    assert scene.core.status == '等待跳过键和确认框'

    tick(scene, 4.1)
    advance = scene.core.detect(scene.frame, mode=MODE_SKIP, click_interval=0.5)
    assert advance is not None and advance.kind == 'advance'
    scene.core.feedback(advance, True)

    # 菜单按钮仍在也不能刷新 5s 计时或再次点菜单；同一句对话继续推进。
    tick(scene, 0.5)
    again = scene.core.detect(scene.frame, mode=MODE_SKIP, click_interval=0.5)
    assert again is not None and again.kind == 'advance'


def test_failed_menu_input_does_not_start_skip_wait_or_mark_menu_opened(scene):
    set_dialogue(scene, body=('菜单还没点上。',), controls=('菜单',))
    menu = scene.core.detect(scene.frame, mode=MODE_SKIP, click_interval=0.5)
    assert menu is not None and menu.kind == 'menu'
    scene.core.feedback(menu, False)

    tick(scene, 0.5)
    retry = scene.core.detect(scene.frame, mode=MODE_SKIP, click_interval=0.5)
    assert retry is not None and retry.kind == 'menu'


def test_skip_confirmation_needs_an_explicit_skip_prompt(scene):
    scene.core.reset()
    scene.texts.clear()
    scene.texts['对话框确认'] = [word('确认', 1120, 650)]
    scene.texts['skip_prompt'] = [word('是否跳过当前剧情？', 960, 400)]
    confirmation = scene.core.detect(scene.frame, mode=MODE_SKIP)
    assert confirmation is not None and confirmation.kind == 'confirm_skip'
    assert confirmation.point.tuple() == (1120, 650)

    scene.core.reset()
    scene.texts['skip_prompt'] = [word('是否花费160菲林购买？', 960, 400)]
    assert scene.core.detect(scene.frame, mode=MODE_SKIP) is None

    scene.core.reset()
    scene.texts['skip_prompt'] = [word('确认跳过动画需要购买', 960, 400)]
    assert scene.core.detect(scene.frame, mode=MODE_SKIP) is None

    scene.core.reset()
    assert scene.core.detect(scene.frame, mode=MODE_CLICK) is None


def test_named_story_skip_confirmation_after_click(scene):
    set_dialogue(scene, controls=('跳过', '菜单'))
    skip = scene.core.detect(scene.frame, mode=MODE_SKIP)
    assert skip is not None and skip.kind == 'skip'
    scene.core.feedback(skip, True)
    tick(scene, .6)
    scene.texts.clear()
    scene.texts['skip_prompt'] = [word('是否跳过「告别」的剧情？', 954, 487)]
    scene.texts['对话框确认'] = [word('确认', 1130, 663)]
    confirmation = scene.core.detect(scene.frame, mode=MODE_SKIP)
    assert confirmation is not None and confirmation.kind == 'confirm_skip'
    assert confirmation.point.tuple() == (1130, 663)


def test_skip_button_wins_over_choices_in_skip_mode(scene):
    set_dialogue(scene, body=('先跳过。',), controls=('跳过', '菜单'))
    scene.texts['右侧选项区域'] = [word('选项甲', 1600, 600), word('选项乙', 1600, 700)]
    action = scene.core.detect(scene.frame, mode=MODE_SKIP, option='第一个')
    assert action is not None and action.kind == 'skip'


def test_narration_without_speaker_advances(scene):
    set_dialogue(scene, body=('旁白：夜风穿过空巷。',), speaker=None, controls=('菜单',))
    action = scene.core.detect(scene.frame, mode=MODE_CLICK)
    assert action is not None and action.kind == 'advance'



def test_subtitle_only_blackout_advances_without_selecting_options(scene):
    set_dialogue(scene, body=('「From：伊瑟尔德。To：铃小姐。',), speaker=None, controls=())
    scene.texts['右侧选项区域'] = [word('装饰文字', 1600, 700)]
    action = scene.core.detect(scene.frame, mode=MODE_SKIP)
    assert action is not None and action.kind == 'advance'
    assert action.point.tuple() == (959, 905)


@pytest.mark.parametrize('overlay', ['gray_scene', 'confirmation', 'detail_page'])
def test_unlabeled_text_does_not_advance_on_other_screens(scene, overlay):
    set_dialogue(scene, body=('请阅读以下详情。',), speaker=None, controls=())
    if overlay == 'gray_scene':
        scene.frame[:770] = (160, 160, 160)
    elif overlay == 'confirmation':
        scene.texts['对话框确认'] = [word('确认', 1130, 663)]
    else:
        scene.found.add(('委托助手', '左上角返回'))
    assert scene.core.detect(scene.frame, mode=MODE_SKIP) is None


@pytest.mark.parametrize('overlay', [None, 'scene', 'confirmation', 'menu'])
def test_centered_black_intertitle_advances_only_on_clean_blackout(scene, overlay):
    scene.texts['centered_narration'] = [
        word('事情以「人类体会不了」的方式圆满落幕了？', 953, 484),
        word('委托布转身离开，步履轻松。', 819, 537),
    ]
    if overlay == 'scene':
        scene.frame[200:400, 100:600] = 80
    elif overlay == 'confirmation':
        scene.texts['对话框确认'] = [word('确认', 1130, 663)]
    elif overlay == 'menu':
        scene.texts['centered_narration'].append(word('取消', 960, 603))
    action = scene.core.detect(scene.frame, mode=MODE_SKIP)
    if overlay is None:
        assert action is not None and action.kind == 'advance'
        assert action.point.tuple() == (959, 905)
    else:
        assert action is None


def test_centered_intertitle_with_menu_tries_skip_then_advances(scene):
    scene.frame[115:151, 1732:1792] = 255  # The top-right menu is bright on the black screen.
    scene.texts['文本-剧情右上角'] = [word('菜单', 1762, 133)]
    scene.texts['centered_narration'] = [word('不久后，和凯撒等人悄悄来到了人影附近', 925, 541)]
    scene.texts['右侧选项区域'] = [word('装饰文字', 1600, 700)]
    menu = scene.core.detect(scene.frame, mode=MODE_SKIP)
    assert menu is not None and menu.kind == 'menu'
    scene.core.feedback(menu, True)
    tick(scene, 1)
    assert scene.core.detect(scene.frame, mode=MODE_SKIP) is None
    tick(scene, 4.1)
    action = scene.core.detect(scene.frame, mode=MODE_SKIP)
    assert action is not None and action.kind == 'advance'
    scene.frame[150:410, 1610:1810] = 90  # Expanded menu extends below the top-right label.
    scene.texts['文本-剧情右上角'] = [word('跳过', 1762, 133)]
    action = scene.core.detect(scene.frame, mode=MODE_SKIP)
    assert action is not None and action.kind == 'skip'


def test_native_centered_intertitle_clicks_its_visible_continue_marker(scene):
    scene.texts['centered_narration'] = [word('新艾利都，雅努斯区十四分街。', 960, 512)]
    for x in (942, 961):
        vertices = np.array([[x, 561], [x+8, 561], [x+17, 572],
                             [x+8, 582], [x, 582], [x+8, 572]], np.int32)
        cv2.fillPoly(scene.frame, [vertices], (160, 160, 160))
    action = scene.core.detect(scene.frame, mode=MODE_CLICK, source_size=(3024, 1898))
    assert action is not None and action.kind == 'advance'
    assert action.point.tuple() == (960, 572)


def test_native_npc_name_below_reference_title_area_enables_dialogue(scene):
    rows = [word('喵吉', 960, 843), word('祝你度过愉快的一天！', 962, 943)]
    scene.ctx.ocr_service.get_ocr_result_list.side_effect = lambda image, rect, **_: [
        row for row in rows if rect.x1 <= row.center.x < rect.x2 and rect.y1 <= row.center.y < rect.y2]
    scene.frame[:850] = (125, 155, 185)  # Ordinary street scene above the dialogue box.
    scene.frame[853:990, 415:1510] = (33, 33, 33)
    action = scene.core.detect(scene.frame, source_size=(3024, 1898))
    assert action is not None and action.kind == 'advance'
    assert action.point.tuple() == (959, 923)


@pytest.mark.parametrize('icon', [False, True])
def test_native_skip_requires_story_evidence_for_a_lone_label(scene, icon):
    rows = [word('跳过', 1762, 173)]
    scene.ctx.ocr_service.get_ocr_result_list.side_effect = lambda image, rect, **_: [
        row for row in rows if rect.x1 <= row.center.x < rect.x2 and rect.y1 <= row.center.y < rect.y2]
    if icon:
        cv2.ellipse(scene.frame, (1656, 174), (15, 13), 0, 0, 360, (255, 120, 0), -1)
        cv2.rectangle(scene.frame, (1653, 167), (1659, 180), (0, 0, 0), -1)
    action = scene.core.detect(scene.frame, source_size=(3024, 1898))
    if icon:
        assert action is not None and action.kind == 'skip'
        assert action.point.tuple() == (1762, 173)
    else:
        assert action is None


@pytest.mark.parametrize('obstruction', [None, 'no_bar', 'dialog', 'world', 'no_text', 'no_control'])
def test_letterboxed_dialogue_enters_skip_flow(scene, obstruction):
    scene.frame[135:945] = (172, 102, 4)
    scene.texts['文本-剧情右上角'] = [word('菜单', 1763, 132)]
    scene.texts['cinematic_dialogue'] = [word('呵，不过无聊也是好事。', 878, 214),
                                      word('行了，至少能有几年不用', 1308, 806),
                                      word('为火湖的事操心了。', 1275, 848)]
    if obstruction == 'no_bar':
        scene.frame[980:1040] = 80
    elif obstruction == 'dialog':
        scene.texts['cinematic_dialogue'].append(word('确认', 1130, 663))
    elif obstruction == 'world':
        scene.found.add(('大世界-普通', '按钮-菜单'))
    elif obstruction == 'no_text':
        del scene.texts['cinematic_dialogue']
    elif obstruction == 'no_control':
        del scene.texts['文本-剧情右上角']
    action = scene.core.detect(scene.frame, mode=MODE_SKIP)
    if obstruction is not None:
        assert action is None
        return
    assert action is not None and action.kind == 'menu'
    scene.core.feedback(action, True)
    scene.texts['文本-剧情右上角'] = [word('跳过', 1762, 133)]
    tick(scene, .6)
    action = scene.core.detect(scene.frame, mode=MODE_SKIP)
    assert action is not None and action.kind == 'skip'
    scene.texts['文本-剧情右上角'] = [word('菜单', 1763, 132)]
    scene.texts['右侧选项区域'] = [word('场景文字', 1600, 700)]
    tick(scene, 5)
    action = scene.core.detect(scene.frame, mode=MODE_SKIP)
    assert action is not None and action.kind == 'advance'


def test_dialogue_with_speaker_but_no_visible_controls_advances(scene):
    set_dialogue(scene, body=('只有说话人和正文。',), speaker='妮可', controls=())
    action = scene.core.detect(scene.frame, mode=MODE_CLICK, click_interval=0.6)
    assert action is not None and action.kind == 'advance'


@pytest.mark.parametrize('mode', [MODE_CLICK, MODE_AUTO, MODE_SKIP])
def test_nameless_dialogue_requires_a_framed_textbox_and_no_confirmation(scene, mode):
    set_dialogue(scene, body=('他原先站岗的位置空无一人。',), speaker=None, controls=())
    scene.frame[:] = (166, 115, 75)
    scene.frame[833:1024, 406:1515] = (30, 20, 10)
    scene.frame[826:833, 400:1523] = (39, 36, 39)
    scene.frame[833:1024, 397:406] = (34, 33, 34)
    # A dark text area with a partial border is not enough.
    assert scene.core.detect(scene.frame, mode=mode) is None

    scene.frame[833:1024, 1516:1523] = (34, 33, 34)
    scene.texts['对话框确认'] = [word('确认')]
    assert scene.core.detect(scene.frame, mode=mode) is None
    scene.texts['对话框确认'] = []

    scene.found.add(('大世界-普通', '按钮-菜单'))
    assert scene.core.detect(scene.frame, mode=mode) is None
    scene.found.clear()
    action = scene.core.detect(scene.frame, mode=mode)
    assert action is not None and action.kind == 'advance'
    assert action.point.tuple() == (959, 905)


def test_ellipsis_dialogue_before_text_appears_advances(scene):
    set_dialogue(scene, body=('......',), speaker=None, controls=('菜单',))
    action = scene.core.detect(scene.frame, mode=MODE_CLICK)
    assert action is not None and action.kind == 'advance'


@pytest.mark.parametrize('mode', [MODE_CLICK, MODE_AUTO, MODE_SKIP])
def test_speaker_with_unread_ellipsis_advances_but_blank_body_does_not(scene, mode):
    set_dialogue(scene, body=(), speaker='普莱尔', controls=())
    frame = scene.frame
    frame[:] = (166, 115, 75)
    frame[826:1024, 397:1523] = (34, 33, 34)
    frame[833:1024, 406:1515] = (30, 20, 10)
    assert scene.core.detect(frame, mode=mode) is None

    for x in range(933, 988, 10):
        frame[928:934, x:x + 6] = 255
    frame[928:934, 983:989] = (30, 20, 10)
    frame[938:944, 983:989] = 255
    assert scene.core.detect(frame, mode=mode) is None

    frame[938:944, 983:989] = (30, 20, 10)
    frame[928:934, 983:989] = 255
    scene.texts['对话框确认'] = [word('确认')]
    assert scene.core.detect(frame, mode=mode) is None
    scene.texts['对话框确认'] = []
    action = scene.core.detect(frame, mode=mode)
    assert action is not None and action.kind == 'advance'
    assert action.point.tuple() == (959, 905)


def test_chinese_text_alone_is_not_a_dialogue(scene):
    scene.texts.clear()
    scene.texts['对话框内容'] = [word('材料不足', 1000, 890), word('确定', 1000, 930)]
    assert scene.core.detect(scene.frame, mode=MODE_CLICK) is None
    assert scene.core.detect(scene.frame, mode=MODE_SKIP) is None


@pytest.mark.parametrize('mode', [MODE_CLICK, MODE_AUTO, MODE_SKIP])
def test_character_selection_menu_is_not_a_dialogue_even_after_story(scene, mode):
    set_dialogue(scene, body=('上一句对白。',), controls=())
    action = scene.core.detect(scene.frame, mode=mode)
    assert action is not None and action.kind == 'advance'
    scene.core.feedback(action, True)
    tick(scene, .6)

    set_dialogue(scene, body=('切换角色',), speaker='派派', controls=())
    scene.texts['右侧选项区域'] = [word('潘引壶', 1539, 563), word('格莉丝', 1540, 796)]
    scene.found.add(('委托助手', '左上角返回'))
    assert scene.core.detect(scene.frame, mode=mode) is None

    # Closing a menu into a black transition must not re-use the old story session.
    scene.found.clear()
    scene.texts.clear()
    tick(scene, .6)
    assert scene.core.detect(scene.frame, mode=mode) is None


@pytest.mark.parametrize('mode', [MODE_CLICK, MODE_AUTO, MODE_SKIP])
@pytest.mark.parametrize('button_text', ['优化', '完成优化'])
def test_system_upgrade_popup_never_advances_even_after_dialogue(scene, mode, button_text):
    set_dialogue(scene, body=('说完了。',), speaker='妮可', controls=())
    action = scene.core.detect(scene.frame, mode=mode)
    assert action is not None and action.kind == 'advance'
    scene.core.feedback(action, True)
    tick(scene, .6)
    set_dialogue(scene, body=(button_text,), speaker='系统优化后可解锁新的等级上限', controls=())
    scene.texts['system_upgrade_title'] = [word('系统优化', 503, 240)]
    assert scene.core.detect(scene.frame, mode=mode) is None
    scene.texts.clear()
    assert scene.core.detect(scene.frame, mode=mode) is None


@pytest.mark.parametrize('option, expected', [('第一个', '选项甲'), ('最后一个', '选项乙')])
def test_choices_need_current_dialogue_and_honor_first_last(scene, option, expected):
    set_dialogue(scene, body=('请选择你的回答。',), controls=('菜单',))
    scene.texts['右侧选项区域'] = [word('选项乙', 1600, 700), word('选项甲', 1600, 600)]
    action = scene.core.detect(scene.frame, mode=MODE_CLICK, option=option)
    assert action is not None and action.kind == 'option' and action.text == expected


def test_option_region_without_dialogue_is_ignored(scene):
    scene.texts.clear()
    scene.texts['右侧选项区域'] = [word('每日任务', 1600, 600)]
    assert scene.core.detect(scene.frame, mode=MODE_CLICK) is None


def test_selected_option_is_reclicked_then_replaced_after_two_seconds(scene):
    set_dialogue(scene, body=('请选择你的回答。',), controls=('菜单',))
    scene.texts['右侧选项区域'] = [word('选项甲', 1600, 600), word('选项乙', 1600, 700)]
    first = scene.core.detect(scene.frame, mode=MODE_CLICK, option='最后一个')
    assert first is not None and first.text == '选项乙'
    scene.core.feedback(first, True)

    tick(scene, 0.5)
    protected = scene.core.detect(scene.frame, mode=MODE_CLICK, option='最后一个')
    assert protected is not None and protected.text == '选项乙'
    scene.core.feedback(protected, True)

    tick(scene, 1.1)
    still_protected = scene.core.detect(scene.frame, mode=MODE_CLICK, option='最后一个')
    assert still_protected is not None and still_protected.text == '选项乙'
    scene.core.feedback(still_protected, True)

    tick(scene, 1.0)
    replacement = scene.core.detect(scene.frame, mode=MODE_CLICK, option='最后一个')
    assert replacement is not None and replacement.text == '选项甲'


def test_selected_option_is_reclicked_when_ocr_temporarily_loses_it(scene):
    set_dialogue(scene, body=('请选择你的回答。',), controls=('菜单',))
    scene.texts['右侧选项区域'] = [word('选项甲', 1600, 600), word('选项乙', 1600, 700)]
    first = scene.core.detect(scene.frame, mode=MODE_CLICK)
    assert first is not None and first.text == '选项乙'
    scene.core.feedback(first, True)

    # 点击动画会让按钮短暂变透明，保护期内继续重按刚才的选项。
    scene.texts['右侧选项区域'] = []
    tick(scene, 0.5)
    protected = scene.core.detect(scene.frame, mode=MODE_CLICK)
    assert protected is not None and protected.kind == 'option' and protected.text == '选项乙'


def test_auto_mode_still_selects_choices_while_auto_marker_is_visible(scene):
    set_dialogue(scene, body=('自动播放中也要选。',), controls=('自动',))
    scene.texts['右侧选项区域'] = [word('选项甲', 1600, 600), word('选项乙', 1600, 700)]
    action = scene.core.detect(scene.frame, mode=MODE_AUTO, option='最后一个')
    assert action is not None and action.kind == 'option' and action.text == '选项乙'


@pytest.mark.parametrize('background', [True, False])
def test_option_ocr_keeps_focused_choice_regardless_of_global_mode(scene, background):
    set_dialogue(scene, body=('请选择你的回答。',), controls=('菜单',))
    scene.ctx.controller.background_mode = background
    option_area = scene.ctx.screen_loader.get_area(None, '右侧选项区域').rect
    base_ocr = scene.ctx.ocr_service.get_ocr_result_list

    def ocr(image, rect, color_range=None, **kwargs):
        if rect == option_area:
            # 白字蒙版只读到未选中的行，完整 OCR 才包含当前黄色焦点。
            return [word('选项甲', 1600, 600)] if color_range is not None else [
                word('选项甲', 1600, 600), word('选项乙', 1600, 700)]
        return base_ocr(image, rect, color_range=color_range, **kwargs)

    scene.ctx.ocr_service = SimpleNamespace(get_ocr_result_list=ocr)
    action = scene.core.detect(scene.frame, mode=MODE_CLICK, option='最后一个')
    assert action is not None and action.text == '选项乙'


def test_option_stall_timer_survives_a_temporary_ocr_gap(scene):
    set_dialogue(scene, body=('请选择你的回答。',), controls=('菜单',))
    scene.texts['右侧选项区域'] = [word('选项甲', 1600, 600), word('选项乙', 1600, 700)]
    first = scene.core.detect(scene.frame, mode=MODE_CLICK, option='最后一个')
    assert first is not None and first.text == '选项乙'
    scene.core.feedback(first, True)

    scene.texts['右侧选项区域'] = []
    tick(scene, 0.5)
    protected = scene.core.detect(scene.frame, mode=MODE_CLICK, option='最后一个')
    assert protected is not None and protected.text == '选项乙'
    scene.core.feedback(protected, True)

    scene.texts['右侧选项区域'] = [word('选项甲', 1600, 600), word('选项乙', 1600, 700)]
    tick(scene, 2.1)
    replacement = scene.core.detect(scene.frame, mode=MODE_CLICK, option='最后一个')
    assert replacement is not None and replacement.text == '选项甲'


def test_single_option_that_does_not_react_is_not_clicked_forever(scene):
    set_dialogue(scene, body=('只剩一个选项。',), controls=('菜单',))
    scene.texts['右侧选项区域'] = [word('选项乙', 1600, 700)]
    first = scene.core.detect(scene.frame, mode=MODE_CLICK)
    assert first is not None and first.text == '选项乙'
    scene.core.feedback(first, True)

    tick(scene, 2.6)
    assert scene.core.detect(scene.frame, mode=MODE_CLICK) is None
    assert '选项' in scene.core.status

    tick(scene, 0.5)
    assert scene.core.detect(scene.frame, mode=MODE_CLICK) is None


@pytest.mark.parametrize('option,expected', [('最后一个', '否'), ('第一个', '是')])
def test_single_character_options_are_selectable(scene, option, expected):
    set_dialogue(scene, body=('要一起去吗？',), controls=('菜单',))
    scene.texts['右侧选项区域'] = [word('是', 1600, 600), word('否', 1600, 700)]
    action = scene.core.detect(scene.frame, mode=MODE_CLICK, option=option)
    assert action is not None and action.kind == 'option' and action.text == expected


@pytest.mark.parametrize('sensitive', ['确认购买', '充值水晶', '解锁角色', '消耗菲林'])
def test_sensitive_options_are_never_selected(scene, sensitive):
    set_dialogue(scene, body=('请选择你的回答。',), controls=('菜单',))
    scene.texts['右侧选项区域'] = [word('选项甲', 1600, 600), word(sensitive, 1600, 700)]
    assert scene.core.detect(scene.frame, mode=MODE_CLICK, option='最后一个') is None
    assert '人工' in scene.core.status


def test_unknown_transition_grace_stops_after_five_rounds(scene):
    set_dialogue(scene, body=('第一句。',), speaker='妮可', controls=('菜单',))
    action = scene.core.detect(scene.frame, mode=MODE_CLICK)
    assert action is not None and action.kind == 'advance'
    scene.core.feedback(action, True)

    scene.texts.clear()
    for _ in range(5):
        tick(scene, 0.5)
        action = scene.core.detect(scene.frame, mode=MODE_CLICK)
        assert action is not None and action.kind == 'advance'
        scene.core.feedback(action, True)

    tick(scene, 0.5)
    assert scene.core.detect(scene.frame, mode=MODE_CLICK) is None
    assert scene.core.status == '等待对话画面'
    # 会话结束后同一帧不会继续补点，等真正的新对话再开始。
    tick(scene, 0.5)
    assert scene.core.detect(scene.frame, mode=MODE_CLICK) is None


def test_colorful_world_frame_after_dialogue_gets_no_grace_click(scene):
    set_dialogue(scene, body=('上一句。',), controls=('菜单',))
    action = scene.core.detect(scene.frame, mode=MODE_CLICK)
    assert action is not None
    scene.core.feedback(action, True)

    scene.texts.clear()
    colorful = np.full((1080, 1920, 3), (255, 0, 0), np.uint8)
    tick(scene, 0.5)
    assert scene.core.detect(colorful, mode=MODE_CLICK) is None
    assert scene.core.detect(colorful, mode=MODE_CLICK) is None


def test_live_skip_frame_menu_beats_decorative_center_text(scene):
    scene.texts.clear()
    scene.texts['文本-剧情右上角'] = [word('菜单', 1736, 117)]
    scene.texts['中间选项区域'] = [word('辉集', 868, 306), word('店铺', 900, 500),
                                   word('ooi', 934, 633)]
    scene.texts['对话框标题'] = [word('伊瑟尔德', 910, 786)]
    scene.texts['对话框内容'] = [
        word('其能够容纳和孕育「牲鬼」的特性，由奥波勒斯小队首次发现，也在其他部队', 474, 878),
        word('的后续行动中得到证实……', 476, 919),
    ]

    action = scene.core.detect(scene.frame, mode=MODE_SKIP)
    assert action is not None and action.kind == 'menu'
    scene.core.feedback(action, True)

    tick(scene, 5.1)
    fallback = scene.core.detect(scene.frame, mode=MODE_SKIP)
    assert fallback is not None and fallback.kind == 'advance'


def test_auto_mode_opens_menu_then_clicks_auto_button(scene):
    set_dialogue(scene, body=('自动播放。',), controls=('菜单',))
    scene.texts['按钮-自动'] = [word('自动', 1750, 210)]
    menu = scene.core.detect(scene.frame, mode=MODE_AUTO, click_interval=0.5)
    assert menu is not None and menu.kind == 'menu'
    scene.core.feedback(menu, True)

    tick(scene, 0.5)
    auto = scene.core.detect(scene.frame, mode=MODE_AUTO, click_interval=0.5)
    assert auto is not None and auto.kind == 'auto'
    scene.core.feedback(auto, True)

    scene.texts['文本-剧情右上角'] = [word('自动', 1750, 70)]
    tick(scene, 0.5)
    assert scene.core.detect(scene.frame, mode=MODE_AUTO, click_interval=0.5) is None
    assert scene.core.status == '剧情自动播放中'


def test_isolated_story_button_is_not_story_evidence(scene):
    for label in ('跳过', '菜单', '自动'):
        scene.core.reset()
        scene.texts.clear()
        scene.texts['文本-剧情右上角'] = [word(label, 1750, 70)]
        assert scene.core.detect(scene.frame, mode=MODE_SKIP) is None
        assert scene.core.detect(scene.frame, mode=MODE_CLICK) is None


def test_tutorial_is_not_story_dialogue(scene):
    set_dialogue(scene, body=('玩法引导',), controls=('跳过',))
    scene.texts['玩法引导'] = [word('玩法引导', 450, 250)]
    assert scene.core.detect(scene.frame, mode=MODE_SKIP) is None
    assert '玩法引导' in scene.core.status


def test_reset_clears_policy_and_status(scene):
    set_dialogue(scene, body=('选择后重置。',), controls=('菜单',))
    scene.texts['右侧选项区域'] = [word('选项甲', 1600, 600), word('选项乙', 1600, 700)]
    action = scene.core.detect(scene.frame, mode=MODE_CLICK, option='最后一个')
    assert action is not None
    scene.core.feedback(action, True)
    assert scene.core.status != '等待对话画面'

    scene.core.reset()
    assert scene.core.status == '等待对话画面'
    fresh = scene.core.detect(scene.frame, mode=MODE_CLICK, option='最后一个')
    assert fresh is not None and fresh.text == '选项乙'


def _load_fixture(scene, name):
    base = Path(__file__).parent / 'fixtures/dialogue'
    image = cv2.cvtColor(cv2.imread(str(base / f'{name}.png')), cv2.COLOR_BGR2RGB)
    rows = [word(row['text'],
                 row['rect'][0] + row['rect'][2] // 2,
                 row['rect'][1] + row['rect'][3] // 2)
            for row in json.loads(
                (base / f'{name}.json').read_text(encoding='utf-8'))['result']['ocr']]
    scene.ctx.ocr_service = SimpleNamespace(get_ocr_result_list=lambda image, rect, **_: [
        row for row in rows
        if rect.x1 <= row.center.x < rect.x2 and rect.y1 <= row.center.y < rect.y2])
    return image


@pytest.mark.parametrize('name', ['coffee-no-order', 'world-no-dialogue', 'title-keyboard-prompt',
                                  'launch-health-advisory', 'title-login-prompt',
                                  'skill-upgrade-insufficient'])
def test_real_non_dialogue_screens_do_not_generate_actions(scene, name):
    image = _load_fixture(scene, name)
    for mode in (MODE_CLICK, MODE_SKIP, MODE_AUTO):
        scene.core.reset()
        assert scene.core.detect(image, mode=mode) is None


@pytest.mark.parametrize('name, kind', [('story-skip-mouse-prompts', 'skip'),
                                       ('story-skip-pad-prompts', 'skip'),
                                       ('story-skip-confirm-pad', 'confirm_skip')])
def test_real_story_frames_keep_skip_actions(scene, name, kind):
    image = _load_fixture(scene, name)
    action = scene.core.detect(image, mode=MODE_SKIP)
    assert action is not None and action.kind == kind
