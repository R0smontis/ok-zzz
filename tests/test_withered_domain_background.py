"""枯萎之都 entrance, zone map and mission list on real controller frames."""
import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import pytest

from onedragon.base.geometry.rectangle import Rect
from onedragon.base.operation.operation_round_result import OperationRoundResultEnum as R
from src.navigation.hollow import entrance_step, mission_step, next_step, zone_step
from zzz_od.application.hollow_zero.withered_domain.withered_domain_app import WitheredDomainApp
from test_lost_void_background_menus import operation

BASE = Path(__file__).parent / 'fixtures/withered'


def frame(name, op=None):
    op = op or operation(WitheredDomainApp)
    screen = cv2.cvtColor(cv2.imread(str(BASE / f'{name}.png')), cv2.COLOR_BGR2RGB)
    payload = json.loads((BASE / f'{name}.json').read_text(encoding='utf-8'))
    rows = [SimpleNamespace(data=r['text'], center=Rect(r['rect'][0], r['rect'][1], r['rect'][0] + r['rect'][2],
                                                        r['rect'][1] + r['rect'][3]).center)
            for r in payload['result']['ocr']]
    op.ctx.ocr_service = SimpleNamespace(get_ocr_result_list=lambda image, rect, **_: rows)
    return op, screen


def pressed(op):
    return [call.args[0] for call in op.ctx.controller.btn_press.call_args_list]


@pytest.mark.parametrize('name,button', [('hz-entry', 'xbox_dpad_right'), ('hz-wd-focus', 'xbox_a')])
def test_entrance_moves_to_withered_domain_then_enters(name, button):
    op, screen = frame(name)
    assert entrance_step(op, screen).result == R.WAIT
    assert pressed(op) == [button]


def test_zone_map_counts_as_arrived_and_steers_to_the_zone():
    op, screen = frame('hz-wd-entry')
    assert entrance_step(op, screen).is_success
    assert zone_step(op, screen, '旧都列车').result == R.WAIT
    assert pressed(op) == ['xbox_dpad_right']  # 资质考核 is focused; 旧都列车 lies right
    op, screen = frame('wd-2')
    assert zone_step(op, screen, '旧都列车').result == R.WAIT
    assert pressed(op) == ['xbox_a']


def test_mission_list_selects_the_configured_mission():
    op, screen = frame('wd-3')
    assert mission_step(op, screen, '旧都列车-内部').result == R.WAIT
    assert pressed(op) == ['xbox_dpad_down']
    op, screen = frame('wd-4')
    assert mission_step(op, screen, '旧都列车-内部').is_success


def test_next_is_pressed_on_the_menu_button_until_deployment():
    op, screen = frame('wd-4')
    assert next_step(op, screen).result == R.WAIT
    assert pressed(op) == ['xbox_start']
    op, screen = frame('wd-5')
    result = next_step(op, screen)
    assert result.is_success and result.status == '出战'


def test_squad_keeps_existing_leader_without_replacing_user_team():
    from src.navigation.hollow import squad_step
    op, screen = frame('hollow-leader-ready')
    assert squad_step(op, screen, ['ellen', '击破', 'soukaku']).is_success
    assert pressed(op) == []


def test_empty_leader_opens_with_a_then_selects_and_confirms_with_ax():
    from src.navigation.hollow import squad_step
    op, screen = frame('hollow-squad-empty')
    assert squad_step(op, screen, ['roxy']).result == R.WAIT
    assert pressed(op) == ['xbox_a']
    _, screen = frame('hollow-picker-settled', op)
    assert squad_step(op, screen, ['roxy']).result == R.WAIT
    assert pressed(op) == ['xbox_a', 'xbox_a']
    assert op._leader_pending == 'roxy'
    _, screen = frame('hollow-roxy-chosen', op)
    assert squad_step(op, screen, ['roxy']).result == R.WAIT
    assert pressed(op)[-1] == 'xbox_x'  # X 确认阵容, not A again (which would deselect).
    _, screen = frame('hollow-leader-ready', op)
    assert squad_step(op, screen, ['roxy']).is_success
    assert len(pressed(op)) == 3


