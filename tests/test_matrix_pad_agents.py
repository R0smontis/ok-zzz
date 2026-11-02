"""真实矩阵截图识别 + 真实头像模板；仅模拟按键后网格、槽位的下一帧变化。"""
import json
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import pytest

from onedragon.base.geometry.rectangle import Rect
from onedragon.base.operation.operation_round_result import OperationRoundResultEnum as R
from onedragon.base.screen.template_loader import TemplateLoader
from src.navigation.common import focus_mask, in_rect, norm_text
from zzz_od.application.hollow_zero.lost_void import matrix_pad_agents as agents
from zzz_od.application.hollow_zero.lost_void import matrix_screen
from zzz_od.application.hollow_zero.lost_void.lost_void_app import LostVoidApp
from zzz_od.operation.agent_template_matcher import match_team_agent_template

FIXTURES = Path(__file__).parent / 'fixtures' / 'lost_void'
ORIGINAL = ['claret', 'roxy', 'rina']
TARGET = ['rina', 'manato', 'caesar_king']
CARD_POSITIONS = {'manato': (0, 0), 'rina': (0, 1), 'caesar_king': (0, 2),
                  'roxy': (1, 0), 'claret': (1, 1)}
AVATARS = {'claret': ('matrix-agent-focused', 0), 'roxy': ('matrix-agent-focused', 1),
           'rina': ('matrix-agent-focused', 2), 'manato': ('matrix-two-agents', 1),
           'caesar_king': ('matrix-three-agents', 2)}
BADGES = {'claret': 'matrix-agent-focused', 'roxy': 'matrix-agent-focused',
          'rina': 'matrix-three-agents', 'manato': 'matrix-two-agents',
          'caesar_king': 'matrix-three-agents'}


@lru_cache(maxsize=None)
def recorded(name):
    image = cv2.cvtColor(cv2.imread(str(FIXTURES / f'{name}.png')), cv2.COLOR_BGR2RGB)
    payload = json.loads((FIXTURES / f'{name}.json').read_text(encoding='utf-8'))
    rows = []
    for row in payload['result']['ocr']:
        x, y, width, height = row['rect']
        rows.append(SimpleNamespace(data=row['text'], confidence=row['confidence'],
                                    center=Rect(x, y, x + width, y + height).center))
    return image, rows


def frame_op(name, template_loader):
    op = object.__new__(LostVoidApp)
    op._after_round_wait = lambda **_: None
    op._matrix_selection = {'foreground': 'must remain untouched'}
    op._matrix_pad_selection = None
    op.last_screenshot, rows = recorded(name)
    op.ctx = SimpleNamespace(
        game_config=SimpleNamespace(background_gamepad_type='xbox'),
        controller=SimpleNamespace(background_mode=True, btn_press=Mock(), click=Mock()),
        template_loader=template_loader,
        ocr_service=SimpleNamespace(get_ocr_result_list=lambda image, rect, **_: [
            row for row in rows if in_rect(row.center, rect)]),
        run_context=SimpleNamespace(is_context_stop=False, is_context_running=True),
    )
    return op


@pytest.fixture(scope='module')
def templates():
    return TemplateLoader()


@pytest.fixture
def feature_cache(monkeypatch):
    """缓存真实特征计算，不根据目标或状态编造匹配结果。"""
    cache = {}
    frames = {}

    def match(ctx, image, rect, target=None):
        frames[id(image)] = image  # 保留引用，避免下一帧重用 id。
        key = (id(image), rect.x1, rect.y1, rect.x2, rect.y2,
               tuple(target) if target is not None else None)
        if key not in cache:
            cache[key] = match_team_agent_template(ctx, image, rect, target)
        return cache[key]

    monkeypatch.setattr(matrix_screen, 'match_team_agent_template', match)
    monkeypatch.setattr(agents, 'match_team_agent_template', match)


def test_selected_focused_card_is_identified_with_real_avatar_and_badge(templates, feature_cache):
    op = frame_op('matrix-agent-focused', templates)
    page = matrix_screen.read_team_page(op)
    match = agents._target_match(op, 'claret')
    assert match is not None and in_rect(match.center, page.focus)
    assert agents._selected(page, page.focus)


def card_rect(position):
    row, column = position
    return Rect(185 + column * 157, 165 + row * 200,
                334 + column * 157, 360 + row * 200)


def slot_rect(index):
    return Rect(1032 + index * 135, 162, 1167 + index * 135, 299)


def copy_rect(destination, source, src, dst):
    destination[dst.y1:dst.y2, dst.x1:dst.x2] = source[src.y1:src.y2, src.x1:src.x2]


def shifted_row(row, x, y):
    return SimpleNamespace(data=row.data, confidence=row.confidence,
                           center=type(row.center)(row.center.x + x, row.center.y + y))


