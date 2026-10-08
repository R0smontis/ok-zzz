from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from onedragon.base.geometry.rectangle import Rect
from onedragon.base.matcher.ocr.ocr_match_result import OcrMatchResult
from onedragon.base.operation.operation_round_result import OperationRoundResult, OperationRoundResultEnum
from zzz_od.application.hollow_zero.lost_void.bounty_progress import parse_progress_text, read_progress
from zzz_od.application.hollow_zero.lost_void.lost_void_app import LostVoidApp


def word(text, x=0, y=0, w=90, h=25):
    return OcrMatchResult(c=.99, x=x, y=y, w=w, h=h, data=text)


@pytest.mark.parametrize('text,expected', [
    ('2500/2500', (2500, 2500)), ('1250/2500', (1250, 2500)),
    ('0/8000', (0, 8000)), ('8000/8000', (8000, 8000)),
    ('悬赏进度 ２，５００ ／ ２，５００', (2500, 2500)),
    ('2 500 / 15 000', (2500, 15000)), ('25OO/25OO', (2500, 2500)),
    ('2500', None), ('2500 2500', None), ('0/0', None),
    ('25000/2500', None), ('1/2500 1/8000', None), ('', None),
    ('-1/2500', None), ('1.5/2500', None), ('2500/2500.0', None),
])
def test_progress_reads_both_numbers_and_rejects_ambiguous_text(text, expected):
    assert parse_progress_text(text) == expected


def test_ocr_can_split_fraction_across_adjacent_boxes():
    assert read_progress([word('2500', 0, w=70), word('/', 75, w=10),
                          word('2500', 90, w=70)]) == (2500, 2500)


def test_different_rows_and_distant_boxes_are_not_joined():
    assert read_progress([word('2500', 0), word('/2500', 500)]) is None
    assert read_progress([word('2500', 0), word('/2500', 0, y=60)]) is None
    assert read_progress([word('0/2500'), word('8000/8000', y=60)]) is None


@pytest.fixture
def app():
    task = object.__new__(LostVoidApp)
    task.config = SimpleNamespace(is_bounty_commission_mode=True, mission_name='特遣调查')
    task.run_record = SimpleNamespace(bounty_commission_complete=False, is_finished_by_day=False)
    task.last_screenshot = np.zeros((1080, 1920, 3), np.uint8)
    task.node_retry_times, task.node_max_retry_times = 0, 5
    task._after_round_wait = lambda **_kwargs: None
    task.round_by_find_area = Mock(return_value=OperationRoundResult(OperationRoundResultEnum.SUCCESS))
    task.ctx = SimpleNamespace(screen_loader=SimpleNamespace(get_area=lambda *_args:
        SimpleNamespace(rect=Rect(736, 12, 1138, 92))), ocr=SimpleNamespace(ocr=Mock()))
    task.save_screenshot = Mock(return_value='saved.png')
    return task


@pytest.mark.parametrize('score', ['2500/2500', '8000/8000', '15000/15000'])
def test_completed_progress_routes_to_reward_claim_without_another_run(app, score):
    app.ctx.ocr.ocr.return_value = [word(score)]
    result = app.check_bounty_commission_before()
    assert result.is_success and result.status == app.STATUS_ENOUGH_TIMES
    assert app.run_record.bounty_commission_complete
    app.ctx.ocr.ocr.assert_called_once()


@pytest.mark.parametrize('mission,expected', [('特遣调查', LostVoidApp.STATUS_AGAIN),
                                             ('矩阵行动', LostVoidApp.STATUS_AGAIN_MATRIX)])
def test_incomplete_progress_preserves_mission_route(app, mission, expected):
    app.config.mission_name = mission
    app.ctx.ocr.ocr.return_value = [word('1250/2500')]
    result = app.check_bounty_commission_before()
    assert result.is_success and result.status == expected
    assert not app.run_record.bounty_commission_complete


def test_small_text_retry_uses_enlarged_crop(app):
    app.ctx.ocr.ocr.side_effect = [[], [word('2500/2500')]]
    result = app.check_bounty_commission_before()
    assert result.is_success and result.status == app.STATUS_ENOUGH_TIMES
    assert app.ctx.ocr.ocr.call_args_list[1].args[0].shape[:2] == (160, 804)


def test_unknown_progress_does_not_claim_completion_and_retains_evidence(app):
    app.node_retry_times = 5
    app.ctx.ocr.ocr.return_value = [word('2500')]
    result = app.check_bounty_commission_before()
    assert result.result == OperationRoundResultEnum.RETRY
    assert '悬赏进度' in result.status and '2500' in result.status
    assert not app.run_record.bounty_commission_complete
    app.save_screenshot.assert_called_once()