@pytest.mark.parametrize('targets', [[], [None], 'roxy', ['不存在的角色']])
def test_empty_leader_needs_valid_configuration(targets):
    from src.navigation.hollow import squad_step
    op, screen = frame('hollow-squad-empty')
    assert squad_step(op, screen, targets).is_fail
    assert pressed(op) == []


def test_role_type_matches_current_agent_but_unowned_name_is_not_selected():
    from src.navigation.hollow import squad_step
    op, screen = frame('hollow-squad-empty')
    squad_step(op, screen, ['击破'])
    _, screen = frame('hollow-picker-settled', op)
    assert squad_step(op, screen, ['击破']).result == R.WAIT
    assert op._leader_pending == 'roxy'
    op, screen = frame('hollow-squad-empty')
    squad_step(op, screen, ['ellen'])
    _, screen = frame('hollow-picker-settled', op)
    assert squad_step(op, screen, ['ellen']).result == R.WAIT
    assert pressed(op)[-1] == 'xbox_dpad_right'
    assert getattr(op, '_leader_pending', None) is None


def test_unrelated_picker_and_mismatched_confirmation_do_not_succeed():
    from src.navigation.hollow import squad_step
    op, screen = frame('hollow-roxy-chosen')
    assert squad_step(op, screen, ['roxy']).is_fail
    assert pressed(op) == []
    op, screen = frame('hollow-leader-ready')
    op._leader_pending = 'ellen'
    assert squad_step(op, screen, ['ellen']).is_fail
    assert pressed(op) == []


def test_roster_selection_and_deploy_are_separate_nodes():
    entries = WitheredDomainApp.check_squad.operation_edge_annotation
    assert any(e.node_from_name == '下一步' and e.status == '出战' for e in entries)
    deploy = WitheredDomainApp.deploy.operation_edge_annotation
    assert all(e.node_from_name == '检测编队' for e in deploy)


def test_suspended_run_dialog_is_confirmed_once_and_resumes_without_deploying():
    op, screen = frame('hollow-resume-dialog')
    assert next_step(op, screen).result == R.WAIT
    assert pressed(op) == ['xbox_a']
    assert next_step(op, screen).result == R.WAIT  # still visible: no repeated confirm
    op, screen = frame('hollow-back-world', op)
    result = next_step(op, screen)
    assert result.is_success and result.status == '继续-确认'
    assert pressed(op) == ['xbox_a']


def test_resume_dialog_that_never_closes_fails_without_repeating():
    op, screen = frame('hollow-resume-dialog')
    next_step(op, screen)
    results = [next_step(op, screen) for _ in range(7)]
    assert results[-1].is_fail and pressed(op) == ['xbox_a']


def test_resume_dialog_without_verified_confirm_focus_is_not_operated():
    op, screen = frame('hollow-resume-dialog')
    screen = screen.copy()
    screen[560:660, 960:1240] = 0
    assert next_step(op, screen).result == R.RETRY and pressed(op) == []


def test_app_resets_level_after_resume_confirmation():
    op, screen = frame('hollow-resume-dialog')
    op.ctx.controller.background_mode = True
    op._background = lambda: True
    op.level = op.phase = 2
    op.last_screenshot = screen
    op.click_next()
    _, op.last_screenshot = frame('hollow-back-world', op)
    assert op.click_next().status == '继续-确认'
    assert op.level == -1 and op.phase == -1


@pytest.mark.parametrize('name', ['hollow-corruption-popup-2', 'hollow-loot-confirm', 'hollow-resumed-board'])
def test_hollow_popup_at_start_resumes_the_run_instead_of_leaving(name):
    op, screen = frame(name)
    op.ctx.controller.background_mode = True
    op._background = lambda: True
    op.last_screenshot = screen
    from unittest.mock import Mock
    import zzz_od.hollow_zero.event.hollow_event_utils as utils
    original = utils.check_screen
    utils.check_screen = Mock(return_value=None)
    try:
        result = op.check_first_screen()
    finally:
        utils.check_screen = original
    assert result.status == WitheredDomainApp.STATUS_IN_HOLLOW
