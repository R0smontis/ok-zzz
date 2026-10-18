"""Authenticated loopback monitor with one bounded, cancellable command worker.

The HTTP threads never touch a controller, a Qt widget or executor.next_frame.
Frames and commands carry the selected window identity; stale work is rejected.
"""
from collections import OrderedDict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import logging
import math
import os
from pathlib import Path
import queue
import re
import secrets
import threading
import sys
import traceback
import time
from urllib.parse import urlsplit, parse_qs
import uuid

import cv2

from onedragon.base.operation import dry_run
from src.runtime.frame_geometry import bgra_view


class LiveError(ValueError):
    pass


LEASE_SECONDS = 60
COMMANDS = ('acquire', 'release', 'heartbeat', 'analyze', 'click', 'drag', 'scroll',
            'key', 'action', 'task_start', 'task_pause', 'task_resume', 'task_stop')


def number(value, minimum, maximum, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise LiveError(f'{label}必须是有限数字')
    if not minimum <= value <= maximum:
        raise LiveError(f'{label}范围为{minimum}～{maximum}')
    return value


class LiveLog(logging.Handler):
    def __init__(self, service):
        super().__init__(logging.INFO)
        self.service = service

    def emit(self, record):
        self.service.event('log', level=record.levelname, message=record.getMessage()[:3000])


class LiveDebugService:
    def __init__(self, adapter, folder, interval=.25):
        self.adapter = adapter
        self.folder = Path(folder)
        self.interval = interval
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.command_cancel = threading.Event()
        self.commands = queue.Queue(maxsize=8)
        self.jobs = OrderedDict()
        self.frames = deque(maxlen=12)
        self.events = deque(maxlen=600)
        self.sequence = 0
        self.frame_sequence = 0
        self.encoded_frames = OrderedDict()
        self.runtime = {}
        self.capture_error = ''
        self.owned = False
        self.lease_until = 0
        self.generation = 0
        self.started = False
        self.server = None
        self.token = secrets.token_urlsafe(32)
        self.session_id = uuid.uuid4().hex
        self.log_handler = LiveLog(self)
        self.threads = []

    def start(self):
        if self.started:
            return
        self.folder.mkdir(parents=True, exist_ok=True)
        self.stop_event.clear()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), self._handler())
        self.server.daemon_threads = True
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        discovery = {'protocol': 1, 'url': self.url, 'token': self.token, 'pid': os.getpid(),
                     'session_id': self.session_id, 'started_at': time.time()}
        temporary = self.folder / 'session.json.tmp'
        temporary.write_text(json.dumps(discovery), encoding='utf-8')
        temporary.replace(self.folder / 'session.json')
        logging.getLogger('ok').addHandler(self.log_handler)
        self.started = True
        start_observing = getattr(self.adapter, 'start_observing', None)
        if callable(start_observing):
            start_observing()
        for name, target in (('LiveHTTP', self.server.serve_forever),
                             ('LiveMonitor', self._monitor), ('LiveCommands', self._worker)):
            thread = threading.Thread(target=target, name=name, daemon=True)
            self.threads.append(thread)
            thread.start()
        self.event('service_started', address=self.url)
        logging.getLogger('ok').info('实时调试已启动：%s（仅本机）', self.url)

    def stop(self):
        if not self.started:
            return
        self.stop_event.set()
        self.release('停止监控')
        stop_observing = getattr(self.adapter, 'stop_observing', None)
        if callable(stop_observing):
            stop_observing()
        self.server.shutdown()
        self.server.server_close()
        for thread in self.threads:
            if thread is not threading.current_thread():
                thread.join(timeout=1)
        self.threads.clear()
        logging.getLogger('ok').removeHandler(self.log_handler)
        path = self.folder / 'session.json'
        try:
            if json.loads(path.read_text(encoding='utf-8')).get('session_id') == self.session_id:
                path.unlink()
        except (OSError, ValueError):
            pass
        self.started = False

    def event(self, kind, **details):
        with self.lock:
            self.sequence += 1
            # Recognition events may include numpy scalars or engine objects.
            safe = json.loads(json.dumps(details, default=str, ensure_ascii=False))
            self.events.append({'seq': self.sequence, 'time': time.time(), 'kind': kind, **safe})

    def event_list(self, after=0):
        with self.lock:
            return {'events': [dict(item) for item in self.events if item['seq'] > after],
                    'latest_seq': self.sequence, 'oldest_seq': self.events[0]['seq'] if self.events else 0}

    def publish(self, frame, hwnd, captured_at=None, geometry=None):
        if frame is None or not hwnd or frame.size == 0:
            return
        captured_at = time.time() if captured_at is None else captured_at
        hwnd = int(hwnd)
        if not self._accepts_frame(hwnd, captured_at):
            return
        # Resize without the service lock: event() shares it on dodge/battle threads.
        source = bgra_view(frame)
        display = cv2.resize(frame if source is None else source, (1920, 1080), interpolation=
            cv2.INTER_AREA if frame.shape[1] > 1920 else cv2.INTER_CUBIC)
        if source is not None:
            display = cv2.cvtColor(display, cv2.COLOR_BGRA2BGR)
        with self.lock:
            # Another publisher may have appended while this frame was resized.
            if not self._accepts_frame(hwnd, captured_at):
                return
            self.frame_sequence += 1
            self.frames.append({'id': self.frame_sequence, 'hwnd': hwnd,
                'captured_at': captured_at, 'source_size': [frame.shape[1], frame.shape[0]],
                'geometry': geometry, 'image': display})

    def _accepts_frame(self, hwnd, captured_at):
        with self.lock:
            if self.frames and captured_at <= self.frames[-1]['captured_at']:
                return False
            # Debug preview needs 10 FPS; recognition keeps its own rate.
            return not (self.frames and self.frames[-1]['hwnd'] == hwnd
                        and captured_at - self.frames[-1]['captured_at'] < .1)

    def frame(self, frame_id=None):
        with self.lock:
            item = next((f for f in reversed(self.frames)
                         if frame_id is None or f['id'] == frame_id), None)
            if item is None:
                raise LiveError('尚无游戏画面，请先选择游戏窗口，或重新获取截图')
            return dict(item)

    @staticmethod
    def frame_metadata(item):
        return {k: v for k, v in item.items() if k != 'image'} | {
            'age_seconds': round(max(0, time.time()-item['captured_at']), 3),
            'coordinate_size': [1920, 1080]}

    def status(self):
        with self.lock:
            return {'protocol': 1, 'session_id': self.session_id, 'monitoring': self.started,
                'control': self.owned, 'lease_seconds': round(max(0, self.lease_until-time.monotonic()), 1),
                'capture_error': self.capture_error, 'runtime': self.runtime,
                'frame': self.frame_metadata(self.frames[-1]) if self.frames else None,
                'latest_event_seq': self.sequence, 'pending_commands': self.commands.qsize(),
                'dry_run': {'stop_before': sorted(dry_run.stop_before()), 'hits': dry_run.hits()},
                'commands': list(COMMANDS)}

    def thread_stacks(self):
        """Read-only stack positions; omit frame locals and command payloads."""
        frames = sys._current_frames()
        return {'captured_at': time.time(), 'threads': [
            {'name': thread.name, 'daemon': thread.daemon, 'native_id': thread.native_id,
             'stack': traceback.format_list(traceback.extract_stack(frames[thread.ident])[-32:])}
            for thread in threading.enumerate() if thread.ident in frames]}

    def screenshot(self, frame_id=None, preview=False, jpeg=False):
        item = self.frame(frame_id)
        if item['hwnd'] != self.adapter.target()['hwnd']:
            raise LiveError('窗口已改变，请等待新截图')
        key = (item['id'], preview, jpeg)
        with self.lock:
            cached = self.encoded_frames.get(key)
            if cached is not None:
                return cached, item['id']
        from src.diagnostics.recorder import private_frame
        frame = private_frame(item['image'])  # publish already owns a 1920x1080 frame.
        if preview:
            frame = cv2.resize(frame, (960, 540))
        ok, encoded = cv2.imencode('.jpg' if preview or jpeg else '.png', frame,
                                  [cv2.IMWRITE_JPEG_QUALITY, 85] if preview or jpeg
                                  else [cv2.IMWRITE_PNG_COMPRESSION, 1])
        if not ok:
            raise LiveError('截图编码失败')
        data = encoded.tobytes()
        with self.lock:
            self.encoded_frames[key] = data
            while len(self.encoded_frames) > 8:
                self.encoded_frames.popitem(last=False)
        return data, item['id']

    def _monitor(self):
        while not self.stop_event.is_set():
            try:
                snapshot = self.adapter.snapshot()
                with self.lock:
                    self.runtime = {**snapshot, 'observed_at': time.time()}
                target = self.adapter.target()
                if not target.get('hwnd'):
                    with self.lock:
                        self.frames.clear()
                    raise LiveError('请选择有效的游戏窗口')
                captured = self.adapter.capture()
                if captured is not None:
                    self.publish(*captured)
                    with self.lock:
                        self.capture_error = ''
                elif not self.frames or self.frame()['hwnd'] != target['hwnd']:
                    raise LiveError('游戏截图暂不可用')
                elif time.time()-self.frame()['captured_at'] > 2:
                    raise LiveError('游戏截图已停滞，操作将拒绝过期画面')
            except Exception as error:
                with self.lock:
                    self.capture_error = str(error)
            with self.lock:
                expired = self.owned and time.monotonic() > self.lease_until
            if expired or (self.owned and not self.adapter.control_target_valid()):
                self.release('连接超时或窗口改变')
            self.stop_event.wait(self.interval)

    def release(self, reason='释放控制'):
        # Always invalidate queued operations, even when acquire is in progress.
        with self.lock:
            self.generation += 1
            self.command_cancel.set()
            was_owned = self.owned
            self.owned = False
            self.lease_until = 0
        try:
            self.adapter.release()
        except Exception as error:
            self.event('release_error', error=str(error))
            logging.getLogger('ok').error('实时调试释放输入失败：%s', error)
        if was_owned:
            self.event('control_released', reason=reason)
            logging.getLogger('ok').info('实时调试已释放控制：%s', reason)

    def submit(self, command):
        if not isinstance(command, dict) or not isinstance(command.get('op'), str):
            raise LiveError('指令必须包含op')
        if not self.started or self.stop_event.is_set():
            raise LiveError('实时监控已停止')
        # Reject invalid input before it can affect ownership or enter the queue.
        self._validate(command)
        with self.lock:
            key = command.get('request_id', uuid.uuid4().hex)
            if not isinstance(key, str) or not 1 <= len(key) <= 80:
                raise LiveError('request_id无效')
            if key in self.jobs:
                if self.jobs[key]['command'] != command:
                    raise LiveError('request_id已用于另一条指令')
                return self.job(key)
            job = {'id': key, 'state': 'queued', 'command': dict(command),
                   'submitted_at': time.time(), 'generation': self.generation}
            self.jobs[key] = job
            try:
                self.commands.put_nowait(key)
            except queue.Full:
                self.jobs.pop(key)
                raise LiveError('操作队列已满')
            # Never evict jobs still running or waiting.
            while len(self.jobs) > 100:
                oldest = next((k for k, v in self.jobs.items()
                               if v['state'] in ('done', 'error', 'cancelled')), None)
                if oldest is None:
                    break
                self.jobs.pop(oldest)
            return self.job(key)

    def job(self, key):
        with self.lock:
            if key not in self.jobs:
                raise LiveError('未找到指令')
            return {k: v for k, v in self.jobs[key].items() if k not in ('command', 'generation')}

    def cancel(self, key):
        with self.lock:
            job = self.jobs.get(key)
            if job is None:
                raise LiveError('未找到指令')
            if job['state'] == 'queued':
                job['state'] = 'cancelled'
            elif job['state'] == 'running':
                self.release('取消正在执行的指令')
            return self.job(key)

    def _validate(self, c):
        op = c['op']
        if op not in COMMANDS:
            raise LiveError('不支持的指令')
        if op in ('click', 'drag', 'scroll', 'key', 'action'):
            number(c.get('hwnd'), 1, 2**64, 'hwnd')
            number(c.get('frame_id'), 1, 2**53, 'frame_id')
        if op in ('click', 'drag', 'scroll'):
            number(c.get('x'), 0, 1919, 'x')
            number(c.get('y'), 0, 1079, 'y')
        if op == 'drag':
            number(c.get('end_x'), 0, 1919, 'end_x')
            number(c.get('end_y'), 0, 1079, 'end_y')
        if op in ('click', 'drag', 'key', 'action'):
            number(c.get('duration', .08), .01, 2, 'duration')
        if op == 'click' and c.get('button', 'left') not in ('left', 'right', 'middle'):
            raise LiveError('不支持的鼠标按钮')
        if op == 'scroll':
            number(c.get('amount'), -10, 10, 'amount')
        if op == 'key':
            from src.controls.hotkey_settings import validate_hotkey
            if not validate_hotkey('key', c.get('key'))[0]:
                raise LiveError('按键无效')
        if op == 'action' and c.get('action') not in self.adapter.actions:
            raise LiveError('不支持的游戏动作')
        if op == 'acquire' and c.get('mode', 'gamepad') not in ('messages', 'gamepad'):
            raise LiveError('操作方式必须是messages或gamepad')
        if op.startswith('task_') and not isinstance(c.get('task'), str):
            raise LiveError('请指定任务class')
        if 'app' in c and (op != 'task_start' or not isinstance(c['app'], str)
                           or not re.fullmatch(r'[a-z][a-z0-9_]{1,40}', c['app'])):
            raise LiveError('app应为task_start的应用ID')
        if 'stop_before' in c:
            nodes = c['stop_before']
            if (op != 'task_start' or not isinstance(nodes, list) or len(nodes) > 20
                    or not all(isinstance(n, str) and 0 < len(n) <= 40 for n in nodes)):
                raise LiveError('stop_before应为task_start的节点名称列表')
        if op == 'analyze' and 'roi' in c:
            if not isinstance(c['roi'], list) or len(c['roi']) != 4:
                raise LiveError('roi应为[x,y,width,height]')
            x, y, w, h = c['roi']
            number(x, 0, 1919, 'roi.x'); number(y, 0, 1079, 'roi.y')
            number(w, 1, 1920-x, 'roi.width'); number(h, 1, 1080-y, 'roi.height')

    def _fresh_frame(self, c):
        if not self.owned:
            raise LiveError('请先接管控制')
        item = self.frame(c['frame_id'])
        target = self.adapter.target()
        if (time.time()-item['captured_at'] > 3 or item['hwnd'] != c['hwnd']
                or item['hwnd'] != target['hwnd'] or not self.adapter.control_target_valid()
                or item['geometry'] != target.get('geometry')):
            raise LiveError('画面过期、窗口或分辨率已改变，请重新截图')
        return item

    def _execute(self, c, generation):
        op = c['op']
        if op == 'release':
            self.release()
            return {'released': True}
        if op == 'acquire':
            if self.owned:
                raise LiveError('已经接管，请先释放后再切换方式')
            self.command_cancel.clear()
            result = self.adapter.acquire(c.get('mode', 'gamepad'))
            with self.lock:
                if self.generation != generation or self.stop_event.is_set():
                    self.adapter.release()
                    raise LiveError('接管已取消')
                self.owned = True
                self.lease_until = time.monotonic()+LEASE_SECONDS
            logging.getLogger('ok').info('实时调试接管控制，已停止自动任务；方式：%s', c.get('mode', 'gamepad'))
            return result
        if op == 'heartbeat':
            with self.lock:
                if not self.owned:
                    raise LiveError('未接管控制')
                self.lease_until = time.monotonic()+LEASE_SECONDS
            return {'lease_seconds': LEASE_SECONDS}
        if op == 'analyze':
            item = self.frame(c.get('frame_id'))
            if time.time()-item['captured_at'] > 3 or item['hwnd'] != self.adapter.target()['hwnd']:
                raise LiveError('画面过期，请等待新截图')
            result = self.adapter.analyze(item['image'], c)
            return {'frame': self.frame_metadata(item), **result}
        if op.startswith('task_'):
            if self.owned:
                self.release('操作自动任务')
            if op == 'task_start':
                dry_run.set_stop_before(c.get('stop_before') or ())
            if c.get('app'):
                return self.adapter.task(c['task'], op[5:], app=c['app'])
            return self.adapter.task(c['task'], op[5:])
        self._fresh_frame(c)
        with self.lock:
            self.lease_until = time.monotonic()+LEASE_SECONDS
        result = self.adapter.input(c, self.command_cancel)
        return {'delivered': result is not False, 'game_accepted': '需查看后续画面确认',
                'coordinate_size': [1920, 1080]}

    def _worker(self):
        while not self.stop_event.is_set():
            try:
                key = self.commands.get(timeout=.1)
            except queue.Empty:
                continue
            with self.lock:
                job = self.jobs[key]
                if job['state'] == 'cancelled':
                    continue
                if time.time()-job['submitted_at'] > 5 or job['generation'] != self.generation:
                    job.update(state='cancelled', error='指令已过期或控制状态已改变')
                    continue
                job['state'] = 'running'
            try:
                result = self._execute(job['command'], job['generation'])
                with self.lock:
                    job.update(state='done', result=result, finished_at=time.time())
            except Exception as error:
                with self.lock:
                    job.update(state='error', error=str(error), finished_at=time.time())
            self.event('command_result', job=self.job(key), op=job['command']['op'])
            if job['command']['op'] != 'heartbeat':
                logging.getLogger('ok').info('实时调试指令：%s → %s%s', job['command']['op'],
                    job['state'], '：'+job.get('error', '') if job['state'] == 'error' else '')

    def _handler(self):
        service = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def setup(self):
                super().setup()
                self.connection.settimeout(3)

            def reply(self, code, value, mime='application/json; charset=utf-8', frame_id=None):
                data = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode('utf-8')
                self.send_response(code)
                self.send_header('Content-Type', mime)
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                if frame_id is not None:
                    self.send_header('X-Frame-Id', str(frame_id))
                self.end_headers()
                self.wfile.write(data)

            def authorized(self):
                auth = self.headers.get('Authorization', '')
                host = self.headers.get('Host', '')
                if (self.headers.get('Origin') or self.headers.get('Sec-Fetch-Site') in ('cross-site', 'same-site')
                        or host != f'127.0.0.1:{service.server.server_port}'
                        or not hmac.compare_digest(auth, 'Bearer '+service.token)):
                    self.reply(403, {'error': '仅接受本机已认证调试客户端'})
                    return False
                return True

            def do_GET(self):
                if not self.authorized():
                    return
                try:
                    url = urlsplit(self.path)
                    query = parse_qs(url.query)
                    if url.path == '/status':
                        self.reply(200, service.status())
                    elif url.path == '/threads':
                        self.reply(200, service.thread_stacks())
                    elif url.path == '/events':
                        self.reply(200, service.event_list(int(query.get('after', ['0'])[0])))
                    elif url.path.startswith('/jobs/'):
                        self.reply(200, service.job(url.path.split('/')[-1]))
                    elif url.path in ('/frame.png', '/frame.jpg', '/preview.jpg'):
                        frame_id = int(query['id'][0]) if 'id' in query else None
                        data, frame_id = service.screenshot(frame_id, url.path == '/preview.jpg',
                                                            url.path == '/frame.jpg')
                        self.reply(200, data, 'image/jpeg' if url.path.endswith('jpg') else 'image/png', frame_id)
                    else:
                        self.reply(404, {'error': '接口不存在'})
                except ValueError as error:  # 含 LiveError
                    self.reply(409, {'error': str(error)})
                except Exception as error:
                    self.reply(500, {'error': str(error)})

            def do_POST(self):
                if not self.authorized():
                    return
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 1 <= length <= 8192 or self.headers.get('Content-Type') != 'application/json':
                        raise LiveError('仅支持不超过8192字节的JSON请求')
                    body = json.loads(self.rfile.read(length))
                    if self.path == '/commands':
                        self.reply(202, service.submit(body))
                    elif self.path == '/release':
                        service.release('紧急释放')
                        self.reply(200, {'released': True})
                    elif self.path.startswith('/cancel/'):
                        self.reply(200, service.cancel(self.path.split('/')[-1]))
                    else:
                        self.reply(404, {'error': '接口不存在'})
                except (ValueError, TypeError) as error:  # 含 LiveError
                    self.reply(400, {'error': str(error)})
                except Exception as error:
                    self.reply(500, {'error': str(error)})

        return Handler
