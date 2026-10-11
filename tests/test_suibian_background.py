"""随便观 controller flows on real frames: every press follows a verified page and focus."""
import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import pytest

from onedragon.base.geometry.rectangle import Rect
from onedragon.base.operation.operation_round_result import OperationRoundResultEnum as R
from src.navigation.suibian import (SuibianPadFlow, adventure_locations, adventure_step, arrival_step,
                                    auto_manage_step, duration_tiles, entry_tile_focused, is_entry,
                                    neighbourhood_focused, yum_cha_step)
from test_lost_void_background_menus import operation

BASE = Path(__file__).parent / 'fixtures/suibian'


def frame(name, op=None, **state):
    op = op or operation(SuibianPadFlow)
    op.__dict__.update(state)
    screen = cv2.cvtColor(cv2.imread(str(BASE / f'{name}.png')), cv2.COLOR_BGR2RGB)
    payload = json.loads((BASE / f'{name}.json').read_text(encoding='utf-8'))
    rows = [SimpleNamespace(data=r['text'], center=Rect(r['rect'][0], r['rect'][1], r['rect'][0] + r['rect'][2],
                                                        r['rect'][1] + r['rect'][3]).center)
            for r in payload['result']['ocr']]
    op.ctx.ocr_service = SimpleNamespace(get_ocr_result_list=lambda image, rect: [
        r for r in rows if rect.x1 <= r.center.x < rect.x2 and rect.y1 <= r.center.y < rect.y2])
    return op, screen, rows


def pressed(op):
    return [call.args[0] for call in op.ctx.controller.btn_press.call_args_list]


def settled(op, screen):
    """A detail panel is acted on once two frames agree."""
    assert adventure_step(op, screen).result == R.WAIT
    return adventure_step(op, screen)


def adventure_op(**state):
    return dict(claim=True, dispatch=True, duration='20小时', **state)


def test_real_entry_page_and_focused_tile():
    op, screen, rows = frame('entry')
    assert is_entry(rows)
    focused = [r.data for r in rows if r.data in ('经营', '游历') and entry_tile_focused(screen, r)]
    assert len(focused) == 1
    op, screen, rows = frame('adventure-map')
    assert not is_entry(rows)


def test_entry_opens_adventure_through_verified_focus():
    op, screen, rows = frame('entry', **adventure_op())
    focused = next(r.data for r in rows if r.data in ('经营', '游历') and entry_tile_focused(screen, r))
    assert adventure_step(op, screen).result == R.WAIT
    assert pressed(op) == (['xbox_a'] if focused == '游历' else ['xbox_dpad_right'])


def test_real_map_reads_unlocked_and_focused_locations():
    op, screen, rows = frame('adventure-map')
    locations = adventure_locations(screen, rows)
    assert [name for name, _, unlocked, _ in locations if unlocked] == ['制造区1']
    assert [name for name, _, _, focused in locations if focused] == ['制造区1']
    op, screen, rows = frame('adventure-map-locked-focus')
    assert [name for name, _, _, focused in adventure_locations(screen, rows) if focused] == ['制造区2']
    op, screen, rows = frame('adventure-map-traditional-label')  # OCR: 製造区1
    assert [(name, focused) for name, _, unlocked, focused in adventure_locations(screen, rows) if unlocked] == [
        ('制造区1', True)]


def test_focused_unlocked_location_is_opened_and_others_steer_back():
    op, screen, _ = frame('adventure-map', **adventure_op())
    adventure_step(op, screen)
    assert pressed(op) == ['xbox_a'] and op._current == '制造区1'
    op, screen, _ = frame('adventure-map-locked-focus', **adventure_op())
    adventure_step(op, screen)
    assert pressed(op) == ['xbox_dpad_left'] and getattr(op, '_current', None) is None


def test_claim_then_confirm_then_dispatch_with_longest_unlocked_time():
    op, screen, _ = frame('adventure-claimable', **adventure_op(_current='制造区1'))
    settled(op, screen)
    assert pressed(op) == ['xbox_start']
    op, screen, _ = frame('adventure-claim-result', op)
    adventure_step(op, screen)
    op, screen, _ = frame('adventure-dispatchable', op)
    settled(op, screen)  # opens 游历时间选择
    op, screen, _ = frame('duration-3min-focused', op)
    adventure_step(op, screen)  # 20小时 is locked: move to 15分钟
    op, screen, _ = frame('duration-15min-focused', op)
    adventure_step(op, screen)
    assert op._duration_chosen == '15分钟'
    op, screen, _ = frame('adventure-duration-chosen', op)
    settled(op, screen)  # 自动选择邦布
    settled(op, screen)  # 派遣
    op, screen, _ = frame('adventure-dispatched', op)
    settled(op, screen)  # 提前收获 is never pressed; close the panel
    assert pressed(op) == ['xbox_start', 'xbox_a', 'xbox_a', 'xbox_dpad_right', 'xbox_a', 'xbox_y',
                           'xbox_start', 'xbox_b']
    assert op._done == {'制造区1'} and op._results == ['制造区1收获', '制造区1派遣']


