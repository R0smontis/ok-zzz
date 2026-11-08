"""矩阵行动菜单使用实测帧、离线 OCR 和真实焦点识别；不发送本机输入。"""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest

from onedragon.base.geometry.rectangle import Rect
from onedragon.base.operation.operation_round_result import (
    OperationRoundResult, OperationRoundResultEnum as R,
)
from src.navigation.common import in_rect
from zzz_od.application.hollow_zero.lost_void import matrix_pad_menu as menu
from zzz_od.application.hollow_zero.lost_void.lost_void_challenge_config import LostVoidRegionType


_FIXTURES = Path(__file__).parent / 'fixtures' / 'lost_void'
_PRESET_ROSTER = ['claret', 'roxy', 'rina']


class FrameOperation:
    def __init__(self):
        config = SimpleNamespace(predefined_team_idx=0, artifact_priority_in_battle=['旧优先级'])
        config.clear_artifact_priority_in_battle = Mock(
            side_effect=lambda: setattr(config, 'artifact_priority_in_battle', []))
        self.ctx = SimpleNamespace(
            controller=SimpleNamespace(btn_press=Mock()),
            game_config=SimpleNamespace(background_gamepad_type='xbox'),
            lost_void=SimpleNamespace(challenge_config=config, predefined_team_idx=7,
                                      in_normal_world=Mock(return_value=False), in_start_room=False),
            team_config=SimpleNamespace(team_list=[
                SimpleNamespace(name=f'编队{index + 1}', agent_id_list=list(_PRESET_ROSTER))
                for index in range(5)]),
            ocr_service=SimpleNamespace(get_ocr_result_list=Mock(side_effect=self._read_ocr)),
        )
        self.rows = []
        self.last_screenshot = np.zeros((1080, 1920, 3), np.uint8)
        self.next_region_type = None

    def frame(self, name):
        path = _FIXTURES / f'{name}.png'
        image = cv2.imread(str(path))
        assert image is not None, path
        self.last_screenshot = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        data = json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
        self.rows = []
        for item in data['result']['ocr']:
            x, y, width, height = item['rect']
            rect = Rect(x, y, x + width, y + height)
            self.rows.append(SimpleNamespace(data=item['text'], confidence=item['confidence'],
                                             rect=rect, center=rect.center))
        return self

    def _read_ocr(self, *, image, rect=None, **_):
        assert image is self.last_screenshot, '必须识别本轮截图，不能复用历史坐标'
        return [row for row in self.rows if rect is None or in_rect(row.center, rect)]

    @property
    def buttons(self):
        return [call.args[0] for call in self.ctx.controller.btn_press.call_args_list]

    def round_wait(self, status=None, **_):
        return OperationRoundResult(R.WAIT, status)

    def round_success(self, status=None, **_):
        return OperationRoundResult(R.SUCCESS, status)

    def round_fail(self, status=None, **_):
        return OperationRoundResult(R.FAIL, status)


@pytest.fixture
def op(monkeypatch):
    # 头像模板识别另由 matrix_pad_agents 的真实模板回归覆盖；此处只隔离该依赖，
    # 页签、焦点、主战/协战标签、按钮和勾选仍全部从实测 PNG/JSON 读取。
    monkeypatch.setattr(menu, 'main_agents', Mock(return_value=list(_PRESET_ROSTER)))
    return FrameOperation()


def finish_unchanged(helper, op, maximum=100):
    for _ in range(maximum):
        result = helper(op)
        if result.is_success or result.is_fail:
            return result
    pytest.fail('菜单在有限轮次内没有完成或明确失败')


def test_real_periodic_entry_requires_detail_next_step_then_verified_team(op):
    op.frame('matrix-periodic')
    assert menu.goto_entry(op).result == R.WAIT
    assert op.buttons == ['xbox_a']
    op.frame('matrix-detail')
    # 实测 OCR 把「下一步」拆成「下一」「步」，仍应使用菜单键而非 A。
    assert menu.goto_entry(op).result == R.WAIT
    assert op.buttons == ['xbox_a', 'xbox_start']
    op.frame('matrix-team-empty')
    assert menu.goto_entry(op).is_success
    assert op.buttons == ['xbox_a', 'xbox_start']