class FixtureBoard:
    """槽位头像、卡片、徽标、OCR 来自固定录屏；A 按实际焦点卡片切换，不读 target。"""

    def __init__(self, templates, roster=(), focus=(0, 1), mode='agents', rows=4):
        self.op = frame_op('matrix-main-empty', templates)
        self.roster = list(roster)
        self.focus = focus
        self.mode = mode
        self.row_count = rows
        self.viewport = 0
        self.positions = dict(CARD_POSITIONS)
        self.events = []
        self.toggles = []
        self.frozen_moves = False
        self.frozen_toggle = False
        self.wrong_toggle = None
        self.mode_on_move = None
        self.hide_badge = False
        self.wrap = False
        self.frames = {}
        self.op.ctx.controller.btn_press.side_effect = self.press
        source, _ = recorded('matrix-team-empty')
        self.cards = {}
        for row in range(4):
            for column in range(5):
                rect = card_rect((row, column))
                self.cards[(row, column)] = source[rect.y1:rect.y2, rect.x1:rect.x2]
        self.fillers = [position for position in self.cards if position not in CARD_POSITIONS.values()]

    def frame(self):
        key = (tuple(self.roster), self.focus, self.mode, self.viewport, self.hide_badge,
               tuple(sorted(self.positions.items())))
        if key not in self.frames:
            self.frames[key] = self.render()
        image, rows = self.frames[key]
        self.op.last_screenshot = image
        self.op.ctx.ocr_service = SimpleNamespace(
            get_ocr_result_list=lambda image, rect, **_: [row for row in rows if in_rect(row.center, rect)])
        return self.op

    def render(self):
        if self.mode == 'agents':
            image, rows = recorded('matrix-main-empty')
            image = image.copy()
            rows = [row for row in rows if not in_rect(row.center, matrix_screen.AGENT_LIST)
                    or (self.viewport == 0 and norm_text(row.data) == '代理人' and row.center.y < 155)]
            image[155:1070, 180:970] = (29, 29, 29)
            inverse = {position: agent for agent, position in self.positions.items()}
            for visible_row in range(4):
                row = self.viewport + visible_row
                for column in range(5):
                    position = (row, column)
                    role = inverse.get(position)
                    source_position = (CARD_POSITIONS[role] if role else
                                       self.fillers[(row * 5 + column) % len(self.fillers)])
                    rect = card_rect((visible_row, column))
                    image[rect.y1:rect.y2, rect.x1:rect.x2] = self.cards[source_position]
                    if role in self.roster and not self.hide_badge:
                        self.add_badge(image, rows, role, rect)
            if self.focus is not None:
                row, column = self.focus
                rect = card_rect((row - self.viewport, column))
                cv2.rectangle(image, (rect.x1, rect.y1), (rect.x2 - 1, rect.y2 - 1), (247, 219, 0), 4)
        else:
            name = ('matrix-preset-focused' if self.focus is not None else 'matrix-preset-tab')
            if self.mode == 'support':
                name = 'matrix-support-focused' if self.focus is not None else 'matrix-support-panel'
            image, rows = recorded(name)
            image, rows = image.copy(), list(rows)
        # 只重绘三个主战槽；邦布和协战区域仍为原始截图。
        empty, _ = recorded('matrix-main-empty')
        for index in range(3):
            rect = slot_rect(index)
            copy_rect(image, empty, rect, rect)
        rows = [row for row in rows if not (in_rect(row.center, matrix_screen.MAIN_SLOTS)
                                            and norm_text(row.data) == '主战')]
        for index, role in enumerate(self.roster):
            name, source_index = AVATARS[role]
            source, source_rows = recorded(name)
            src, dst = slot_rect(source_index), slot_rect(index)
            copy_rect(image, source, src, dst)
            rows.extend(shifted_row(row, dst.x1 - src.x1, 0) for row in source_rows
                        if in_rect(row.center, src) and norm_text(row.data) == '主战')
        if self.mode == 'agents' and self.focus is None:
            # 切回右侧时保留实机槽位的焦点圆环；只有左侧框消失不等于焦点已核验。
            source, _ = recorded('matrix-team-empty')
            rect = slot_rect(0)
            focused = source[rect.y1:rect.y2, rect.x1:rect.x2]
            part = image[rect.y1:rect.y2, rect.x1:rect.x2]
            mask = focus_mask(focused)
            part[mask] = focused[mask]
        return image, rows

    def add_badge(self, image, rows, role, destination):
        source, source_rows = recorded(BADGES[role])
        original = card_rect(CARD_POSITIONS[role])
        src = Rect(original.x1 + 75, original.y1 + 120, original.x2 - 5, original.y1 + 165)
        dst = Rect(destination.x1 + 75, destination.y1 + 120, destination.x2 - 5, destination.y1 + 165)
        copy_rect(image, source, src, dst)
        rows.extend(shifted_row(row, destination.x1 - original.x1, destination.y1 - original.y1)
                    for row in source_rows if in_rect(row.center, original)
                    and norm_text(row.data) in ('主战', '主点'))

    def press(self, key, press_time):
        button = key.removeprefix('xbox_').removeprefix('ds4_')
        button = {'cross': 'a', 'circle': 'b', 'l1': 'lb'}.get(button, button)
        self.events.append(button)
        if self.mode == 'support':
            if button == 'b':
                self.focus = None
            elif button == 'dpad_up' and self.focus is None:
                self.mode = 'agents'
            else:
                pytest.fail(f'主战选人在协战页面按了 {button}')
            return
        if self.mode == 'preset':
            assert button == 'lb'
            self.mode, self.focus = 'agents', None
            return
        if button == 'a':
            if self.focus is None:
                self.focus = self.positions[self.roster[0]] if self.roster else (0, 0)
                return
            role = next((role for role, position in self.positions.items() if position == self.focus), None)
            assert role is not None, 'A 必须按在由真实头像匹配确定的角色上'
            self.toggles.append(role)
            if not self.frozen_toggle:
                if role in self.roster:
                    self.roster.remove(role)
                else:
                    self.roster.append(self.wrong_toggle or role)
            return
        assert button.startswith('ls_'), '网格滚动必须使用左摇杆，十字键向下会离开主战列表'
        if self.mode_on_move:
            self.mode, self.focus = self.mode_on_move, None
            return
        if self.frozen_moves:
            return
        row, column = self.focus
        if button == 'ls_up':
            row = (row - 1) % self.row_count if self.wrap else max(0, row - 1)
        elif button == 'ls_down':
            row = (row + 1) % self.row_count if self.wrap else min(self.row_count - 1, row + 1)
        elif button == 'ls_left':
            column = max(0, column - 1)
        elif button == 'ls_right':
            column = min(4, column + 1)
        self.focus = (row, column)
        self.viewport = min(self.viewport, row)
        self.viewport = max(self.viewport, row - 3)


