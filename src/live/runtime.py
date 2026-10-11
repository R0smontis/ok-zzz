"""Bridge live debugging to selected game capture and background input."""
import threading
import time

import cv2
import win32gui
from PySide6.QtCore import QObject, Signal, Slot
from ok import og

from src.live.service import LiveError


def runtime_xbox_pad(context):
    """Keep one application device across debugging leases and task resumes."""
    if context.controller is None:
        context.init_controller(activate=False)
    controller = context.controller
    if controller.xbox_controller is None:
        controller.enable_xbox()
    return controller.xbox_controller


class GuiCalls(QObject):
    request = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.request.connect(self._execute)

    @Slot(object)
    def _execute(self, job):
        with job['lock']:
            if job['cancelled']:
                return
            try:
                job['result'] = job['call']()
            except Exception as error:
                job['error'] = error
            finally:
                job['done'].set()

    def call(self, callback):
        if self.thread().isCurrentThread():
            return callback()
        job = {'call': callback, 'done': threading.Event(), 'lock': threading.Lock(), 'cancelled': False}
        self.request.emit(job)
        if not job['done'].wait(5):
            # Pending GUI work must never run later after the caller timed out.
            with job['lock']:
                if not job['done'].is_set():
                    job['cancelled'] = True
                    raise LiveError('界面没有响应，指令已取消')
        if 'error' in job:
            raise job['error']
        return job.get('result')


