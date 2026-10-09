"""Local, bounded diagnostics. Observe existing game frames; never send input."""
from datetime import datetime, timedelta, timezone
from functools import wraps
import json
import math
from pathlib import Path
import queue
import threading
import time
import traceback
import uuid
import zipfile

import cv2
import numpy as np


TAIPEI = timezone(timedelta(hours=8))
MAX_IMAGES = 300
MAX_VIDEO_BYTES = 1024 * 1024 * 1024
LOG_TAIL_BYTES = 1024 * 1024
VIDEO_FPS = (5, 10, 15, 24, 30, 60)
VIDEO_RESOLUTIONS = {'480P': (854, 480), '720P': (1280, 720), '1080P': (1920, 1080)}


def timestamp(wall_time):
    return datetime.fromtimestamp(wall_time, TAIPEI).isoformat(timespec='milliseconds')


def private_frame(frame):
    """Mask UID on a copy; preserve the frame used by the game recognizers."""
    copy = frame.copy()
    h, w = copy.shape[:2]
    copy[int(h * 1059 / 1080):h, int(w * 1814 / 1920):w] = 0
    return copy


def visual_evidence(frame):
    from zzz_od.auto_battle.battle_presence import has_enemy_health_bar, has_target_reticle
    from src.runtime.frame_geometry import normalize_bgr
    normalized = normalize_bgr(frame)
    if normalized is None:
        return {'target_reticle': False, 'enemy_health_bar': False}
    return {'target_reticle': has_target_reticle(normalized),
            'enemy_health_bar': has_enemy_health_bar(normalized)}


def runtime_snapshot(executor):
    """Read cached state only: no device discovery, recognition, or input."""
    from ok import og
    result = {'executor_paused': bool(getattr(executor, 'paused', False))}
    from src.runtime.inference import runtime_status
    result['recognition'] = runtime_status()
    manager = getattr(executor, 'device_manager', None)
    window = getattr(manager, 'hwnd_window', None)
    method = getattr(executor, 'method', None)
    result['window'] = {key: getattr(window, key, None) for key in (
        'hwnd', 'visible', 'exists', 'x', 'y', 'width', 'height')}
    result['capture_backend'] = type(method).__name__ if method is not None else None
    result['frame_age'] = round(max(0, time.time() - getattr(executor, '_last_frame_time', time.time())), 3)
    tasks = executor.get_all_tasks()
    result['tasks'] = [{'class': type(task).__name__, 'name': task.name,
                        'enabled': task.enabled, 'running': task.running,
                        'state': str(task.info.get('助手状态', '')),
                        'evidence': str(task.info.get('触发原因', '')),
                        'burst_remaining': round(max(0, getattr(task, '_input_until', 0) - time.monotonic()), 3)}
                       for task in tasks if task.enabled or task.running]
    context = getattr(getattr(og, 'my_app', None), '_context', None)
    if context is not None:
        result['frame_geometry'] = getattr(getattr(context, 'controller', None), 'frame_geometry', None)
        run = context.run_context
        result['application'] = run.current_app_id
        app = run.current_application
        result['node'] = getattr(getattr(app, '_current_node', None), 'cn', None)
        controller = context.controller
        battle = context.auto_battle_context
        op = battle.auto_op
        team = getattr(getattr(battle, 'agent_context', None), 'team_info', None)
        result['battle'] = {
            'attack_hud_visible': battle.last_check_in_battle,
            'operator_running': bool(op is not None and op.is_running),
            'template': getattr(op, 'module_name', None),
            'execution_guard_installed': getattr(op, 'execution_allowed', None) is not None,
            'controller_guard_installed': getattr(controller, 'battle_input_guard', None) is not None,
            'background_mode': getattr(controller, 'background_mode', None),
            'expression': getattr(getattr(op, 'current_execution_info', None), 'expr_display', None),
            'team': [{'agent': getattr(info.agent, 'agent_name', None),
                      'template': info.matched_template_id, 'energy': info.energy,
                      'special_ready': info.special_ready, 'ultimate_ready': info.ultimate_ready}
                     for info in list(getattr(team, 'agent_list', []))],
            'team_check_all_agents': getattr(team, 'should_check_all_agents', None),
            'team_rejected_checks': getattr(team, 'check_agent_diff_times', None),
            'team_last_update': getattr(team, 'agent_update_time', None),
        }
    return result


