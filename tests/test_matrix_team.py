"""矩阵行动编队状态机回归；截图、滚动和点击均使用替身。"""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from onedragon.base.geometry.point import Point
from zzz_od.application.hollow_zero.lost_void.lost_void_app import LostVoidApp
from zzz_od.application.hollow_zero.lost_void.matrix_team import resolve_agent_ids


@pytest.mark.parametrize('values', [[], ['unknown'], ['anby', '安比'], ['missing'],
                                  ['anby'] * 4, 'anby', [{}]])
def test_invalid_team_rejected(values):
    with pytest.raises(ValueError):
        resolve_agent_ids(values)


def test_team_accepts_names_and_ids_in_slot_order():
    assert resolve_agent_ids(['安比', 'unknown', 'nicole']) == ['anby', 'nicole']


@pytest.fixture
def matrix(monkeypatch):
    app = object.__new__(LostVoidApp)
    app.config = SimpleNamespace(mission_name='矩阵行动', matrix_team_mode='自定义编队',
                                 matrix_agent_1='anby', matrix_agent_2='nicole', matrix_agent_3='nekomata')
    main = SimpleNamespace(rect=SimpleNamespace(center=Point(1500, 200)), kind='main')
    agents = SimpleNamespace(rect=SimpleNamespace(), kind='agents')
    world = {'page': 3, 'roster': ['ellen'], 'frame': 0, 'clicks': [], 'scrolls': [],
             'missing': set(), 'bad_click': False}
    pages = {'anby': 2, 'nicole': 1, 'nekomata': 0}
    ctx = SimpleNamespace(
        run_context=SimpleNamespace(is_context_stop=False, is_context_running=True),
        lost_void=SimpleNamespace(predefined_team_idx=4,
                                 challenge_config=SimpleNamespace(manually_choose_agent=False, team_info=['ellen'])),
        template_loader=SimpleNamespace(get_template=Mock(return_value=object())),
        screen_loader=SimpleNamespace(get_area=lambda _s, name: main if name == '主战编队槽' else agents),
    )
    def click(point):
        world['clicks'].append(point)
        if point.x == 1000:
            world['roster'].pop(0)
        elif point.x < 1000:
            # 点击坐标只属于当前截图，历史坐标会立刻使测试失败。
            assert point.y == world['frame']
            target = app._matrix_selection['target'][app._matrix_selection['index']]
            world['roster'].append('ellen' if world['bad_click'] else target)
        return True
    ctx.controller = SimpleNamespace(click=Mock(side_effect=click))
    ctx.ocr_service = SimpleNamespace(get_ocr_result_list=lambda **kwargs: [
        SimpleNamespace(data='主战', center=Point(1000, 200)) for _ in world['roster']])
    app.ctx = ctx
    app._matrix_selection = None
    app._after_round_wait = lambda **kwargs: None
    def scroll(_screen, _area, direction):
        world['scrolls'].append(direction)
        world['page'] = max(0, world['page'] + (1 if direction == 'down' else -1))
    app.scroll_area = scroll
    def match(_ctx, screen, rect, target=None):
        assert screen['frame'] == world['frame']
        if rect is main.rect:
            return [SimpleNamespace(data=SimpleNamespace(agent_id=aid), confidence=1,
                                    center=Point(1100 + index * 150, 200))
                    for index, aid in enumerate(screen['roster'])]
        aid = target[0]
        if aid in world['missing'] or pages[aid] != screen['page']:
            return []
        return [SimpleNamespace(data=SimpleNamespace(agent_id=aid), confidence=1,
                                center=Point(200, screen['frame']))]
    monkeypatch.setattr('zzz_od.application.hollow_zero.lost_void.lost_void_app.match_team_agent_template', match)
    def frame():
        world['frame'] += 1
        app.last_screenshot = {'frame': world['frame'], 'page': world['page'], 'roster': list(world['roster'])}
    return app, world, frame


def run_selection(matrix):
    app, world, frame = matrix
    for _ in range(65):
        frame()
        result = app.matrix_select_agent()
        if result.is_fail or result.is_success:
            return result
    pytest.fail('选人状态机未在有限轮次内结束')


def test_custom_team_uses_fresh_frames_and_verifies_order(matrix):
    app, world, frame = matrix
    assert app.matrix_click_preset_team().status == '手动选取角色'
    assert app.ctx.lost_void.predefined_team_idx == -1
    result = run_selection(matrix)
    assert result.is_success
    assert world['roster'] == ['anby', 'nicole', 'nekomata']
    assert 'up' in world['scrolls'] and 'down' in world['scrolls']
    frame()
    app.round_by_find_and_click_area = Mock(return_value=app.round_success())
    assert app.matrix_start_challenge().is_success
    app.round_by_find_and_click_area.assert_called_once()


def test_missing_or_wrong_role_does_not_start_challenge(matrix):
    app, world, frame = matrix
    world['missing'].add('nicole')
    result = run_selection(matrix)
    assert result.is_fail and '未找到指定角色' in result.status
    frame()
    app.round_by_find_and_click_area = Mock()
    assert app.matrix_start_challenge().is_fail
    app.round_by_find_and_click_area.assert_not_called()


def test_wrong_click_stops_without_repeated_role_clicks(matrix):
    app, world, _frame = matrix
    world['bad_click'] = True
    assert run_selection(matrix).is_fail
    assert len([point for point in world['clicks'] if point.x < 1000]) == 1


def test_missing_template_and_invalid_team_do_not_clear_current_team(matrix):
    app, world, frame = matrix
    app.ctx.template_loader.get_template.return_value = None
    frame()
    assert app.matrix_select_agent().is_fail
    assert not world['clicks'] and world['roster'] == ['ellen']
    app.config.matrix_agent_2 = 'anby'
    assert app.matrix_select_agent().is_fail
    assert not world['clicks']


def test_pause_and_stop_issue_no_inputs(matrix):
    app, world, frame = matrix
    app.ctx.run_context.is_context_running = False
    frame()
    assert not app.matrix_select_agent().is_success
    app.ctx.run_context.is_context_stop = True
    assert app.matrix_select_agent().is_fail
    assert not world['clicks'] and not world['scrolls']


def test_legacy_challenge_team_remains_supported(matrix):
    app, world, _frame = matrix
    app.config.matrix_team_mode = '沿用挑战配置'
    app.ctx.lost_void.challenge_config.manually_choose_agent = True
    app.ctx.lost_void.challenge_config.team_info = ['安比', 'nicole']
    assert app.matrix_click_preset_team().is_success
    assert run_selection(matrix).is_success
    assert world['roster'] == ['anby', 'nicole']


def test_custom_team_clears_previous_preset_before_battle_initialization(matrix):
    app, _world, _frame = matrix
    app.run_record = SimpleNamespace(is_finished_by_day=False)
    app.config.challenge_config = '默认-成就模式'
    app.ctx.lost_void.init_before_run = Mock()
    assert app.init_for_lost_void().is_success
    assert app.ctx.lost_void.predefined_team_idx == -1
    app.ctx.lost_void.init_before_run.assert_called_once()