def test_regular_entry_switches_tab_and_waits_for_actual_matrix_card(op):
    op.frame('matrix-periodic')
    # 保留实测入口的页头/按钮形状，只改变常规入口卡片标题。
    next(row for row in op.rows if row.data == '矩阵行动').data = '战线清扫'
    assert menu.goto_entry(op).result == R.WAIT
    assert op.buttons == ['xbox_lb']
    op.frame('matrix-periodic')
    assert menu.goto_entry(op).result == R.WAIT
    assert op.buttons == ['xbox_lb', 'xbox_a']


@pytest.mark.parametrize('missing', ['title', 'action', 'header'])
def test_matrix_entry_needs_both_page_identity_and_local_control(op, missing):
    op.frame('matrix-periodic')
    removed = {'title': '矩阵行动', 'action': '前往挑战',
               'header': '悬赏委托完成进度：0/8000'}[missing]
    op.rows[:] = [row for row in op.rows if row.data != removed]
    result = finish_unchanged(menu.goto_entry, op)
    assert result.is_fail
    # 缺失矩阵标题时只允许已识别入口的 LB 切页，不得确认「前往挑战」。
    if missing != 'title':
        assert not op.buttons
    else:
        assert 'xbox_a' not in op.buttons and len(op.buttons) <= 8


def test_tab_switch_is_not_list_open_and_preset_is_applied_before_success(op):
    op.frame('matrix-team-empty')
    assert menu.open_preset(op).result == R.WAIT
    assert op.buttons == ['xbox_rb']
    op.frame('matrix-preset-tab')
    assert menu.open_preset(op).is_success
    assert op.buttons == ['xbox_rb']
    op.ctx.lost_void.challenge_config.predefined_team_idx = -1
    op.ctx.team_config.team_list[0].name = ' 编队 1 '
    assert menu.select_preset(op).result == R.WAIT
    assert op.buttons == ['xbox_rb', 'xbox_a']
    assert op.ctx.lost_void.predefined_team_idx == 7
    op.frame('matrix-preset-focused')
    assert menu.select_preset(op).result == R.WAIT
    assert op.buttons == ['xbox_rb', 'xbox_a', 'xbox_a']
    assert op.ctx.lost_void.predefined_team_idx == 7
    op.frame('matrix-preset-selected')
    assert menu.select_preset(op).is_success
    assert op.ctx.lost_void.predefined_team_idx == 0


def test_open_preset_leaves_support_list_and_restores_main_before_tab_success(op):
    op.frame('matrix-support-focused')
    assert menu.open_preset(op).result == R.WAIT
    assert op.buttons == ['xbox_b']
    op.frame('matrix-support-panel')
    assert menu.open_preset(op).result == R.WAIT
    assert op.buttons == ['xbox_b', 'xbox_dpad_up']
    op.frame('matrix-preset-tab')
    assert menu.open_preset(op).is_success
    assert len(op.buttons) == 2


def test_existing_main_labels_do_not_bypass_applying_configured_preset(op):
    op.frame('matrix-preset-selected')
    assert menu.select_preset(op).result == R.WAIT
    assert op.buttons == ['xbox_a']
    assert op.ctx.lost_void.predefined_team_idx == 7
    op.frame('matrix-preset-selected')
    assert menu.select_preset(op).is_success
    assert op.buttons == ['xbox_a']


def test_preset_next_visible_card_is_vertical_not_two_column(op):
    op.frame('matrix-preset-focused')
    # 复用第二张实际竖排卡片的 OCR 框，模拟用户将空预设命名为编队2。
    empty_titles = sorted((row for row in op.rows if row.data == '待设置编队'),
                          key=lambda row: row.center.y)
    empty_titles[0].data = '编队2'
    op.ctx.lost_void.challenge_config.predefined_team_idx = 1
    assert menu.select_preset(op).result == R.WAIT
    assert op.buttons == ['xbox_ls_down']
    assert op.ctx.lost_void.predefined_team_idx == 7


def test_offscreen_preset_search_uses_config_order_and_never_random_applies(op):
    op.frame('matrix-preset-focused')
    op.ctx.lost_void.challenge_config.predefined_team_idx = 4
    result = finish_unchanged(menu.select_preset, op)
    assert result.is_fail
    assert op.buttons and set(op.buttons) == {'xbox_ls_down'}
    assert len(op.buttons) <= 16
    assert op.ctx.lost_void.predefined_team_idx == 7