def run_board(board, target=TARGET, limit=350):
    for _ in range(limit):
        result = agents.select_agents(board.frame(), list(target))
        if result.is_success or result.is_fail:
            return result
    pytest.fail('代理人状态机未在有限新画面内结束')


def test_clears_only_selected_main_cards_and_adds_exact_order(templates, feature_cache):
    board = FixtureBoard(templates, ORIGINAL, focus=(1, 1))
    original_foreground = board.op._matrix_selection
    before = board.frame().last_screenshot.copy()
    result = run_board(board)
    assert result.is_success
    assert board.toggles == ORIGINAL + TARGET
    assert board.roster == TARGET
    assert board.op._matrix_selection is original_foreground
    after = board.frame().last_screenshot
    assert (before[350:510, 1020:1180] == after[350:510, 1020:1180]).all()
    assert (before[162:299, 1440:1560] == after[162:299, 1440:1560]).all()
    board.op.ctx.controller.click.assert_not_called()
    assert not any(button.startswith('dpad_') for button in board.events)


@pytest.mark.parametrize('mode,focus,prefix', [
    ('support', (0, 0), ['b', 'dpad_up', 'a']),
    ('support', None, ['dpad_up', 'a']),
    ('preset', (0, 0), ['lb', 'a']),
])
def test_returns_to_free_main_list_before_any_toggle(templates, feature_cache, mode, focus, prefix):
    board = FixtureBoard(templates, ORIGINAL, mode=mode, focus=focus)
    assert run_board(board).is_success
    assert board.events[:len(prefix)] == prefix
    assert board.toggles == ORIGINAL + TARGET


def test_exact_real_roster_succeeds_without_clearing_or_input(templates, feature_cache):
    op = frame_op('matrix-three-agents', templates)
    assert agents.select_agents(op, TARGET).is_success
    op.ctx.controller.btn_press.assert_not_called()
    op.ctx.controller.click.assert_not_called()


@pytest.mark.parametrize('failure', ['wrong-role', 'unchanged-roster', 'missing-selected-label'])
def test_toggle_verification_never_repeats_a(templates, feature_cache, failure):
    board = FixtureBoard(templates)
    if failure == 'wrong-role':
        board.wrong_toggle = 'manato'
    elif failure == 'unchanged-roster':
        board.frozen_toggle = True
    else:
        board.hide_badge = True
    result = run_board(board, ['rina'])
    assert result.is_fail and ('核验' in result.status or '校验' in result.status)
    assert board.toggles == ['rina']
    assert board.events == ['a']
    assert agents.select_agents(board.frame(), ['rina']).is_fail
    assert board.events == ['a']


