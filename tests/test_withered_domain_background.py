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