def test_far_preset_can_apply_after_more_than_eight_list_moves(op):
    op.frame('matrix-preset-focused')
    op.ctx.lost_void.challenge_config.predefined_team_idx = 4
    for _ in range(9):
        assert menu.select_preset(op).result == R.WAIT
    assert op.buttons == ['xbox_ls_down'] * 9
    # 模拟滚动后出现同阵容的第5预设，继续使用真实卡片与 OCR 框。
    op.frame('matrix-preset-focused')
    next(row for row in op.rows if row.data == '编队1').data = '编队5'
    assert menu.select_preset(op).result == R.WAIT
    assert op.buttons[-1] == 'xbox_a'
    op.frame('matrix-preset-selected')
    next(row for row in op.rows if row.data == '编队1').data = '编队5'
    assert menu.select_preset(op).is_success
    assert op.ctx.lost_void.predefined_team_idx == 4


@pytest.mark.parametrize('idx', [-2, 5, '0', True])
def test_invalid_preset_index_fails_before_input_or_active_index_mutation(op, idx):
    op.frame('matrix-preset-focused')
    op.ctx.lost_void.challenge_config.predefined_team_idx = idx
    assert menu.select_preset(op).is_fail
    assert not op.buttons and op.ctx.lost_void.predefined_team_idx == 7


def test_empty_or_ambiguous_configured_preset_fails_clearly(op):
    op.frame('matrix-preset-focused')
    op.ctx.team_config.team_list = []
    assert menu.select_preset(op).is_fail
    op.ctx.team_config.team_list = [SimpleNamespace(name=' ')]
    assert '名称为空' in menu.select_preset(op).status
    op.ctx.team_config.team_list = [SimpleNamespace(name='编队1'), SimpleNamespace(name='编队 1')]
    assert '不唯一' in menu.select_preset(op).status
    assert not op.buttons


def test_preset_apply_requires_checkmark_and_expected_roster(op):
    op.frame('matrix-preset-focused')
    assert menu.select_preset(op).result == R.WAIT
    # 同一张未选中的实测卡片不能因其角色图片/已有主战配置而被误报成功；无变化时最多补按一次 A。
    assert finish_unchanged(menu.select_preset, op).is_fail
    assert op.buttons == ['xbox_a', 'xbox_a']
    op.ctx.lost_void.challenge_config.predefined_team_idx = 0
    op._matrix_pad_menu = {}
    op.frame('matrix-preset-focused')
    assert menu.select_preset(op).result == R.WAIT
    op.frame('matrix-preset-selected')
    menu.main_agents.return_value = ['rina', 'claret', 'roxy']
    assert finish_unchanged(menu.select_preset, op).is_fail
    # Checked card and main labels present: the order mismatch is never answered with another A.
    assert op.buttons == ['xbox_a', 'xbox_a', 'xbox_a']
    assert op.ctx.lost_void.predefined_team_idx == 7


def test_ignored_preset_apply_is_pressed_again_once_then_verified(op):
    # 2026-11-08 实机：A 后编队 1 仍未勾选、主战槽全空，任务等满轮次失败；再按一次 A 立即应用。
    op.frame('matrix-preset-focused')
    assert menu.select_preset(op).result == R.WAIT
    op.frame('matrix-preset-apply-ignored')
    for _ in range(3):
        assert menu.select_preset(op).result == R.WAIT
    assert op.buttons == ['xbox_a', 'xbox_a']
    op.frame('matrix-preset-selected')
    assert menu.select_preset(op).is_success
    assert op.buttons == ['xbox_a', 'xbox_a']


def test_recreated_pad_reveals_focus_before_entering_and_applying_preset(op):
    op.frame('matrix-preset-keyboard')
    assert menu.select_preset(op).result == R.WAIT
    assert op.buttons == ['xbox_ls_left']  # 键鼠画面无手柄焦点，不能直接 A 或永久等待。
    op.frame('matrix-preset-tab')
    assert menu.select_preset(op).result == R.WAIT
    op.frame('matrix-preset-focused')
    assert menu.select_preset(op).result == R.WAIT
    op.frame('matrix-preset-selected')
    assert menu.select_preset(op).is_success
    assert op.buttons == ['xbox_ls_left', 'xbox_a', 'xbox_a']