def test_unknown_roster_is_not_treated_as_empty(templates, feature_cache, monkeypatch):
    op = frame_op('matrix-agent-focused', templates)
    monkeypatch.setattr(agents, 'main_agents', lambda _op, _page: None)
    for _ in range(agents._FRAME_LIMIT - 1):
        assert agents.select_agents(op, TARGET).result == R.WAIT
    result = agents.select_agents(op, TARGET)
    assert result.is_fail and '未识别角色' in result.status
    op.ctx.controller.btn_press.assert_not_called()


def test_real_wrong_page_sends_no_input(templates, feature_cache):
    op = frame_op('matrix-detail', templates)
    for _ in range(agents._FRAME_LIMIT):
        result = agents.select_agents(op, TARGET)
    assert result.is_fail and '编队页面' in result.status
    op.ctx.controller.btn_press.assert_not_called()
    op.ctx.controller.click.assert_not_called()


@pytest.mark.parametrize('focus', [(0, 1), (3, 2)])
def test_offscreen_target_rewinds_and_scrolls_without_wrapping_past_top(templates, feature_cache, focus):
    board = FixtureBoard(templates, focus=focus, rows=7)
    board.wrap = True
    board.positions['manato'] = (6, 4)
    board.viewport = 0
    result = run_board(board, ['manato'])
    assert result.is_success and board.roster == ['manato']
    assert board.toggles == ['manato']
    assert board.viewport > 0
    assert board.focus == (6, 4)


def test_unavailable_target_stops_at_bottom_without_toggling(templates, feature_cache, monkeypatch):
    board = FixtureBoard(templates, focus=(2, 2))
    monkeypatch.setattr(agents, '_target_match', lambda _op, _agent: None)
    result = run_board(board, ['anby'])
    assert result.is_fail and '未找到指定角色' in result.status
    assert not board.toggles and 'a' not in board.events
    assert len(board.events) <= board.row_count * 2 + 2


def test_unchanged_focus_is_bounded_and_never_confirmed(templates, feature_cache):
    board = FixtureBoard(templates, focus=(0, 0))
    board.frozen_moves = True
    result = run_board(board, ['rina'])
    assert result.is_fail and '焦点持续未移动' in result.status
    assert board.events == ['ls_right']
    assert not board.toggles


def test_navigation_wrap_is_detected_without_toggling(templates, feature_cache, monkeypatch):
    board = FixtureBoard(templates, focus=(3, 2))
    board.wrap = True
    monkeypatch.setattr(agents, '_target_match', lambda _op, _agent: None)
    result = run_board(board, ['anby'])
    assert result.is_fail and '循环' in result.status
    assert not board.toggles


def test_unexpected_support_transition_preserves_state_without_a(templates, feature_cache):
    board = FixtureBoard(templates, focus=(0, 0))
    board.mode_on_move = 'support'
    result = run_board(board, ['rina'])
    assert result.is_fail and '离开了自由编队列表' in result.status
    assert board.events == ['ls_right']
    assert board.op._matrix_pad_selection['roster'] == []
    assert not board.toggles


@pytest.mark.parametrize('stopped', [False, True])
def test_upstream_real_operation_pause_stop_guards_precede_pad_selection(templates, stopped):
    op = frame_op('matrix-agent-focused', templates)
    op.ctx.run_context.is_context_running = False
    op.ctx.run_context.is_context_stop = stopped
    # 调用真实 LostVoidApp 守卫，不用「代理函数返回预设结果」验证自己写的替身。
    result = op.matrix_select_agent()
    assert result.result == (R.FAIL if stopped else R.WAIT)
    assert result.status == ('任务已停止' if stopped else '任务已暂停')
    assert op._matrix_pad_selection is None
    op.ctx.controller.btn_press.assert_not_called()
    op.ctx.controller.click.assert_not_called()


def test_ds4_uses_fixed_cross_and_stick_mappings(templates, feature_cache):
    board = FixtureBoard(templates, focus=(0, 0))
    board.op.ctx.game_config.background_gamepad_type = 'ds4'
    assert run_board(board, ['rina']).is_success
    keys = [call.args[0] for call in board.op.ctx.controller.btn_press.call_args_list]
    assert keys == ['ds4_ls_right', 'ds4_cross']


def test_target_change_during_navigation_stops_before_another_input(templates, feature_cache):
    board = FixtureBoard(templates, focus=(0, 0))
    assert agents.select_agents(board.frame(), ['rina']).result == R.WAIT
    result = agents.select_agents(board.frame(), ['manato'])
    assert result.is_fail and '配置在选人期间发生变化' in result.status
    assert board.events == ['ls_right']
    assert not board.toggles
