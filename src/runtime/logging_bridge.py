"""Forward engine progress to the framework's existing log file and UI."""
import logging
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

_event_times = {}
_event_lock = threading.Lock()


def log_runtime_event(kind, details):
    titles = {'assistant_combat_start': '开始10秒战斗', 'assistant_input_phase': '输入阶段',
        'realtime_response': '实时战斗响应', 'dialogue_input': '对话操作',
        'video_segment': '录制视频分段', 'battle_entry': '进入战斗',
        'assistant_warning_rejected': '预警未采用'}
    if kind not in titles:
        return
    labels = {'task':'任务','source':'依据','phase':'阶段','reason':'原因',
        'warning':'预警','response':'响应','fallback_reason':'回退原因','video':'文件','action':'操作'}
    content = '，'.join(f'{labels.get(key,key)}={value}' for key, value in details.items()
        if key in ('task', 'source', 'phase', 'reason', 'warning', 'response', 'fallback_reason', 'video', 'action'))
    message = f'{titles[kind]}：{content}'
    now = time.monotonic()
    with _event_lock:
        if now-_event_times.get(message, -10) < 1:
            return
        _event_times[message] = now
        if len(_event_times) > 128:
            for key in list(_event_times):
                if now-_event_times[key] > 10:
                    del _event_times[key]
    logging.getLogger('ok').info('执行状态:%s', message)


class FrameworkLogBridge(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self._recent = {}
        self._lock = threading.Lock()

    def emit(self, record):
        message = record.getMessage()
        now = time.monotonic()
        with self._lock:
            key = (record.levelno, message)
            if now-self._recent.get(key, -10) < 1:
                return
            self._recent[key] = now
            if len(self._recent) > 512:
                self._recent = {k: v for k, v in self._recent.items() if now-v < 10}
        logging.getLogger('ok').log(record.levelno, '一条龙:%s', message)


def install_runtime_logging():
    framework = logging.getLogger('ok')
    if not any(getattr(handler, '_zzz_runtime_file', False) for handler in framework.handlers):
        path = Path('logs/runtime.log')
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(path, maxBytes=4 * 1024 * 1024, backupCount=5, encoding='utf-8')
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        handler._zzz_runtime_file = True
        framework.addHandler(handler)
    from onedragon.utils.log_utils import log
    if not any(isinstance(handler, FrameworkLogBridge) for handler in log.handlers):
        log.addHandler(FrameworkLogBridge())
