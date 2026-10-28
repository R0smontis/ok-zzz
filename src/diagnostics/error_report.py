"""Error reports the user sends to the developer after a failure, only when they click for it.

There is no report server: the report is a local ZIP (failure screenshot with the UID masked,
sanitized log tails, the failed task's settings, version and system), and "send" opens a
pre-filled GitHub issue plus the report folder so the user attaches the ZIP themselves.
Nothing leaves the computer unless the user submits that issue.
"""
from __future__ import annotations

import json
import os
import platform
import re
import sys
import threading
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

LOG_TAIL_BYTES = 512 * 1024
MAX_FAILURES = 10
MERGE_SECONDS = 5
ISSUE_MESSAGE_CHARS = 300
LOG_SOURCES = (('logs/ok-script.log', 'ok-script.log'), ('.log/log.txt', 'game-engine.log'))
# Keys that are, or end with, a secret word ('password', 'game_account', '账号'); not keys that merely
# start with one, such as the daily's 「账号 01 执行计划」 (2026-10-28 report).
SECRET_KEY = re.compile(r'(account|password|passwd|pwd|token|secret|cookie|phone|mobile|账号|密码|手机号?)$', re.I)
SECRET_VALUE = re.compile(
    r'(?i)((?:password|passwd|pwd|token|secret|cookie|authorization|账号|密码)["\']?\s*[:=：]\s*["\']?)'
    r'(?:bearer\s+)?[^\s"\',}]+')


@dataclass
class Failure:
    time: float
    task_name: str
    message: str
    task_class: str | None = None
    info: dict = field(default_factory=dict)
    config: dict = field(default_factory=dict)
    frame: object = None
    runtime: dict = field(default_factory=dict)


class FailureRegistry:
    """Recent failures, newest last; listeners run on the thread that records (the GUI thread)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._failures: list[Failure] = []
        self.listeners = []

    def record(self, message, task_name=None, task=None, frame=None, runtime=None, now=None) -> Failure:
        now = time.time() if now is None else now
        name = task_name or getattr(task, 'name', None) or '程序'
        with self._lock:
            last = self._failures[-1] if self._failures else None
            # A task's log_error(notify) and the executor's exception report the same failure.
            if last is not None and now - last.time < MERGE_SECONDS and (
                    last.task_name == name or '程序' in (last.task_name, name)):
                failure = last
                if name != '程序':
                    failure.task_name = name
                if message and message not in failure.message:
                    failure.message = f'{failure.message}\n{message}' if failure.message else str(message)
            else:
                failure = Failure(time=now, task_name=name, message=str(message or ''))
                self._failures.append(failure)
                del self._failures[:-MAX_FAILURES]
            if task is not None:
                failure.task_class = type(task).__name__
                failure.info = _plain(getattr(task, 'info', {}) or {})
                failure.config = _plain(getattr(task, 'config', {}) or {})
            if frame is not None and failure.frame is None:
                failure.frame = frame.copy() if hasattr(frame, 'copy') else frame
            if runtime and not failure.runtime:
                failure.runtime = runtime
        for listener in list(self.listeners):
            try:
                listener(failure)
            except Exception:
                pass
        return failure

    def latest(self) -> Failure | None:
        with self._lock:
            return self._failures[-1] if self._failures else None

    def all(self) -> list[Failure]:
        with self._lock:
            return list(self._failures)


registry = FailureRegistry()


def _plain(mapping) -> dict:
    try:
        return json.loads(json.dumps(dict(mapping), ensure_ascii=False, default=str))
    except Exception:
        return {str(k): str(v) for k, v in dict(mapping).items()}


def sanitize_text(text: str, secrets=()) -> str:
    """Remove the user's home path, known secrets and password/token-like values from log text."""
    home = os.path.expanduser('~')
    for variant in {home, home.replace('\\', '/'), home.replace('\\', '\\\\')}:
        if variant and len(variant) > 3:
            text = re.sub(re.escape(variant), '%USERPROFILE%', text, flags=re.I)
    for secret in secrets:
        if secret and len(secret) >= 8:
            text = text.replace(secret, '***')
    return SECRET_VALUE.sub(lambda m: m.group(1) + '***', text)


