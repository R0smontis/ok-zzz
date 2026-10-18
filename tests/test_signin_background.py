"""每日签到 alternatives in the background on real frames (报刊亭 / 刮刮卡)."""
import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import pytest

from onedragon.base.geometry.rectangle import Rect
from onedragon.base.operation.operation_round_result import OperationRoundResultEnum as R
from onedragon.base.screen.screen_loader import ScreenContext
from src.navigation.signin import ALREADY_DONE, newsstand_step
from zzz_od.application.scratch_card.scratch_card_app import ScratchCardApp
from test_lost_void_background_menus import operation

BASE = Path(__file__).parent / 'fixtures/signin'
LOADER = ScreenContext()
LOADER.reload()


def frame(name, op=None):
    op = op or operation(ScratchCardApp)
    screen = cv2.cvtColor(cv2.imread(str(BASE / f'{name}.png')), cv2.COLOR_BGR2RGB)
    payload = json.loads((BASE / f'{name}.json').read_text(encoding='utf-8'))
    rows = [SimpleNamespace(data=r['text'], center=Rect(r['rect'][0], r['rect'][1], r['rect'][0] + r['rect'][2],
                                                        r['rect'][1] + r['rect'][3]).center)
            for r in payload['result']['ocr']]
    op.ctx.ocr_service = SimpleNamespace(get_ocr_result_list=lambda image, rect=None, **_: [
        r for r in rows if rect is None or (rect.x1 <= r.center.x < rect.x2 and rect.y1 <= r.center.y < rect.y2)])
    op.ctx.screen_loader = LOADER
    op.last_screenshot = screen
    return op, screen


def pressed(op):
    return [call.args[0] for call in op.ctx.controller.btn_press.call_args_list]


def test_newsstand_opens_the_scratch_card_with_x():
    op, screen = frame('scratch-stuck')
    assert newsstand_step(op, screen).result == R.WAIT
    assert pressed(op) == ['xbox_x']


def test_reward_taken_elsewhere_is_confirmed_then_reported():
    op, screen = frame('scratch-open')
    assert newsstand_step(op, screen).result == R.WAIT
    assert pressed(op) == ['xbox_a']
    op, screen = frame('scratch-stuck', op)
    result = newsstand_step(op, screen)
    assert result.is_success and result.status == ALREADY_DONE
    assert pressed(op) == ['xbox_a']  # No second X: the page is left for 返回大世界.


def test_ignored_open_is_bounded():
    op, screen = frame('scratch-stuck')
    for _ in range(3):
        assert newsstand_step(op, screen).result == R.WAIT
    assert newsstand_step(op, screen).is_fail


def test_trigrams_divines_with_a_and_accepts_the_taken_reward():
    from src.navigation.signin import trigrams_step
    from zzz_od.application.trigrams_collection.trigrams_collection_app import TrigramsCollectionApp
    op, screen = frame('trigram-1', operation(TrigramsCollectionApp))
    op.claim_reward = False
    assert trigrams_step(op, screen).result == R.WAIT and pressed(op) == ['xbox_a']  # A 占卜
    op, screen = frame('trigram-2', op)
    assert trigrams_step(op, screen).result == R.WAIT and op.claim_reward  # A 确认
    op, screen = frame('trigram-1', op)
    assert trigrams_step(op, screen).is_success and pressed(op) == ['xbox_a', 'xbox_a']


def test_scratch_card_is_scratched_with_right_stick_strokes():
    from src.navigation.signin import scratch_step
    op, screen = frame('scratch-page')
    assert scratch_step(op, screen).result == R.WAIT
    assert pressed(op) == ['xbox_rs_up', 'xbox_rs_right', 'xbox_rs_down', 'xbox_rs_left'] * 3
    # Scraped: the prizes show and only 「B 返回」 is left.
    op, screen = frame('scratch-what', op)
    assert scratch_step(op, screen).is_success


def test_scratch_waits_for_the_card_before_any_stroke():
    from src.navigation.signin import scratch_step
    op, screen = frame('scratch-stuck')
    assert scratch_step(op, screen).result == R.RETRY and pressed(op) == []


def test_back_button_prompt_ends_the_scrape_without_a_second_press(monkeypatch):
    """手柄提示为「B 返回」（无「刮一刮」）时按已刮开处理，不再无限等待。"""
    import numpy as np
    from src.navigation.signin import scratch_step
    op = operation(ScratchCardApp)
    screen = np.full((1080, 1920, 3), 255, np.uint8)  # 涂层未刮开：不是黑屏
    op.round_by_find_area = lambda *args, **kwargs: SimpleNamespace(is_success=True)
    op.ctx.ocr_service = SimpleNamespace(get_ocr_result_list=lambda image, rect=None, **_: [
        SimpleNamespace(data='B 返回', center=Rect(940, 745, 940, 745).center)])
    result = scratch_step(op, screen)
    assert result.is_success