class GameRuntime:
    actions = {'normal_attack', 'special_attack', 'ultimate', 'dodge', 'switch_next', 'switch_prev',
               'chain_left', 'chain_right', 'move_w', 'move_a', 'move_s', 'move_d',
               'confirm', 'back', 'menu', 'dpad_up', 'dpad_down', 'dpad_left', 'dpad_right',
               'turn_left', 'turn_right'}
    actions |= {'map', 'region_list', 'focus_details', 'tab_prev', 'tab_next', 'interact', 'compendium'}
    PAD_BUTTONS = ('a', 'b', 'x', 'y', 'lb', 'rb', 'lt', 'rt', 'start', 'back', 'l_thumb', 'r_thumb')
    actions |= {'pad_' + button for button in PAD_BUTTONS}  # raw buttons for exploring new pages

    def __init__(self, app, gui):
        self.app = app
        self.gui = gui
        self.service = None
        self.lock = threading.RLock()
        self.window_input = None
        self.pad = None
        self.control_target = None
        self.mode = 'messages'
        self.keys = {}
        self.last_capture = 0
        self.input_trace = None

    def start_observing(self):
        from src.controls.user_input_trace import GameInputTrace
        self.input_trace = GameInputTrace(lambda: self.target()['hwnd'], self.service.event)
        try:
            self.input_trace.start()
        except Exception as error:
            self.service.event('user_input_trace_error', error=str(error))

    def stop_observing(self):
        if self.input_trace is not None:
            self.input_trace.stop()
            self.input_trace = None

    def target(self):
        hwnd = int(self.app._window_provider() or 0)
        try:
            if not hwnd or not win32gui.IsWindow(hwnd) or win32gui.IsIconic(hwnd):
                return {'hwnd': 0, 'geometry': None}
            rect = win32gui.GetClientRect(hwnd)
            if rect[2] <= 10 or rect[3] <= 10:
                return {'hwnd': 0, 'geometry': None}
            return {'hwnd': hwnd, 'geometry': list(rect),
                    'title': win32gui.GetWindowText(hwnd),
                    'foreground': win32gui.GetForegroundWindow() == hwnd}
        except Exception:
            return {'hwnd': 0, 'geometry': None}

    def capture(self):
        executor = og.executor
        target = self.target()
        method = getattr(executor, 'method', None)
        if not target['hwnd'] or method is None:
            return None
        # Ordinary tasks already publish frames. Avoid extra WGC requests during
        # active high-frequency combat; independently capture while F9 is paused.
        if self.service.frames:
            frame = self.service.frame()
            if time.time()-frame['captured_at'] < .4 and frame['hwnd'] == target['hwnd']:
                return None
        if getattr(getattr(method, 'hwnd_window', None), 'hwnd', 0) != target['hwnd']:
            return None
        image = method.get_frame()  # WGC/BitBlt serialize their native resources.
        if image is None or self.target()['hwnd'] != target['hwnd']:
            return None
        from src.runtime.frozen_capture import FrozenCaptureWatch, handle_frozen_capture
        handle_frozen_capture(self.__dict__.setdefault('_capture_watch', FrozenCaptureWatch()), image, method)
        if self.target()['geometry'] != target['geometry']:
            return None
        now = time.time()
        from src.diagnostics.recorder import recorder
        recorder.observe(image, captured_at=now)
        return image, target['hwnd'], now, target['geometry']

    def snapshot(self):
        executor = og.executor
        context = getattr(self.app, '_context', None)
        current = getattr(executor, 'current_task', None)
        from src.runtime.inference import runtime_status
        result = {'executor_paused': bool(executor.paused), 'window': self.target(),
            'capture_ready': bool(executor.can_capture()),
            'interaction_class': type(executor.interaction).__name__,
            'capture_backend': type(executor.method).__name__, 'recognition': runtime_status(),
            'capture_name': executor.method.get_name() if executor.method is not None else None,
            'capture_health': getattr(executor.method, '_zzz_capture_error', ''),
            'tasks': [{'class': type(t).__name__, 'name': t.name, 'enabled': bool(t.enabled),
                       'running': bool(t.running), 'paused': bool(t.paused),
                       'info': {str(k): str(v)[:2000] for k, v in list(t.info.copy().items())}}
                      for t in executor.get_all_tasks()],
            'current_task': type(current).__name__ if current else None}
        if context is not None:
            run = context.run_context
            app = run.current_application
            result['application'] = run.current_app_id
            result['node'] = getattr(getattr(app, '_current_node', None), 'cn', None)
            battle = context.__dict__.get('_auto_battle_context')
            if battle is not None:
                result['recognition_queue'] = battle.recognition_checks.snapshot()
                op = battle.auto_op
                team = battle.agent_context.team_info
                result['battle'] = {'attack_hud_visible': battle.last_check_in_battle,
                    'operator_running': bool(op and op.is_running),
                    'template': getattr(op, 'module_name', None),
                    'expression': getattr(getattr(op, 'current_execution_info', None), 'expr_display', None),
                    'team': [{'agent': getattr(i.agent, 'agent_name', None), 'energy': i.energy,
                              'special_ready': i.special_ready, 'ultimate_ready': i.ultimate_ready}
                             for i in list(team.agent_list)]}
        return result

    def _stop_automation(self):
        if self.service.stop_event.is_set():
            raise LiveError('监控已停止')
        from onedragon.base.controller.input_guard import debug_control_owned
        debug_control_owned.set()
        executor = og.executor
        executor.pause()
        for task in executor.get_all_tasks():
            if task.enabled and not getattr(task, 'recording_controls', False):
                task.disable()
        context = getattr(self.app, '_context', None)
        if context is not None:
            context.run_context.stop_running()
            if context.controller is not None:
                context.controller.cancel_inputs()
        return self.app.context

    def acquire(self, mode):
        target = self.target()
        if not target['hwnd']:
            raise LiveError('请选择有效的游戏窗口')
        try:
            context = self.gui.call(self._stop_automation)
            from onedragon.base.controller.pc_game_window import PcGameWindow
            from src.controls.window_input import WindowMessageInput
            window = PcGameWindow()
            def bound_hwnd():
                owned_target = self.control_target
                return (target['hwnd'] if owned_target is not None
                        and self.target()['hwnd'] == target['hwnd'] else 0)
            window.window_provider = bound_hwnd
            backend = WindowMessageInput(window)
            pad = None
            if mode == 'gamepad':
                # Reuse the application's device. Recreating a ViGEm device on
                # each lease leaves multiple XInput slots until cyclic bindings
                # are collected; the game can keep listening to an older slot.
                pad = self.gui.call(lambda: runtime_xbox_pad(context))
                if pad.pad is None:
                    raise LiveError('虚拟手柄不可用，请安装ViGEmBus或选择窗口消息')
            self.app._sync_game_hotkeys(context.game_config)
            with self.lock:
                self.control_target = target
                self.window_input, self.pad, self.mode = backend, pad, mode
                self.keys = context.game_config.get_action_keys('xbox' if pad else 'keyboard')
                window.init_win()
            return {'mode': mode, 'hwnd': target['hwnd'], 'automatic_tasks_stopped': True}
        except Exception:
            self.release()
            raise

    def release(self):
        from onedragon.base.controller.input_guard import debug_control_owned
        try:
            with self.lock:
                self.control_target = None
                try:
                    if self.window_input is not None:
                        self.window_input.reset()
                    if self.pad is not None:
                        self.pad.reset()
                finally:
                    self.window_input = self.pad = None
        finally:
            debug_control_owned.clear()

    def control_target_valid(self):
        with self.lock:
            target = self.control_target
        current = self.target()
        return bool(target and current['hwnd'] == target['hwnd']
                    and current['geometry'] == target['geometry'])

    def input(self, command, cancel):
        from onedragon.base.geometry.point import Point
        c = command
        duration = c.get('duration', .08)
        with self.lock:
            if cancel.is_set() or not self.control_target_valid():
                raise LiveError('操作已取消或窗口改变')
            backend, pad = self.window_input, self.pad
            op = c['op']
            if op == 'action':
                action = c['action']
                extras = ({'confirm': 'xbox_a', 'back': 'xbox_b', 'menu': 'xbox_start',
                           'map': 'xbox_back', 'region_list': 'xbox_l_thumb', 'focus_details': 'xbox_r_thumb',
                           'tab_prev': 'xbox_lb', 'tab_next': 'xbox_rb',
                           'compendium': ['xbox_lt','xbox_a'],
                           'turn_left': 'xbox_rs_left', 'turn_right': 'xbox_rs_right',
                           **{f'dpad_{d}': f'xbox_dpad_{d}' for d in ('up', 'down', 'left', 'right')},
                           **{f'pad_{b}': f'xbox_{b}' for b in self.PAD_BUTTONS}}
                          if pad else {'confirm': 'enter', 'back': 'esc', 'menu': 'esc',
                           **{f'dpad_{d}': d for d in ('up', 'down', 'left', 'right')}})
                key = extras.get(action) or self.keys.get(action)
                if key is None:
                    raise LiveError('该动作需要手柄后台模式')
                if pad:
                    backend.activate(self.control_target['hwnd'])
                    for index, part in enumerate(key if isinstance(key,list) else [key]):
                        if index:
                            cancel.wait(pad.combo_press_time)
                        pad.press(part)
            else:
                key = c.get('key')
        if op == 'action' and pad:
            try:
                deadline = time.monotonic()+duration
                while not cancel.wait(min(.025, max(0, deadline-time.monotonic()))):
                    if time.monotonic() >= deadline or not self.control_target_valid():
                        break
                return not cancel.is_set() and self.control_target_valid()
            finally:
                with self.lock:
                    for part in reversed(key if isinstance(key,list) else [key]):
                        pad.release(part)
        if cancel.is_set() or not self.control_target_valid():
            return False
        if op in ('key', 'action'):
            return backend.press(key, duration)
        if op == 'click':
            return backend.click(Point(c['x'], c['y']), duration, button=c.get('button', 'left'))
        if op == 'drag':
            return backend.drag(Point(c['x'], c['y']), Point(c['end_x'], c['end_y']), duration)
        if op == 'scroll':
            return backend.scroll(int(c['amount']), Point(c['x'], c['y']))

    def analyze(self, image, command):
        from src.runtime.frame_geometry import normalize_bgr
        from src.diagnostics.recorder import private_frame
        from zzz_od.auto_battle.battle_presence import (find_enemy_health_bar,
            find_enemy_direction_arrow, has_chain_timer)
        context = self.gui.call(lambda: self.app.context)
        context.auto_battle_context.init_screen_area()
        screen = normalize_bgr(private_frame(image))
        # Use the same HUD gate as the running assistant, not an independent heuristic.
        hud = context.auto_battle_context.is_normal_attack_btn_available(screen)
        result = {'attack_hud_visible': bool(hud), 'enemy_detection_skipped': not hud,
                  'enemy_panel': find_enemy_health_bar(screen) if hud else None,
                  'enemy_arrow': find_enemy_direction_arrow(screen) if hud else None,
                  'chain_timer_visible': bool(has_chain_timer(screen))}
        from onedragon.base.screen import screen_utils
        result['normal_world'] = screen_utils.is_target_screen(context, screen, screen_name='大世界-普通')
        result['capture_ready'] = bool(og.executor.can_capture())
        result['interaction_class'] = type(og.device_manager.interaction).__name__
        result['controller_frame_geometry'] = getattr(context.controller, 'frame_geometry', None)
        if command.get('ocr', True):
            x, y, w, h = (int(v) for v in command.get('roi', [0, 0, 1920, 1080]))
            result['ocr'] = [{'text': r.data, 'confidence': r.confidence,
                              'rect': [r.x+x, r.y+y, r.w, r.h]}
                             for r in context.ocr.ocr(screen[y:y+h, x:x+w])]
        return result

    def task(self, name, action):
        def invoke():
            executor = og.executor
            found = [t for t in executor.get_all_tasks() if type(t).__name__ == name]
            if len(found) != 1:
                raise LiveError('任务class不存在或不唯一')
            task = found[0]
            if action == 'start':
                if getattr(task, 'debug_tool', False):
                    raise LiveError('调试工具请从调试页面启动')
                task.enable()
                executor.start()
            elif action == 'pause':
                task.pause()
            elif action == 'resume':
                task.unpause()
                executor.start()
            elif action == 'stop':
                task.disable()
            return {'task': name, 'action': action}
        return self.gui.call(invoke)