def sanitize_config(value):
    if isinstance(value, dict):
        return {k: ('***' if SECRET_KEY.search(str(k)) and v not in ('', None) else sanitize_config(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_config(v) for v in value]
    if isinstance(value, str):
        return sanitize_text(value)
    return value


def _session_secrets(root: Path):
    try:
        data = json.loads((root/'debug/live/session.json').read_text(encoding='utf-8'))
        return [str(data.get('token') or '')]
    except (OSError, ValueError):
        return []


def _tail(path: Path, size=LOG_TAIL_BYTES) -> str | None:
    try:
        with path.open('rb') as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - size))
            data = stream.read(size)
    except OSError:
        return None
    text = data.decode('utf-8', errors='replace')
    return text.split('\n', 1)[-1] if len(data) == size else text  # Drop a cut first line.


def _slug(text):
    text = re.sub(r'[^\w一-鿿-]+', '', str(text))
    return text[:24] or 'report'


def system_info(version=None) -> dict:
    return {'version': version, 'python': sys.version.split()[0], 'os': platform.platform(),
            'frozen': bool(getattr(sys, 'frozen', False))}


def build_report(failure: Failure, root, version=None, now=None) -> Path:
    """Write the report folder and its ZIP under <root>/debug/reports; return the ZIP path."""
    import cv2
    root = Path(root)
    stamp = datetime.fromtimestamp(failure.time).strftime('%Y%m%d-%H%M%S')
    folder = root/'debug/reports'/f'{stamp}-{_slug(failure.task_name)}'
    (folder/'logs').mkdir(parents=True, exist_ok=True)
    secrets = _session_secrets(root)
    contents = []
    if failure.frame is not None:
        from src.runtime.frame_geometry import mask_uid
        frame = mask_uid(failure.frame.copy())
        ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if ok:
            (folder/'screenshot.jpg').write_bytes(encoded.tobytes())
            contents.append('失败时游戏画面（UID 已遮挡）')
    for source, name in LOG_SOURCES:
        text = _tail(root/source)
        if text is not None:
            (folder/'logs'/name).write_text(sanitize_text(text, secrets), encoding='utf-8')
    if any((folder/'logs').iterdir()):
        contents.append('最近的软件日志（已移除用户目录与密钥）')
    message = sanitize_text(failure.message, secrets)
    report = {'time': datetime.fromtimestamp(failure.time).isoformat(timespec='seconds'),
              'task': failure.task_name, 'task_class': failure.task_class, 'error': message,
              'task_info': sanitize_config(failure.info), 'task_config': sanitize_config(failure.config),
              'runtime': sanitize_config(failure.runtime), 'system': system_info(version)}
    (folder/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),
                                      encoding='utf-8')
    contents.append('任务设置与运行状态、软件版本与系统信息（不含账号密码）')
    (folder/'说明.md').write_text(
        f'# ok-zzz 错误报告\n\n- 时间：{report["time"]}\n- 任务：{failure.task_name}\n'
        f'- 版本：{version or "未知"}\n- 系统：{report["system"]["os"]}\n\n## 错误\n\n{message}\n\n'
        '## 包含内容\n\n' + ''.join(f'- {item}\n' for item in contents) +
        '\n不包含账号、密码、游戏账号配置和实时调试会话。\n', encoding='utf-8')
    archive = folder.with_suffix('.zip')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(folder.rglob('*')):
            if path.is_file():
                bundle.write(path, folder.name + '/' + path.relative_to(folder).as_posix())
    return archive


def issue_url(failure: Failure, repository: str, archive: Path | None = None, version=None) -> str:
    """A pre-filled 'new issue' link; the ZIP itself has to be attached by the user."""
    message = sanitize_text(failure.message)
    if len(message) > ISSUE_MESSAGE_CHARS:
        message = message[:ISSUE_MESSAGE_CHARS] + '…'
    first_line = message.splitlines()[0] if message else '运行失败'
    title = f'[错误报告] {failure.task_name}：{first_line[:60]}'
    body = (f'**任务**：{failure.task_name}\n'
            f'**时间**：{datetime.fromtimestamp(failure.time).isoformat(timespec="seconds")}\n'
            f'**版本**：{version or "未知"}\n**系统**：{platform.platform()}\n\n'
            f'**错误信息**\n```\n{message}\n```\n\n'
            '**发生前在做什么**（选填）：\n\n'
            f'**错误报告**：请把 `{archive.name if archive else "错误报告 ZIP"}` 拖到这里上传'
            '（已自动打开所在文件夹；画面已遮挡 UID，不含账号密码）。\n')
    return f'{repository.rstrip("/")}/issues/new?title={quote(title)}&body={quote(body)}'
