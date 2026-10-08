"""入口点击后必须核验实际副本；不会把消息成功当作模式成功。"""
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from onedragon.base.geometry.point import Point
from onedragon.base.geometry.rectangle import Rect
from onedragon.base.matcher.ocr.ocr_match_result import OcrMatchResult
from onedragon.base.operation.operation_round_result import OperationRoundResultEnum
from zzz_od.application.hollow_zero.lost_void.lost_void_app import LostVoidApp
from zzz_od.application.hollow_zero.lost_void.mission_screen import (
    menu_matches, detail_mission, mission_text, ENTRY_TITLES, DETAIL_TITLE, DETAIL_ACTIONS)


@pytest.mark.parametrize('text,expected', [('特遣调查', '特遣调查'), ('特 遣 调 查', '特遣调查'),
    ('战线肃清', '战线肃清'), ('特遣任务', None), ('调查战略', None), ('战线肃清 特遣调查', None)])
def test_mode_uses_complete_unique_title(text, expected):
    assert mission_text(text) == expected


def test_menu_and_detail_use_separate_current_frame_regions():
    frame = np.zeros((1080,1920,3), np.uint8)
    menu = [OcrMatchResult(.95, 800,310,180,35,data='特遣调查'),
            OcrMatchResult(.95, 1450,310,180,35,data='战线肃清')]
    detail = [OcrMatchResult(.95, 990,210,240,40,data='战线肃清')]
    bottom = []
    regions = {ENTRY_TITLES:menu, DETAIL_TITLE:detail, DETAIL_ACTIONS:bottom}
    service = Mock(get_ocr_result_list=lambda **kwargs: regions[kwargs['rect']])
    ctx = SimpleNamespace(ocr_service=service)
    assert menu_matches(ctx, frame)['特遣调查'].center.x == 890
    assert detail_mission(ctx, frame) == '战线肃清'
    assert ENTRY_TITLES != DETAIL_TITLE
    bottom.extend([OcrMatchResult(.95,1330,1000,150,40,data='特遣任务'),
                   OcrMatchResult(.95,1620,1000,150,40,data='下一步')])
    assert detail_mission(ctx, frame) == '战线肃清'  # 错误详情的标题优先，不能被按钮覆盖。
    detail.clear()
    assert detail_mission(ctx, frame) == '特遣调查'
    bottom[0].data = '深潜任务'
    assert detail_mission(ctx, frame) is None  # 两个“任务”字不能确认特遣调查。
    bottom[0].data = '特遣任务'
    bottom.pop()
    assert detail_mission(ctx, frame) is None  # 单个按钮不足以确认已进入详情。


@pytest.fixture
def selection(monkeypatch):
    import zzz_od.application.hollow_zero.lost_void.lost_void_app as source
    monkeypatch.setattr(source.time, 'sleep', lambda *_: None)
    app = object.__new__(LostVoidApp)
    app.config = SimpleNamespace(mission_name='特遣调查')
    app.ctx = SimpleNamespace(controller=Mock(background_mode=False), game_config=SimpleNamespace(
        background_gamepad_type='xbox'), screen_loader=Mock(), lost_void=SimpleNamespace(
        challenge_config=SimpleNamespace(choose_team_by_priority=False)))
    app.ctx.controller.click.return_value = True
    app.last_screenshot = np.zeros((1080,1920,3), np.uint8)
    app._mission_returned_from, app._mission_recoveries = None, 0
    app._after_round_wait = lambda **_: None
    app.round_by_goto_screen = Mock(return_value=app.round_success('迷失之地-特遣调查'))
    app.save_screenshot = Mock(return_value='diagnostic.png')
    actual = Mock(return_value=None)
    titles = Mock(return_value={'特遣调查': SimpleNamespace(center=Point(890,330)),
                               '战线肃清': SimpleNamespace(center=Point(1540,330))})
    monkeypatch.setattr(source, 'detail_mission', actual)
    monkeypatch.setattr(source, 'menu_matches', titles)
    return app, actual, titles


def test_entry_uses_actual_title_point_and_waits_for_detail(selection):
    app, actual, _ = selection
    result = app.goto_mission_screen()
    assert result.result == OperationRoundResultEnum.WAIT
    assert app.ctx.controller.click.call_args.args[0].tuple() == (890,330)
    app.ctx.screen_loader.update_current_screen_name.assert_not_called()
    actual.return_value = '特遣调查'
    assert app.goto_mission_screen().is_success
    app.ctx.screen_loader.update_current_screen_name.assert_called_once_with('迷失之地-特遣调查')


