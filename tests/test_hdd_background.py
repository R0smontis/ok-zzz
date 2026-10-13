"""Current controller HDD pages: no blind A loop and no unverified battle entry."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import pytest

from onedragon.base.geometry.rectangle import Rect
from onedragon.base.operation.operation_round_result import OperationRoundResultEnum as R
from src.navigation.hdd import hdd_state, enter_hdd, choose_chapter
from zzz_od.application.life_on_line.life_on_line_app import LifeOnLineApp
from zzz_od.operation.hdd.enter_hdd_mission import EnterHddMission
from test_lost_void_background_menus import operation

BASE = Path(__file__).parent / 'fixtures/hdd'


def fixture(name, cls=EnterHddMission):
    op = operation(cls)
    op.chapter = '第二章间章'
    op.last_screenshot = cv2.cvtColor(cv2.imread(str(BASE / f'{name}.png')), cv2.COLOR_BGR2RGB)
    data = json.loads((BASE / f'{name}.json').read_text(encoding='utf-8'))
    rows = [SimpleNamespace(data=r['text'], center=Rect(r['rect'][0], r['rect'][1],
            r['rect'][0]+r['rect'][2], r['rect'][1]+r['rect'][3]).center) for r in data['result']['ocr']]
    op.ctx.ocr_service = SimpleNamespace(get_ocr_result_list=Mock(return_value=rows))
    return op


@pytest.mark.parametrize('name,page', [('chapter-hub','hub'), ('chapter-dropdown-latest','chapters'),
                         ('mission-list','missions'), ('deployment','deployment')])
def test_real_hdd_pages_do_not_require_legacy_street_label(name, page):
    op = fixture(name)
    assert hdd_state(op, op.last_screenshot)['page'] == page
    assert enter_hdd(op, op.last_screenshot).is_success
    op.ctx.controller.btn_press.assert_not_called()


@pytest.mark.parametrize('name', ['chapter-dialog', 'chapter-dialog-second', 'trial-mode-notice'])
def test_dialogs_are_not_mistaken_for_hdd_or_pressed(name):
    op = fixture(name, LifeOnLineApp)
    op.check_and_update_current_screen = Mock(return_value=None)
    assert hdd_state(op, op.last_screenshot) is None
    assert op.interact().result == R.RETRY
    op.ctx.controller.interact.assert_not_called()
    op.ctx.controller.btn_press.assert_not_called()


def test_interact_already_in_hdd_generates_no_more_a_presses():
    for name in ('chapter-hub', 'mission-list', 'deployment'):
        op = fixture(name, LifeOnLineApp)
        op._hdd_interact_requests = 3
        assert op.interact().is_success
        assert op._hdd_interact_requests == 0
        op.ctx.controller.interact.assert_not_called()


def test_world_interaction_is_verified_and_bounded():
    op = fixture('chapter-dialog', LifeOnLineApp)
    op.check_and_update_current_screen = Mock(return_value='大世界-普通')
    for _ in range(3):
        assert op.interact().result == R.WAIT
    assert op.interact().is_fail
    assert op.ctx.controller.interact.call_count == 3


def test_chapter_hub_opens_dropdown_without_selecting_default_commission():
    op = fixture('chapter-hub')
    assert choose_chapter(op, op.last_screenshot).result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_l_thumb', press_time=.12)


@pytest.mark.parametrize('name,key', [('chapter-dropdown-latest','xbox_dpad_up'),
                                    ('chapter-dropdown-fourth','xbox_dpad_up'),
                                    ('chapter-dropdown-interlude','xbox_a')])
def test_dropdown_moves_and_selects_only_the_verified_target(name, key):
    op = fixture(name)
    assert choose_chapter(op, op.last_screenshot).result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with(key, press_time=.12)


def test_chapter_selection_is_not_success_until_header_is_verified():
    op = fixture('chapter-dropdown-interlude')
    assert choose_chapter(op, op.last_screenshot).result == R.WAIT
    dialog = fixture('chapter-dialog')
    op.ctx.ocr_service = dialog.ctx.ocr_service
    assert choose_chapter(op, dialog.last_screenshot).result == R.RETRY
    assert op.ctx.controller.btn_press.call_count == 1
    hub = fixture('chapter-hub')
    rows = hub.ctx.ocr_service.get_ocr_result_list.return_value
    rows = [r for r in rows if not (r.center.x > 1490 and r.center.y < 85)]
    rows.append(SimpleNamespace(data='第二章间章', center=Rect(1520, 40, 1700, 75).center))
    op.ctx.ocr_service.get_ocr_result_list.return_value = rows
    assert choose_chapter(op, hub.last_screenshot).is_success
    assert op.ctx.controller.btn_press.call_count == 1


def test_previous_mission_or_deployment_is_backed_out_before_chapter_choice():
    for name in ('mission-list', 'deployment'):
        op = fixture(name)
        assert choose_chapter(op, op.last_screenshot).result == R.WAIT
        op.ctx.controller.btn_press.assert_called_once_with('xbox_b', press_time=.12)


def test_locked_combat_commission_fails_without_input():
    # Live 2026-10-13: 第二章间章 offers 剧情/探索 and a LOCKED card; 真·拿命验收 is out of reach.
    op = fixture('hdd-hub-2i')
    op.mission_type = '战斗委托'
    result = op.choose_mission_type()
    assert result.is_fail and '未解锁' in result.status
    op.ctx.controller.click.assert_not_called()
    op.ctx.controller.btn_press.assert_not_called()


@pytest.mark.parametrize('name,focused', [('hdd-3-left', '探索委托'), ('hdd-3-left2', '剧情委托'),
                                          ('hdd-3-left3', '战斗委托')])
def test_commission_focus_is_read_from_the_chevron(name, focused):
    from src.navigation.hdd import COMMISSIONS, _card_focused, _text
    op = fixture(name)
    rows = op.ctx.ocr_service.get_ocr_result_list()
    cards = [r for r in rows if _text(r.data) in COMMISSIONS]
    assert [_text(r.data) for r in cards if _card_focused(op.last_screenshot, r)] == [focused]


def test_combat_commission_is_reached_and_opened():
    op = fixture('hdd-3-left2')
    op.mission_type = '战斗委托'
    assert op.choose_mission_type().result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_dpad_left', press_time=.12)
    op = fixture('hdd-3-left3')
    op.mission_type = '战斗委托'
    assert op.choose_mission_type().result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_a', press_time=.12)


def test_mission_list_selection_moves_to_the_named_row():
    from src.navigation.hdd import mission_rows
    op = fixture('hdd-3-combat-list')
    rows = op.ctx.ocr_service.get_ocr_result_list()
    lines = mission_rows(op.last_screenshot, rows)
    assert [name for name, _, selected in lines if selected] == ['恶战开拓新道路']
    op.mission_name = '作战实力演技派'
    assert op.choose_mission().result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_dpad_down', press_time=.12)
    op = fixture('hdd-3-combat-list')
    op.mission_name = '恶战开拓新道路Ⅰ'
    op.mission_name = '[恶战]开拓新道路'
    assert op.choose_mission().is_success


def test_next_is_the_menu_button_until_deployment_shows():
    from src.navigation.hdd import press_next
    op = fixture('hdd-3-combat-list')
    assert press_next(op, op.last_screenshot).result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_start', press_time=.12)
    op = fixture('deployment')
    assert press_next(op, op.last_screenshot).is_success