def test_pad_reveal_that_never_shows_focus_does_not_select_any_team(op):
    op.frame('matrix-preset-keyboard')
    assert finish_unchanged(menu.select_preset, op).is_fail
    assert op.buttons == ['xbox_ls_left', 'xbox_ls_left']
    assert op.ctx.lost_void.predefined_team_idx == 7


def test_support_opens_from_main_list_via_right_panel_then_verified_mode(op):
    op.frame('matrix-preset-selected')
    assert menu.open_support(op).result == R.WAIT
    assert op.buttons == ['xbox_b']
    op.frame('matrix-preset-tab')
    assert menu.open_support(op).result == R.WAIT
    assert op.buttons == ['xbox_b', 'xbox_dpad_down']
    op.frame('matrix-support-panel')
    assert menu.open_support(op).is_success
    assert menu.wait_support(op).is_success
    assert len(op.buttons) == 2


def test_wait_support_rejects_main_agents_header_and_is_bounded(op):
    op.frame('matrix-team-empty')
    assert finish_unchanged(menu.wait_support, op).is_fail
    assert not op.buttons


def test_support_first_60_opens_list_then_up_is_selected_and_verified(op):
    op.frame('matrix-support-panel')
    assert menu.select_support(op).result == R.WAIT
    assert op.buttons == ['xbox_a']
    assert op.ctx.lost_void.challenge_config.artifact_priority_in_battle == ['旧优先级']
    op.frame('matrix-support-focused')
    assert menu.select_support(op).result == R.WAIT
    assert op.buttons == ['xbox_a', 'xbox_a']
    op.frame('matrix-support-selected')
    assert menu.select_support(op).is_success
    assert op.buttons == ['xbox_a', 'xbox_a']
    config = op.ctx.lost_void.challenge_config
    assert config.artifact_priority_in_battle == ['异常']
    config.clear_artifact_priority_in_battle.assert_called_once()


def test_already_selected_up_is_not_toggled_off(op):
    op.frame('matrix-support-selected')
    assert menu.select_support(op).is_success
    assert menu.select_support(op).is_success
    assert not op.buttons
    assert op.ctx.lost_void.challenge_config.artifact_priority_in_battle == ['异常']
    op.ctx.lost_void.challenge_config.clear_artifact_priority_in_battle.assert_called_once()


def test_up_badge_takes_priority_over_first_level_60(op):
    op.frame('matrix-support-focused')
    badge = next(row for row in op.rows if row.data == 'UP')
    # 使用同一实测首行第二张卡片的位置；焦点仍在第一张，必须先右移。
    badge.rect = Rect(badge.rect.x1 + 157, badge.rect.y1, badge.rect.x2 + 157, badge.rect.y2)
    badge.center = badge.rect.center
    assert menu.select_support(op).result == R.WAIT
    assert op.buttons == ['xbox_ls_right']


@pytest.mark.parametrize('missing_side', ['left', 'right'])
def test_support_requires_target_left_and_right_selection_labels(op, missing_side):
    op.frame('matrix-support-selected')
    op.rows[:] = [row for row in op.rows if not (row.data == '协战'
                  and ((row.center.x < 1000) == (missing_side == 'left')))]
    assert finish_unchanged(menu.select_support, op).is_fail
    assert not op.buttons
    config = op.ctx.lost_void.challenge_config
    assert config.artifact_priority_in_battle == ['旧优先级']
    config.clear_artifact_priority_in_battle.assert_not_called()


@pytest.mark.parametrize('weapon,expected', [
    ('【昇常：附加】轻羽流霰', ['异常']),
    ('［异常:附加］轻羽流霰', ['异常']),
    ('', []), ('WEAPONS', []), ('[：附加]轻羽流霰', []),
])
def test_support_weapon_only_adds_nonempty_bracket_category(op, weapon, expected):
    op.frame('matrix-support-selected')
    next(row for row in op.rows if row.data.startswith('[异常')).data = weapon
    assert menu.select_support(op).is_success
    assert op.ctx.lost_void.challenge_config.artifact_priority_in_battle == expected


