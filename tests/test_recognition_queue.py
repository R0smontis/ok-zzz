import threading
from concurrent.futures import Future, ThreadPoolExecutor
from unittest.mock import Mock
from src.recognition_queue import SingleFlightChecks


def test_slow_gpu_never_builds_a_backlog_of_old_frames():
    checks = SingleFlightChecks()
    executor = Mock()
    executor.submit.side_effect = lambda *args: Future()
    detector = Mock()
    first = checks.submit('flash', executor, detector, 'frame-0')
    for index in range(1, 1001):
        assert checks.submit('flash', executor, detector, f'frame-{index}') is None
    executor.submit.assert_called_once_with(detector, 'frame-0')
    first.set_result(False)
    latest = checks.submit('flash', executor, detector, 'frame-1001')
    assert latest is not first
    assert executor.submit.call_args.args == (detector, 'frame-1001')
    assert checks.snapshot()['skipped_busy'] == {'flash': 1000}


def test_detection_kinds_are_independent_and_concurrent_submit_is_bounded():
    checks = SingleFlightChecks(); executor = Mock()
    executor.submit.side_effect = lambda *args: Future()
    with ThreadPoolExecutor(max_workers=8) as workers:
        list(workers.map(lambda _: checks.submit('agent', executor, str, 'frame'), range(100)))
    checks.submit('flash', executor, str, 'frame')
    assert executor.submit.call_count == 2
    assert set(checks.snapshot()['pending']) == {'agent', 'flash'}


def test_sync_probe_waits_then_checks_the_requested_fresh_frame():
    checks = SingleFlightChecks(); entered = threading.Event(); release = threading.Event()
    def detect(frame):
        if frame == 'old': entered.set(); release.wait(2)
        return frame
    with ThreadPoolExecutor(max_workers=2) as workers:
        old = checks.submit('flash', workers, detect, 'old')
        assert entered.wait(1)
        call = workers.submit(checks.submit, 'flash', workers, detect, 'new', sync=True)
        assert not call.done()
        release.set()
        assert old.result(1) == 'old'
        assert call.result(1).result(1) == 'new'


def test_failed_or_cancelled_work_does_not_block_subsequent_frames():
    checks=SingleFlightChecks();executor=Mock();executor.submit.side_effect=lambda *a:Future()
    old=checks.submit('flash',executor,str,'old');old.cancel()
    fresh=checks.submit('flash',executor,str,'new')
    assert fresh is not old


def test_battle_dispatch_uses_single_flight_for_every_detection(monkeypatch):
    from types import SimpleNamespace
    from zzz_od.auto_battle import auto_battle_context as module
    battle=module.AutoBattleContext.__new__(module.AutoBattleContext)
    battle.ctx=SimpleNamespace(model_config=SimpleNamespace(flash_classifier_gpu=True))
    battle.dodge_context=Mock();battle.agent_context=Mock();battle.target_context=Mock()
    battle.check_quick_assist=Mock();battle.check_switch_backup=Mock()
    battle.state_record_service=Mock();battle.auto_op=None;battle.auto_ultimate_enabled=True
    battle.recognition_checks=SingleFlightChecks()
    cpu=Mock();gpu=Mock()
    cpu.submit.side_effect=lambda *a:Future();gpu.submit.side_effect=lambda *a:Future()
    monkeypatch.setattr(module,'_battle_state_check_executor',cpu)
    monkeypatch.setattr(module,'gpu_executor',gpu)
    for index in range(100):
        assert battle.check_battle_state(f'frame-{index}',float(index),attack_hud_visible=True)
    assert gpu.submit.call_count==1 and cpu.submit.call_count==5
    assert set(battle.recognition_checks.snapshot()['pending'])=={'audio','flash','agent','target','quick_assist','switch_backup'}