def test_running_trip_is_left_alone_and_finished_map_returns_to_entry():
    op, screen, _ = frame('adventure-dispatched', **adventure_op(_current='制造区1'))
    settled(op, screen)
    assert pressed(op) == ['xbox_b'] and op._done == {'制造区1'}
    op, screen, _ = frame('adventure-map', op)
    assert adventure_step(op, screen).result == R.WAIT  # decided on a second frame only
    assert pressed(op) == ['xbox_b'] and not getattr(op, '_left_map', False)
    adventure_step(op, screen)
    assert pressed(op) == ['xbox_b', 'xbox_b'] and op._left_map
    op, screen, _ = frame('entry', op)
    assert adventure_step(op, screen).is_success


@pytest.mark.parametrize('claim,dispatch,expected', [(False, True, ['xbox_b']), (True, False, ['xbox_start'])])
def test_claim_and_dispatch_switches_are_respected(claim, dispatch, expected):
    op, screen, _ = frame('adventure-claimable', claim=claim, dispatch=dispatch, duration='20小时', _current='制造区1')
    settled(op, screen)
    assert pressed(op) == expected
    op, screen, _ = frame('adventure-dispatchable', claim=claim, dispatch=False, duration='20小时', _current='制造区1')
    settled(op, screen)
    assert pressed(op)[-1] == 'xbox_b'


def test_panel_is_not_acted_on_while_its_reading_changes():
    op, screen, _ = frame('adventure-dispatchable', **adventure_op(_current='制造区1'))
    assert adventure_step(op, screen).result == R.WAIT
    op, screen, _ = frame('adventure-claimable', op)  # the button changed: wait again
    assert adventure_step(op, screen).result == R.WAIT
    op.ctx.controller.btn_press.assert_not_called()
    adventure_step(op, screen)
    assert pressed(op) == ['xbox_start']


def test_hidden_map_focus_is_revealed_once_then_required():
    op, screen, _ = frame('adventure-map', **adventure_op())
    screen[300:520, 100:600] = screen[300:520, 100:600] // 4  # no chevrons: focus hidden
    adventure_step(op, screen)
    assert pressed(op) == ['xbox_dpad_up']
    assert adventure_step(op, screen).result == R.RETRY
    assert pressed(op) == ['xbox_dpad_up']


def test_panel_not_opened_by_the_flow_is_closed_without_action():
    op, screen, _ = frame('adventure-claimable', **adventure_op())
    settled(op, screen)
    assert pressed(op) == ['xbox_b']


def test_duration_tiles_read_lock_and_focus():
    op, screen, rows = frame('duration-3min-focused')
    tiles = duration_tiles(screen, rows)
    assert [t[0] for t in tiles if t[2]] == ['3分钟', '15分钟']
    assert [t[0] for t in tiles if t[3]] == ['3分钟']


def test_configured_unlocked_time_is_taken_as_is():
    op, screen, _ = frame('duration-3min-focused', **adventure_op())
    op.duration = '3分钟'
    adventure_step(op, screen)
    assert pressed(op) == ['xbox_a'] and op._duration_chosen == '3分钟'


def test_locked_auto_manage_falls_back_to_manual_flow():
    op, screen, _ = frame('entry')
    assert auto_manage_step(op, screen).result == R.WAIT
    assert pressed(op) == ['xbox_x']
    op, screen, _ = frame('manage-log-locked', op)
    auto_manage_step(op, screen)
    assert pressed(op)[-1] == 'xbox_b' and op._manage_locked
    op, screen, _ = frame('entry', op)
    result = auto_manage_step(op, screen)
    assert result.is_success and result.status == '未开启自动托管'
    assert pressed(op) == ['xbox_x', 'xbox_b']
    op, screen, _ = frame('manage-locked-dialog')
    auto_manage_step(op, screen)
    assert pressed(op) == ['xbox_a']


def test_arrival_closes_the_daily_log_until_the_entry_is_verified():
    op, screen, _ = frame('manage-log-locked')
    assert arrival_step(op, screen).result == R.WAIT
    assert pressed(op) == ['xbox_b']
    op, screen, _ = frame('entry', op)
    assert arrival_step(op, screen).is_success
    op, screen, _ = frame('adventure-map')
    assert arrival_step(op, screen).result == R.WAIT
    op.ctx.controller.btn_press.assert_not_called()


def test_yum_cha_opens_neighbourhood_then_the_verified_tile():
    op, screen, _ = frame('entry')
    assert yum_cha_step(op, screen).result == R.WAIT
    assert pressed(op) == ['xbox_start']
    op, screen, rows = frame('neighbourhood', op)
    assert [r.data for r in rows if 640 < r.center.y < 720 and neighbourhood_focused(screen, r)] == ['饮茶仙']
    yum_cha_step(op, screen)
    assert pressed(op) == ['xbox_start', 'xbox_a']


def test_wishes_are_never_submitted_and_missing_procurement_is_reported():
    op, screen, _ = frame('yum-cha-wishes')
    yum_cha_step(op, screen)
    assert pressed(op) == ['xbox_b'] and op._yum_result == '定期采办未解锁'
    op, screen, _ = frame('neighbourhood', op)
    yum_cha_step(op, screen)
    op, screen, _ = frame('entry', op)
    result = yum_cha_step(op, screen)
    assert result.is_success and result.status == '定期采办未解锁'
    assert pressed(op) == ['xbox_b', 'xbox_b'] and 'xbox_x' not in pressed(op)
