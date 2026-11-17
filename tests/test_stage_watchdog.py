from types import SimpleNamespace
import threading
from concurrent.futures import ThreadPoolExecutor

from src.runtime.stage_watchdog import StageWatchdog


def setup_watch():
    now = [0.]
    config = {'启用': True, '阶段超时秒数': 30, '自动打包错误记录': False}
    reports = []
    watch = StageWatchdog(lambda: config, lambda *args: reports.append(args), clock=lambda: now[0])
    op = SimpleNamespace(op_name='迷失之地', _current_node=SimpleNamespace(cn='选择'),
                         ctx=SimpleNamespace(run_context=SimpleNamespace(is_context_pause=False, is_context_stop=False)))
    return watch, op, now, reports, config


def test_saved_settings_reload_and_invalid_timeout_recovers(tmp_path):
    import json
    from ok.util.config import Config
    from src.runtime.stage_watchdog import option
    path = tmp_path / (option.name + '.json')
    values = {'启用': True, '阶段超时秒数': 60, '自动打包错误记录': True}
    path.write_text(json.dumps(values), encoding='utf-8')
    loaded = Config(option.name, option.default_config, folder=str(tmp_path), validator=option.validator)
    assert dict(loaded) == values
    values['阶段超时秒数'] = 0
    path.write_text(json.dumps(values), encoding='utf-8')
    loaded = Config(option.name, option.default_config, folder=str(tmp_path), validator=option.validator)
    assert loaded['阶段超时秒数'] == 300
    assert loaded['自动打包错误记录'] is True


def test_stage_timeout_reports_once_and_new_stage_gets_new_deadline():
    watch, op, now, reports, _ = setup_watch()
    entry = watch.enter(op)
    watch.tick()
    now[0] = 30
    watch.tick()
    watch.tick()
    assert len(reports) == 1
    assert reports[0][1] == {'operation': '迷失之地', 'stage': '选择', 'elapsed_seconds': 30}
    op._current_node = SimpleNamespace(cn='战斗')
    watch.tick()
    now[0] = 59
    watch.tick()
    assert len(reports) == 1
    now[0] = 60
    watch.tick()
    assert len(reports) == 2
    watch.leave(entry)
    now[0] = 100
    watch.tick()
    assert len(reports) == 2


def test_nested_operation_pause_and_disabled_monitor_do_not_false_alarm():
    watch, op, now, reports, config = setup_watch()
    parent = watch.enter(op)
    watch.tick()
    child = watch.enter(op)
    watch.tick()
    now[0] = 29
    watch.leave(child)
    watch.tick()
    assert not reports
    op.ctx.run_context.is_context_pause = True
    now[0] = 100
    watch.tick()
    op.ctx.run_context.is_context_pause = False
    now[0] = 101
    watch.tick()
    assert not reports
    config['启用'] = False
    now[0] = 200
    watch.tick()
    assert not reports
    watch.leave(parent)


def test_blocked_operation_thread_still_reports_from_monitor():
    watch, op, now, reports, _ = setup_watch()
    entered, release = threading.Event(), threading.Event()
    def blocked():
        entry = watch.enter(op)
        entered.set()
        try:
            assert release.wait(5)
        finally:
            watch.leave(entry)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(blocked)
        try:
            assert entered.wait(5)
            watch.tick()
            now[0] = 31
            watch.tick()
            assert len(reports) == 1
        finally:
            release.set()
        future.result(timeout=5)
