"""兑换码 in the background on real frames: the panel is driven with Y paste, d-pad and A."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import pytest

from onedragon.base.geometry.rectangle import Rect
from onedragon.base.operation.operation_round_result import OperationRoundResultEnum as R
from src.navigation import redemption
from src.navigation.redemption import (button_focused, code_panel, more_panel_open, open_code_panel,
                                       open_more, redeem_round, same_code)
from zzz_od.application.redemption_code.redemption_code_app import RedemptionCodeApp
from test_lost_void_background_menus import operation

BASE = Path(__file__).parent / 'fixtures/redemption'


def frame(name, op=None):
    op = op or operation(RedemptionCodeApp)
    screen = cv2.cvtColor(cv2.imread(str(BASE / f'{name}.png')), cv2.COLOR_BGR2RGB)
    payload = json.loads((BASE / f'{name}.json').read_text(encoding='utf-8'))
    rows = [SimpleNamespace(data=r['text'], center=Rect(r['rect'][0], r['rect'][1], r['rect'][0] + r['rect'][2],
                                                        r['rect'][1] + r['rect'][3]).center)
            for r in payload['result']['ocr']]
    op.ctx.ocr_service = SimpleNamespace(get_ocr_result_list=lambda image, rect, **_: [
        r for r in rows if rect.x1 <= r.center.x < rect.x2 and rect.y1 <= r.center.y < rect.y2])
    op.last_screenshot = screen
    return op, screen


def pressed(op):
    return [call.args[0] for call in op.ctx.controller.btn_press.call_args_list]


@pytest.fixture
def pasted(monkeypatch):
    calls = []
    monkeypatch.setattr(redemption, 'paste_code', lambda ctx, code: calls.append(code))
    return calls


def redeeming(name, op=None, codes=('ZZZ888',)):
    op, screen = frame(name, op)
    op.__dict__.setdefault('code_idx', 0)
    used = op.__dict__.setdefault('_used', [])
    return op, redeem_round(op, screen, list(codes), used.append)


def test_real_panels_are_told_apart():
    op, screen = frame('redeem-menu')
    assert not more_panel_open(op, screen) and code_panel(op, screen) is None
    op, screen = frame('redeem-more-panel')
    assert more_panel_open(op, screen) and code_panel(op, screen) is None
    op, screen = frame('redeem-code-panel')
    assert code_panel(op, screen) == ('', '', '兑换')
    assert not button_focused(screen)
    op, screen = frame('redeem-code-button')
    assert code_panel(op, screen)[0] == 'ZZZ888' and button_focused(screen)
    op, screen = frame('redeem-code-result')
    assert code_panel(op, screen)[1].startswith('兑换成功')


def test_menu_opens_more_and_the_grid_reaches_the_code_cell():
    op, screen = frame('redeem-menu')
    assert open_more(op, screen).result == R.WAIT
    assert pressed(op) == ['xbox_dpad_right']  # 代理人 → 更多: 4 steps right through the wrap, not 8 left
    op, screen = frame('redeem-more-panel')
    assert open_more(op, screen).is_success
    assert open_code_panel(op, screen).result == R.WAIT
    assert pressed(op) == ['xbox_dpad_down']
    op, screen = frame('redeem-code-focus')
    assert open_code_panel(op, screen).is_success
    assert pressed(op) == ['xbox_a']
    op, screen = frame('redeem-code-panel')
    assert open_code_panel(op, screen).is_success and pressed(op) == []


def test_empty_field_is_pasted_then_the_button_focused_and_pressed(pasted):
    op, result = redeeming('redeem-code-panel')
    assert result.result == R.WAIT and pasted == ['ZZZ888'] and pressed(op) == []
    op, result = redeeming('redeem-code-pasted', op)
    assert result.result == R.WAIT and pressed(op) == ['xbox_dpad_down']
    op, result = redeeming('redeem-code-button', op)
    assert result.result == R.WAIT and pressed(op)[-1] == 'xbox_a' and op._used == []
    op, result = redeeming('redeem-code-result', op)
    assert op._used == ['ZZZ888'] and op.code_idx == 1
    op, result = redeeming('redeem-code-result', op)
    assert result.is_success and result.status == '全部兑换完毕'


def test_other_text_is_cleared_before_the_next_code(pasted):
    op, _ = frame('redeem-code-result')
    op.code_idx = 0
    op, result = redeeming('redeem-code-result', op, codes=('NEWCODE1',))
    assert result.result == R.WAIT and pressed(op) == ['xbox_y'] and pasted == []
    op, result = redeeming('redeem-code-cleared', op, codes=('NEWCODE1',))
    assert pasted == ['NEWCODE1']


def test_cooling_button_is_not_pressed(pasted, monkeypatch):
    op, screen = frame('redeem-code-button')
    op.code_idx = 0
    monkeypatch.setattr(redemption, 'code_panel', lambda o, s: ('ZZZ888', '', '兑换(3)'))
    result = redeem_round(op, screen, ['ZZZ888'], Mock())
    assert result.result == R.WAIT and pressed(op) == []


def test_bounded_paste_attempts(pasted):
    op, _ = frame('redeem-code-panel')
    op.code_idx = 0
    for _ in range(3):
        op, result = redeeming('redeem-code-panel', op)
        assert result.result == R.WAIT
    op, result = redeeming('redeem-code-panel', op)
    assert result.is_fail and len(pasted) == 3


@pytest.mark.parametrize('read,code,same', [('ZZZ888', 'ZZZ888', True), ('ZZ2888', 'ZZZ888', False),
                                            ('PH0ENIX1021', 'PHOENIX1021', True), ('', 'A', False)])
def test_code_comparison_tolerates_only_o_and_i(read, code, same):
    assert same_code(read, code) is same


def test_clipboard_text_is_restored(monkeypatch):
    import win32clipboard as cb
    store = {'text': '用户的剪贴板'}
    monkeypatch.setattr(cb, 'OpenClipboard', lambda *_: None)
    monkeypatch.setattr(cb, 'CloseClipboard', lambda: None)
    monkeypatch.setattr(cb, 'IsClipboardFormatAvailable', lambda fmt: store['text'] is not None)
    monkeypatch.setattr(cb, 'GetClipboardData', lambda fmt: store['text'])
    monkeypatch.setattr(cb, 'EmptyClipboard', lambda: store.update(text=None))
    monkeypatch.setattr(cb, 'SetClipboardText', lambda text, fmt: store.update(text=text))
    monkeypatch.setattr(redemption.time, 'sleep', lambda *_: None)
    seen = []
    ctx = SimpleNamespace(game_config=SimpleNamespace(background_gamepad_type='xbox'),
                          controller=SimpleNamespace(btn_press=lambda key, press_time: seen.append((key, store['text']))))
    redemption.paste_code(ctx, 'ZZZ888')
    assert seen == [('xbox_y', 'ZZZ888')] and store['text'] == '用户的剪贴板'


def test_published_codes_are_downloaded_once_and_cached(tmp_path, monkeypatch):
    from src.runtime import redemption_feed as feed
    monkeypatch.setattr(feed, '_cache_path', lambda: str(tmp_path / 'codes.yml'))
    calls = []

    class Response:
        def __init__(self, text): self.text = text
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self): return self.text.encode('utf-8')

    def urlopen(url, timeout):
        calls.append(url)
        if len(calls) == 1:
            raise OSError('offline mirror')
        return Response('codes:\n  NEWCODE1: 20991231\n  BAD: soon\n')

    monkeypatch.setattr(feed.urllib.request, 'urlopen', urlopen)
    assert feed.refresh() == {'NEWCODE1': 20991231}
    assert len(calls) == 2  # The second mirror answered.
    assert feed.refresh() == {'NEWCODE1': 20991231} and len(calls) == 2  # Fresh cache: no download.
    assert feed.cached_codes() == {'NEWCODE1': 20991231}


def test_unreachable_feed_keeps_the_last_copy(tmp_path, monkeypatch):
    from src.runtime import redemption_feed as feed
    cache = tmp_path / 'codes.yml'
    cache.write_text('codes:\n  OLD: 20991231\n', encoding='utf-8')
    import os
    os.utime(cache, (0, 0))  # Stale: a download is attempted.
    monkeypatch.setattr(feed, '_cache_path', lambda: str(cache))
    monkeypatch.setattr(feed.urllib.request, 'urlopen', Mock(side_effect=OSError('offline')))
    assert feed.refresh() == {'OLD': 20991231}