class DiagnosticRecorder:
    def __init__(self):
        self._lock = threading.RLock()
        self._session = None
        self._thread = None

    @property
    def active(self):
        session = self._session
        return session is not None and not session['stop'].is_set() and session['paused_at'] is None

    @property
    def paused(self):
        session = self._session
        return session is not None and not session['stop'].is_set() and session['paused_at'] is not None

    @staticmethod
    def _elapsed(s, now=None):
        now = time.monotonic() if now is None else now
        end = s['stopped_at'] if s['stopped_at'] is not None else now
        pause = 0 if s['paused_at'] is None else max(0, end-s['paused_at'])
        return max(0, end-s['start']-s['paused_total']-pause)

    @property
    def status(self):
        with self._lock:
            if self._session is None:
                return {'state': '未开始'}
            s = self._session
            result = {key: s[key] for key in ('state', 'folder', 'archive', 'images', 'video_frames',
                                             'events', 'user_inputs', 'input_error', 'dropped', 'error', 'reason')}
            result.update(elapsed=round(self._elapsed(s), 3), duration=s['duration'], paused=self.paused)
            result.update(fps=s['fps'], resolution=s['resolution'], video_size=list(s['video_size']))
            return result

    def start(self, root, *, duration=0, image_interval=1, mode='截图和视频', fps=10,
              resolution='720P', snapshot_provider=None, on_finished=None, input_hwnd_provider=None,
              input_enabled_provider=None):
        if (mode not in ('截图', '视频', '截图和视频') or
                isinstance(duration, bool) or not math.isfinite(float(duration)) or
                not (float(duration) == 0 or float(duration) >= 5) or
                not 0.2 <= float(image_interval) <= 5 or
                isinstance(fps, bool) or not isinstance(fps, int) or fps not in VIDEO_FPS or
                resolution not in VIDEO_RESOLUTIONS):
            raise ValueError('诊断参数超出范围')
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError('上次诊断仍在录制或保存，请稍后再启动')
            root = Path(root).resolve()
            now = time.time()
            name = datetime.fromtimestamp(now, TAIPEI).strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6]
            folder = root / 'debug' / 'diagnostics' / name
            (folder / 'frames').mkdir(parents=True)
            s = {'root': root, 'folder': str(folder), 'archive': None, 'state': '录制中',
                 'start': time.monotonic(), 'wall_start': now, 'duration': float(duration),
                 'interval': float(image_interval), 'mode': mode, 'fps': fps,
                 'resolution': resolution, 'video_size': VIDEO_RESOLUTIONS[resolution],
                 'snapshot': snapshot_provider, 'queue': queue.Queue(maxsize=4096),
                 'on_finished': on_finished,
                 'input_hwnd_provider': input_hwnd_provider, 'input_trace': None,
                 'input_enabled_provider': input_enabled_provider,
                 'user_inputs': 0, 'input_error': None,
                 'paused_at': None, 'paused_total': 0.0, 'stopped_at': None,
                 'stop': threading.Event(), 'next_capture': 0, 'next_image': 0,
                 'pending_frames': 0, 'images': 0, 'video_frames': 0, 'videos': [], 'events': 0,
                 'dropped': 0, 'error': None, 'reason': None, 'throttle': {}}
            self._session = s
            self._thread = threading.Thread(target=self._write, args=(s,),
                                            name='diagnostic-writer', daemon=True)
            self._thread.start()
            return str(folder)

    def record(self, kind, *, throttle=None, **details):
        if not self.active:
            return
        with self._lock:
            s = self._session
            now = time.monotonic()
            if s['stop'].is_set() or s['paused_at'] is not None:
                return
            if throttle is not None:
                signature = json.dumps(details, ensure_ascii=False, default=str, sort_keys=True)
                previous = s['throttle'].get(throttle)
                if previous and previous[0] == signature and now - previous[1] < 1:
                    return
                s['throttle'][throttle] = (signature, now)
            item = {'type': kind, 'time': timestamp(time.time()),
                    'elapsed': round(self._elapsed(s, now), 4), 'wall_elapsed': round(now-s['start'], 4),
                    'thread': threading.current_thread().name,
                    **details}
            try:
                s['queue'].put_nowait(('event', item))
            except queue.Full:
                s['dropped'] += 1

    def observe(self, frame, *, captured_at=None, source='ok-script'):
        if not self.active or frame is None or frame.ndim != 3 or frame.shape[2] != 3:
            return
        with self._lock:
            s = self._session
            now = time.monotonic()
            if s['stop'].is_set() or s['paused_at'] is not None or now < s['next_capture']:
                return
            step = 1 / s['fps'] if s['mode'] != '截图' else s['interval']
            s['next_capture'] = now + step
            if s['pending_frames'] >= 3:
                s['dropped'] += 1
                return
            captured_at = time.time() if captured_at is None else captured_at
            try:
                snapshot = s['snapshot']() if s['snapshot'] else {}
            except Exception as exc:
                snapshot = {'snapshot_error': str(exc)}
            item = {'time': timestamp(captured_at), 'captured_at': captured_at,
                    'elapsed': round(self._elapsed(s, now), 4), 'wall_elapsed': round(now-s['start'], 4),
                    'source': source,
                    'shape': list(frame.shape), 'runtime': snapshot}
            try:
                s['queue'].put_nowait(('frame', (private_frame(frame), item, now)))
                s['pending_frames'] += 1
            except queue.Full:
                s['dropped'] += 1

    def _control_event(self, s, kind, now, **details):
        item = {'type': kind, 'time': timestamp(time.time()),
                'elapsed': round(self._elapsed(s, now), 4), 'wall_elapsed': round(now-s['start'], 4),
                'thread': threading.current_thread().name, **details}
        try:
            s['queue'].put_nowait(('control', item))
        except queue.Full:
            s['dropped'] += 1

    def pause(self):
        with self._lock:
            s = self._session
            if s is None or s['stop'].is_set() or s['paused_at'] is not None:
                return False
            now = time.monotonic()
            s['paused_at'] = now
            s['state'] = '已暂停'
            self._control_event(s, 'recording_pause', now)
            return True

    def resume(self):
        with self._lock:
            s = self._session
            if s is None or s['stop'].is_set() or s['paused_at'] is None:
                return False
            now = time.monotonic()
            paused_for = now-s['paused_at']
            s['paused_total'] += paused_for
            s['paused_at'] = None
            s['next_capture'] = 0
            s['next_image'] = now
            s['state'] = '录制中'
            self._control_event(s, 'recording_resume', now, paused_for=round(paused_for, 4))
            return True

    def _stop_session(self, s, reason, now=None):
        s['stopped_at'] = time.monotonic() if now is None else now
        s['reason'] = reason
        s['state'] = '保存中'
        s['stop'].set()

    def stop(self, reason='手动停止', *, wait=False):
        with self._lock:
            if self._session is not None and not self._session['stop'].is_set():
                self._stop_session(self._session, reason)
            thread = self._thread
        if wait and thread is not None:
            thread.join(timeout=10)

    @staticmethod
    def _logs(s, suffix):
        folder = Path(s['folder']) / 'logs'
        folder.mkdir(exist_ok=True)
        for source, name in (('logs/ok-script.log', 'ok-script'), ('.log/log.txt', 'game-engine')):
            try:
                with (s['root'] / source).open('rb') as stream:
                    stream.seek(0, 2)
                    stream.seek(max(0, stream.tell() - LOG_TAIL_BYTES))
                    (folder / f'{name}-{suffix}.log').write_bytes(stream.read(LOG_TAIL_BYTES))
            except OSError:
                pass

    @staticmethod
    def _video_writer(folder, fps, segment=0, size=(1280, 720)):
        stem = 'video' if segment == 0 else f'video-{segment+1:04d}'
        for filename, codec in ((f'{stem}.mp4', 'mp4v'), (f'{stem}.avi', 'MJPG')):
            path = folder / filename
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*codec), fps, size)
            if writer.isOpened():
                return writer, path
            writer.release()
        raise RuntimeError('视频编码器不可用，继续保存截图和日志')

    def _write(self, s):
        folder = Path(s['folder'])
        writer = None
        video_path = None
        latest = None
        latest_info = None
        next_video = 0.0
        segment_start_frame = 0
        previous_small = None
        latest_canvas = None
        width, height = s['video_size']
        footer = max(14, round(height/36))

        def game_canvas(image):
            canvas = np.zeros((height, width, 3), np.uint8)
            scale = min(width/image.shape[1], (height-footer)/image.shape[0])
            scaled_w, scaled_h = round(image.shape[1]*scale), round(image.shape[0]*scale)
            x, y = (width-scaled_w)//2, (height-footer-scaled_h)//2
            canvas[y:y+scaled_h, x:x+scaled_w] = cv2.resize(image, (scaled_w, scaled_h))
            return canvas
        try:
            self._logs(s, 'start')
            if s['input_hwnd_provider'] is not None:
                try:
                    from src.controls.user_input_trace import GameInputTrace
                    s['input_trace'] = GameInputTrace(s['input_hwnd_provider'], self.record,
                        enabled_provider=lambda: self.active and (
                            s['input_enabled_provider'] is None or s['input_enabled_provider']()))
                    s['input_trace'].start()
                except Exception as exc:
                    s['input_error'] = str(exc)
                    self.record('user_input_capture_error', error=str(exc))
            if s['mode'] != '截图':
                try:
                    writer, video_path = self._video_writer(folder, s['fps'], size=s['video_size'])
                    s['videos'].append(video_path.name)
                except Exception as exc:
                    s['error'] = str(exc)
                    s['mode'] = '截图'
            with (folder / 'events.jsonl').open('w', encoding='utf-8', buffering=1) as events, \
                    (folder / 'user-input.jsonl').open('w', encoding='utf-8', buffering=1) as user_inputs, \
                    (folder / 'frames.jsonl').open('w', encoding='utf-8', buffering=1) as frames, \
                    (folder / 'video-timeline.jsonl').open('w', encoding='utf-8', buffering=1) as timeline:
                while True:
                    now = time.monotonic()
                    with self._lock:
                        if s['duration'] and self._elapsed(s, now) >= s['duration'] and not s['stop'].is_set():
                            self._stop_session(s, '达到录制时长', now)
                    try:
                        # Wake for the next output frame even when source captures
                        # are sparse. A fixed 20 ms wait previously capped 60 FPS.
                        timeout = min(.02, max(0, next_video-self._elapsed(s))) if (
                            writer is not None and self.active) else .02
                        kind, item = s['queue'].get(timeout=timeout)
                    except queue.Empty:
                        kind = None
                    if kind in ('event', 'control'):
                        line = json.dumps(item, ensure_ascii=False, default=str) + '\n'
                        events.write(line)
                        if item['type'] == 'user_input':
                            user_inputs.write(line)
                            s['user_inputs'] += 1
                        s['events'] += 1
                        if kind == 'control':
                            latest = None
                            latest_info = None
                            previous_small = None
                            latest_canvas = None
                            next_video = item['elapsed']
                    elif kind == 'frame':
                        latest, latest_info, observed_at = item
                        latest_canvas = None
                        with self._lock:
                            s['pending_frames'] -= 1
                        latest_info['sample'] = s['images']
                        if observed_at >= s['next_image'] and s['images'] < MAX_IMAGES:
                            s['next_image'] = observed_at + s['interval']
                            evidence = visual_evidence(latest)
                            small = cv2.resize(latest, (192, 108))
                            latest_info['visual_evidence'] = evidence
                            latest_info['brightness'] = round(float(latest.mean()), 2)
                            latest_info['frame_difference'] = None if previous_small is None else round(
                                float(cv2.absdiff(small, previous_small).mean()), 3)
                            previous_small = small
                            if s['mode'] != '视频':
                                filename = f'frames/{s["images"]:04d}-{latest_info["elapsed"]:.2f}s.jpg'
                                success, encoded = cv2.imencode('.jpg', latest, [cv2.IMWRITE_JPEG_QUALITY, 90])
                                if not success:
                                    raise RuntimeError('截图编码失败')
                                (folder / filename).write_bytes(encoded.tobytes())
                                latest_info['image'] = filename
                            frames.write(json.dumps(latest_info, ensure_ascii=False, default=str) + '\n')
                            s['images'] += 1
                    with self._lock:
                        elapsed = self._elapsed(s)
                        write_video = writer is not None and elapsed >= next_video and self.active
                    if write_video:
                        if s['video_frames'] > segment_start_frame and video_path.stat().st_size > MAX_VIDEO_BYTES:
                            writer.release()
                            writer, video_path = self._video_writer(folder, s['fps'], len(s['videos']),
                                                                   size=s['video_size'])
                            s['videos'].append(video_path.name)
                            segment_start_frame = s['video_frames']
                            self.record('video_segment', video=video_path.name)
                        # Playback follows active recording time; recording pauses are excluded.
                        age = None if latest_info is None else max(0, time.time() - latest_info['captured_at'])
                        if latest is not None and age < 2:
                            # Reserve a footer outside the game image; never cover boss bars/dialogue.
                            if latest_canvas is None:
                                latest_canvas = game_canvas(latest)
                            canvas = latest_canvas.copy()
                        else:
                            canvas = np.zeros((height, width, 3), np.uint8)
                            cv2.putText(canvas, 'NO FRESH GAME FRAME', (round(width*.025), round(height*.125)),
                                        cv2.FONT_HERSHEY_SIMPLEX, height/720, (0, 180, 255), 2)
                        cv2.putText(canvas, f't={elapsed:.2f}s  capture_age={age}  frame={s["images"]}',
                                    (12, height-max(4, round(height/120))), cv2.FONT_HERSHEY_SIMPLEX,
                                    max(.35, .4*height/720), (255, 255, 255), 1)
                        writer.write(canvas)
                        timeline.write(json.dumps({'frame': s['video_frames'], 'video': video_path.name,
                            'elapsed': round(elapsed, 4), 'wall_elapsed': round(time.monotonic()-s['start'], 4),
                            'capture_age': age,
                            'captured_at': None if latest_info is None else latest_info['time']}) + '\n')
                        s['video_frames'] += 1
                        next_video += 1 / s['fps']
                    if s['stop'].is_set() and s['queue'].empty() and s['pending_frames'] == 0:
                        break
        except Exception as exc:
            s['error'] = str(exc)
            with self._lock:
                self._stop_session(s, '录制异常')
        finally:
            if s['input_trace'] is not None:
                try:
                    s['input_trace'].stop()
                except Exception as exc:
                    s['input_error'] = str(exc)
            if writer is not None:
                writer.release()
            s['state'] = '保存中'
            try:
                self._logs(s, 'end')
                wall_duration = s['stopped_at']-s['start']
                metadata = {'schema': 2, 'started_at': timestamp(s['wall_start']),
                            'duration': round(self._elapsed(s), 3), 'wall_duration': round(wall_duration, 3),
                            'paused_duration': round(wall_duration-self._elapsed(s), 3),
                            'requested_duration': s['duration'], 'fps': s['fps'],
                            'resolution': s['resolution'], 'video_size': list(s['video_size']),
                            'image_interval': s['interval'], 'mode': s['mode'],
                            'video': s['videos'][0] if s['videos'] else None, 'videos': s['videos'],
                            'samples': s['images'], 'video_frames': s['video_frames'],
                            'events': s['events'], 'dropped': s['dropped'],
                            'user_input_configured': s['input_hwnd_provider'] is not None,
                            'user_input_events': s['user_inputs'], 'input_error': s['input_error'],
                            'reason': s['reason'], 'error': s['error']}
                (folder / 'session.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
                (folder / '说明.md').write_text(
                    '# okzzz 画面与日志诊断\n\n'
                    '截图、视频、events.jsonl、frames.jsonl 使用同一 elapsed 秒时间线（从开始录制算起，不含录制暂停时间）。\n'
                    'wall_elapsed 为包含暂停的实际经过时间，time/captured_at 保留真实时间；暂停与恢复另有事件标记。\n'
                    'video-timeline.jsonl 对应视频每一帧，并注明所属视频分段。暂停不保存画面和输入事件，也不计时。\n'
                    '黑色画面 NO FRESH GAME FRAME 表示游戏截图中断；F9 暂停游戏任务与录制暂停按钮相互独立。\n'
                    'frames.jsonl 包含窗口、任务、输入保护及辅助敌人特征；辅助颜色特征可能误判。\n'
                    'events.jsonl 包含战斗启动来源、识别结果、条件匹配、节点和输入调用；输入调用不保证游戏接受。\n'
                    'user-input.jsonl 为游戏前台时的用户键鼠日志；events.jsonl 的 input_call 为程序调用，\n'
                    'observed_injected_input 为系统标记的合成输入（可能来自本程序或其它自动化）。\n'
                    'logs 包含软件和战斗引擎日志的首尾片段。仅记录游戏帧；UID 已遮挡，不记录音频。\n'
                    '默认不限时，手动停止后保存；大视频自动分段，原始文件保留在本目录，同名ZIP为完整诊断包。\n\n'
                    f'视频规格：{s["resolution"]}（{width}×{height}），{s["fps"]}帧/秒。\n'
                    '输出采用所选帧率；素材来自任务截图，采集较慢时复用最新画面，帧龄见capture_age。\n'
                    f'停止原因：{s["reason"]}。错误：{s["error"] or "无"}。丢弃记录：{s["dropped"]}。\n', encoding='utf-8')
                archive = folder.with_suffix('.zip')
                with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as bundle:
                    for path in sorted(folder.rglob('*')):
                        if path.is_file():
                            bundle.write(path, folder.name + '/' + path.relative_to(folder).as_posix())
                s['archive'] = str(archive)
                s['state'] = '已保存'
            except Exception as exc:
                s['error'] = str(exc)
                s['state'] = '保存失败'
            s['stop'].set()
            if s['on_finished'] is not None:
                try:
                    s['on_finished']()
                except Exception:
                    pass


recorder = DiagnosticRecorder()


def record_event(kind, **details):
    """Diagnostics must never change task execution on failure."""
    try:
        from src.runtime.logging_bridge import log_runtime_event
        log_runtime_event(kind, details)
        recorder.record(kind, **details)
        from ok import og
        live = getattr(getattr(og, 'executor', None), '_live_debug', None)
        if live is not None and live.started:
            # Remains available outside a diagnostic recording session.
            live.event(kind, **{k: v for k, v in details.items() if k != 'throttle'})
    except Exception:
        pass


def record_battle_start(entry, battle):
    if recorder.active:
        record_event('battle_start', entry=entry,
            enemy_gate_installed=getattr(battle.auto_op, 'execution_allowed', None) is not None,
            source=[{'file': f.filename, 'line': f.lineno, 'function': f.name}
                    for f in traceback.extract_stack(limit=7)[:-1]])


def install_frame_observer(executor):
    if getattr(executor.next_frame, '_diagnostic_observer', False) is True:
        return
    original = executor.next_frame

    @wraps(original)
    def next_frame(*args, **kwargs):
        frame = original(*args, **kwargs)
        try:
            recorder.observe(frame, captured_at=getattr(executor, '_last_frame_time', None))
            live = getattr(executor, '_live_debug', None)
            if live is not None and live.started:
                target = live.adapter.target()
                live.publish(frame, target['hwnd'], getattr(executor, '_last_frame_time', None),
                             target.get('geometry'))
        except Exception as exc:
            record_event('capture_observer_error', throttle='capture_observer_error', error=str(exc))
        return frame

    next_frame._diagnostic_observer = True
    executor.next_frame = next_frame