def test_support_apply_does_not_repeat_a_on_unchanged_frame(op):
    op.frame('matrix-support-focused')
    assert menu.select_support(op).result == R.WAIT
    assert finish_unchanged(menu.select_support, op).is_fail
    assert op.buttons == ['xbox_a']
    op.ctx.lost_void.challenge_config.clear_artifact_priority_in_battle.assert_not_called()


def test_start_requires_world_confirmation_not_black_transition(op):
    op.frame('matrix-support-selected')
    assert menu.start_challenge(op).result == R.WAIT
    assert op.buttons == ['xbox_start']
    op.last_screenshot[:] = 0
    op.rows = []
    for _ in range(4):
        assert menu.start_challenge(op).result == R.WAIT
    assert not op.ctx.lost_void.in_start_room
    assert op.next_region_type is None
    op.ctx.lost_void.in_normal_world.return_value = True
    assert menu.start_challenge(op).is_success
    assert op.ctx.lost_void.in_start_room
    assert op.next_region_type == LostVoidRegionType.ENTRY
    assert op.buttons == ['xbox_start']


def test_start_loading_forever_is_bounded_failure(op):
    op.frame('matrix-support-selected')
    assert menu.start_challenge(op).result == R.WAIT
    op.rows = []
    op.last_screenshot[:] = 0
    assert finish_unchanged(menu.start_challenge, op).is_fail
    assert op.buttons == ['xbox_start']
    assert not op.ctx.lost_void.in_start_room


def test_unchanged_team_page_caps_start_requests(op):
    op.frame('matrix-support-selected')
    assert finish_unchanged(menu.start_challenge, op).is_fail
    assert op.buttons == ['xbox_start'] * 3
    assert not op.ctx.lost_void.in_start_room


@pytest.mark.parametrize('frame,message', [('matrix-main-empty', '主战编队为空'),
                                          ('matrix-preset-selected', '协战代理人未选择')])
def test_start_rejects_incomplete_team_without_input(op, frame, message):
    op.frame(frame)
    result = menu.start_challenge(op)
    assert result.is_fail and message in result.status
    assert not op.buttons


def test_rejected_deploy_popup_is_failure_without_random_confirmation(op):
    op.frame('matrix-support-selected')
    assert menu.start_challenge(op).result == R.WAIT
    rect = Rect(690, 440, 1240, 490)
    op.rows = [SimpleNamespace(data='请至少选择一名代理人', confidence=.99, rect=rect, center=rect.center)]
    result = menu.start_challenge(op)
    assert result.is_fail and '代理人' in result.status
    assert op.buttons == ['xbox_start']


@pytest.mark.parametrize('helper', [menu.goto_entry, menu.open_preset, menu.select_preset,
                                  menu.open_support, menu.wait_support, menu.select_support,
                                  menu.start_challenge])
def test_unrelated_real_page_has_no_input_and_bounded_failure(op, helper):
    op.frame('compendium_combat_tab')
    assert finish_unchanged(helper, op).is_fail
    assert not op.buttons


@pytest.mark.parametrize('helper,frame,maximum', [
    (menu.goto_entry, 'matrix-periodic', 8),
    (menu.open_preset, 'matrix-team-empty', 8),
    (menu.open_support, 'matrix-preset-tab', 8),
    (menu.select_preset, 'matrix-preset-tab', 1),
    (menu.select_support, 'matrix-support-panel', 1),
])
def test_unchanged_recognized_page_is_bounded_not_input_storm(op, helper, frame, maximum):
    op.frame(frame)
    assert finish_unchanged(helper, op).is_fail
    assert 0 < len(op.buttons) <= maximum


def test_successive_matrix_runs_do_not_reuse_preset_apply_state(op):
    op.frame('matrix-preset-focused')
    assert menu.select_preset(op).result == R.WAIT
    op.frame('matrix-preset-selected')
    assert menu.select_preset(op).is_success
    op.frame('matrix-periodic')
    assert menu.goto_entry(op).result == R.WAIT
    op.frame('matrix-preset-tab')
    assert menu.goto_entry(op).is_success
    assert menu.open_preset(op).is_success
    op.frame('matrix-preset-focused')
    assert menu.select_preset(op).result == R.WAIT
    assert op.buttons == ['xbox_a', 'xbox_a', 'xbox_a']
