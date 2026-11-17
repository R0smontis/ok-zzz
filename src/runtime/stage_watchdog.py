"""Independent, low-frequency stage timeout evidence capture; never drives game input."""
import functools
import json
import logging
from pathlib import Path
import sys
import threading
import time
import traceback

from ok import ConfigOption

log = logging.getLogger(__name__)
def validate_setting(key, value):
    if key == '阶段超时秒数' and (type(value) is not int or not 30 <= value <= 7200):
        return False, '阶段超时秒数必须为30至7200的整数'
    return True, None


option = ConfigOption('阶段超时检测', {'启用': True, '阶段超时秒数': 300, '自动打包错误记录': False},
                      validator=validate_setting)


class StageWatchdog:
    def __init__(self, settings, report, clock=time.monotonic):
        self.settings, self.report, self.clock = settings, report, clock
        self.lock = threading.RLock()
        self.stack = []
        self.stop_event = threading.Event()
        self.thread = None

    def enter(self, operation):
        with self.lock:
            entry = {'operation': operation, 'node': None, 'since': self.clock(), 'reported': False}
            self.stack.append(entry)
            return entry

    def leave(self, entry):
        with self.lock:
            self.stack = [item for item in self.stack if item is not entry]
            if self.stack:
                self.stack[-1]['since'] = self.clock()

    def tick(self):
        config = self.settings()
        with self.lock:
            if not self.stack:
                return
            entry = self.stack[-1]
            op = entry['operation']
            run = op.ctx.run_context
            now = self.clock()
            node = getattr(op, '_current_node', None)
            key = id(node)
            if (not config.get('启用', True) or run.is_context_stop or run.is_context_pause):
                entry['since'] = now
                return
            if entry['node'] != key:
                entry.update(node=key, since=now, reported=False)
            elapsed = now - entry['since']
            if entry['reported'] or elapsed < config.get('阶段超时秒数', 300):
                return
            entry['reported'] = True
            detail = {'operation': op.op_name, 'stage': getattr(node, 'cn', '初始化'),
                      'elapsed_seconds': round(elapsed, 1)}
        self.report(op, detail, bool(config.get('自动打包错误记录', False)))

    def start(self):
        def watch():
            while not self.stop_event.wait(1):
                try:
                    self.tick()
                except Exception:
                    log.exception('阶段超时检测失败')
        self.thread = threading.Thread(target=watch, name='stage-watchdog', daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()


active = None


def monitored_operation(function):
    @functools.wraps(function)
    def execute(self, *args, **kwargs):
        monitor = active
        if monitor is None:
            return function(self, *args, **kwargs)
        entry = monitor.enter(self)
        try:
            return function(self, *args, **kwargs)
        finally:
            monitor.leave(entry)
    return execute


def capture_stall(op, detail, package):
    from ok import og
    from ok.core.events import communicate
    from onedragon.utils import os_utils
    from src.diagnostics.error_report import Failure, build_report, sanitize_text, _tail
    from src.diagnostics.recorder import recorder, runtime_snapshot
    root = Path(os_utils.get_work_dir())
    message = f"阶段长时间未推进：{detail['operation']} / {detail['stage']}（{detail['elapsed_seconds']}秒）"
    log.error(message)
    executor = og.executor
    runtime = runtime_snapshot(executor)
    runtime['stage_timeout'] = detail
    frame = getattr(executor, '_frame', None)
    failure = Failure(time=time.time(), task_name='程序阶段超时', message=message, runtime=runtime,
                      frame=frame.copy() if frame is not None else None)
    folder = root / 'debug' / 'stalls' / str(time.time_ns())
    folder.mkdir(parents=True)
    (folder / 'incident.json').write_text(sanitize_text(json.dumps(runtime, ensure_ascii=False, default=str)), encoding='utf-8')
    stacks = ''.join(f'\nThread {ident}\n' + ''.join(traceback.format_stack(stack))
                     for ident, stack in sys._current_frames().items())
    (folder / 'threads.log').write_text(sanitize_text(stacks), encoding='utf-8')
    for source in ('runtime.log', 'ok-script.log'):
        text = _tail(root / 'logs' / source)
        if text is not None:
            (folder / source).write_text(sanitize_text(text), encoding='utf-8')
    communicate.notification.emit(message, '程序阶段超时', True, True, None, None,
                                  [failure.frame] if failure.frame is not None else None)
    # Existing recorder is bounded to one minute; don't disrupt a user recording.
    try:
        if not recorder.active and not recorder.paused:
            recorder.start(root, duration=60, mode='截图', image_interval=1,
                           snapshot_provider=lambda: runtime_snapshot(executor))
        recorder.record('stage_timeout', **detail)
    except Exception:
        log.exception('阶段超时诊断录制未能启动')
    if package:
        try:
            archive = build_report(failure, root)
            import zipfile
            with zipfile.ZipFile(archive, 'a', zipfile.ZIP_DEFLATED) as bundle:
                for path in folder.iterdir():
                    bundle.write(path, 'stage-timeout/' + path.name)
            communicate.notification.emit('错误记录已保存：' + str(archive), '程序阶段超时',
                                          False, True, None, None, None)
        except Exception:
            log.exception('阶段超时错误记录打包失败')


def install():
    global active
    from ok import og
    active = StageWatchdog(lambda: og.global_config.get_config(option), capture_stall)
    active.start()
    return active