def test_normal_run_count_mode_does_not_require_bounty_ocr(app):
    app.config.is_bounty_commission_mode = False
    assert app.check_bounty_commission_before().status == app.STATUS_AGAIN
    app.ctx.ocr.ocr.assert_not_called()


def test_failure_is_reported_in_task_panel_with_reason():
    from src.tasks.app_task_base import AppTaskBase
    task = SimpleNamespace(name='迷失之地', info={}, log_error=Mock(), log_info=Mock(),
        ctx=SimpleNamespace(run_context=SimpleNamespace(last_application_result=SimpleNamespace(
            status='悬赏进度未识别到当前值/目标值（OCR：无文字）'))))
    AppTaskBase.report_run_result(task, SimpleNamespace(finish_reason='FAILED'))
    assert '悬赏进度' in task.info['执行结果']
    assert '悬赏进度' in task.log_error.call_args.args[0]
    task.log_info.assert_not_called()


@pytest.fixture(scope='module')
def real_ocr():
    from ok.task.TaskExecutor import TaskExecutor
    from src.gpu_ocr import install_gpu_ocr
    from onedragon.base.matcher.ocr.ok_ocr_matcher import OkOcrMatcher
    install_gpu_ocr()
    executor = TaskExecutor.__new__(TaskExecutor)
    executor.config = {'ocr': {'default': {'lib': 'onnxocr', 'params': {}}}}
    lib = executor._create_ocr_lib('default')
    return OkOcrMatcher(lambda: lib)


@pytest.mark.parametrize('fixture', ['bounty_complete_2500_header.png', 'bounty_complete_8000_gamepad_header.png'])
@pytest.mark.parametrize('width,height', [(1280, 720), (1920, 1080), (2560, 1440), (3840, 2160)])
def test_user_screenshot_progress_replays_with_real_ocr(app, real_ocr, width, height, fixture):
    import cv2
    from pathlib import Path
    from src.frame_geometry import normalize_bgr
    from onedragon.base.screen.screen_loader import ScreenContext
    from onedragon.base.matcher.ocr.ocr_service import OcrService
    header = cv2.imread(str(Path(__file__).parent / 'fixtures/lost_void' / fixture))
    frame = np.zeros((1080, 1920, 3), np.uint8)
    frame[:header.shape[0]] = header
    app.last_screenshot = normalize_bgr(cv2.resize(frame, (width, height)))
    loader = ScreenContext()
    loader.reload()
    app.ctx = SimpleNamespace(ocr=real_ocr, ocr_service=OcrService(ocr_matcher=real_ocr), screen_loader=loader)
    # 使用真实入口按钮判断，不使用上面单元测试的识别替身。
    del app.round_by_find_area
    result = app.check_bounty_commission_before()
    assert result.is_success and result.status == app.STATUS_ENOUGH_TIMES
    assert app.run_record.bounty_commission_complete


def test_gamepad_opens_and_claims_bounty_list_on_real_screens(app, real_ocr):
    import cv2
    from pathlib import Path
    from src.frame_geometry import normalize_bgr
    from onedragon.base.screen.screen_loader import ScreenContext
    from onedragon.base.matcher.ocr.ocr_service import OcrService
    fixtures = Path(__file__).parent / 'fixtures/lost_void'
    entry = normalize_bgr(cv2.imread(str(fixtures / 'bounty_entry_gamepad.png')))
    bounty_list = normalize_bgr(cv2.imread(str(fixtures / 'bounty_list_gamepad.png')))
    loader = ScreenContext()
    loader.reload()
    app.ctx = SimpleNamespace(ocr=real_ocr, ocr_service=OcrService(ocr_matcher=real_ocr), screen_loader=loader,
                              controller=Mock(background_mode=True),
                              game_config=SimpleNamespace(background_gamepad_type='xbox'))
    del app.round_by_find_area
    app.last_screenshot = entry
    assert app.open_reward_list().result == OperationRoundResultEnum.WAIT
    app.ctx.controller.btn_press.assert_called_once_with('xbox_y', press_time=.12)
    # The entry button stays readable behind a modal that has not opened yet: no claim press.
    assert app.claim_all().result == OperationRoundResultEnum.RETRY
    app.last_screenshot = bounty_list
    assert app.open_reward_list().is_success
    assert app.claim_all().is_success
    assert app.ctx.controller.btn_press.call_args_list[-1].args == ('xbox_x',)
    app.last_screenshot = entry
    # A verified open resets the bound, so a later stuck entry gets three fresh presses.
    for _ in range(3):
        app.open_reward_list()
    assert app.open_reward_list().is_fail