@pytest.mark.parametrize('pad', ['xbox', 'ds4'])
@pytest.mark.parametrize('wanted,other,direction', [('特遣调查','战线肃清','right'),
                                                   ('战线肃清','特遣调查','left')])
def test_wrong_mode_recovers_with_gamepad_and_requires_new_title(selection, monkeypatch, pad, wanted, other, direction):
    app, actual, _ = selection
    app.config.mission_name = wanted
    app.ctx.controller.background_mode = True
    app.ctx.game_config.background_gamepad_type = pad
    actual.return_value = other
    assert app.goto_mission_screen().result == OperationRoundResultEnum.WAIT
    back = 'ds4_circle' if pad == 'ds4' else 'xbox_b'
    app.ctx.controller.btn_press.assert_called_once_with(back, press_time=.12)
    actual.return_value = None
    import zzz_od.application.hollow_zero.lost_void.lost_void_app as source
    target = app.config.mission_name
    point = selection[2].return_value[target].center
    other_point = Point(point.x + (600 if direction == 'left' else -600), point.y)
    focus = Mock(return_value=Rect(other_point.x-100, 300, other_point.x+100, 500))
    monkeypatch.setattr(source, 'focused_card', focus)
    assert app.goto_mission_screen().result == OperationRoundResultEnum.WAIT
    assert app.ctx.controller.btn_press.call_args.args[0] == f'{pad}_dpad_{direction}'
    focus.return_value = Rect(point.x-100, 300, point.x+100, 500)
    assert app.goto_mission_screen().result == OperationRoundResultEnum.WAIT
    keys = [call.args[0] for call in app.ctx.controller.btn_press.call_args_list]
    assert keys == [back, f'{pad}_dpad_{direction}', 'ds4_cross' if pad == 'ds4' else 'xbox_a']
    app.ctx.controller.click.assert_not_called()
    actual.return_value = wanted
    assert app.goto_mission_screen().is_success


def test_background_never_confirms_without_current_focus(selection):
    app, _, _ = selection
    app.ctx.controller.background_mode = True
    app.goto_mission_screen()
    app.goto_mission_screen()
    assert all(call.args[0] == 'xbox_dpad_right' for call in app.ctx.controller.btn_press.call_args_list)
    app.ctx.controller.click.assert_not_called()


def test_focus_rejects_gold_strip_and_accepts_protruding_level_circle():
    import cv2
    from zzz_od.application.hollow_zero.lost_void.mission_screen import focused_card
    frame=np.zeros((1080,1920,3), np.uint8)
    cv2.rectangle(frame,(700,370),(1250,390),(240,220,0),-1)
    assert focused_card(frame) is None
    cv2.rectangle(frame,(1455,270),(1770,730),(200,230,0),6)
    cv2.circle(frame,(1730,294),43,(200,230,0),6)
    focus=focused_card(frame)
    assert focus and focus.x1 < 1600 < focus.x2 and focus.y1 < 480 < focus.y2
    cv2.rectangle(frame,(700,300),(1220,505),(200,230,0),6)
    assert focused_card(frame) is None  # 不能任选多个高亮框之一。


def test_cached_screen_name_cannot_confirm_mode(selection):
    app, _actual, titles = selection
    titles.return_value = {}
    result = app.goto_mission_screen()
    assert result.result == OperationRoundResultEnum.RETRY
    assert '详情标题' in result.status


def test_repeated_wrong_mode_fails_before_starting_challenge(selection):
    app, actual, _ = selection
    actual.return_value = '战线肃清'
    app._mission_recoveries = 3
    result = app.goto_mission_screen()
    assert result.is_fail and '设定特遣调查，实际战线肃清' in result.status
    app.ctx.controller.assert_not_called()
    app.ctx.controller.click.assert_not_called()


def test_detail_mismatch_returns_to_selection_before_up_agent_detection(selection, monkeypatch):
    import zzz_od.application.hollow_zero.lost_void.lost_void_app as source
    app, actual, _ = selection
    actual.return_value = '战线肃清'
    match = Mock(side_effect=AssertionError('错误模式禁止继续识别 UP'))
    monkeypatch.setattr(source, 'match_team_agent_template', match)
    assert app.check_for_mission().status == '副本模式不一致'
    match.assert_not_called()


def test_optional_up_agents_do_not_block_configured_team(selection, monkeypatch):
    import zzz_od.application.hollow_zero.lost_void.lost_void_app as source
    app, actual, _ = selection
    actual.return_value = '特遣调查'
    match = Mock(side_effect=AssertionError('未启用 UP 编队时无需检测'))
    monkeypatch.setattr(source, 'match_team_agent_template', match)
    assert app.check_for_mission().is_success
    assert app.priority_agent_list == []
    match.assert_not_called()
