"""Frame-driven dialogue skipping: each invocation sends at most one click."""
import math
import threading
import time

from ok import TriggerTask

from src.tasks.zzz_base_task import ZzzBaseTask
from zzz_od.application.commission_assistant.dialogue_detector import DialogueDetector
from src.diagnostics import record_event


class AutoDialogueTriggerTask(ZzzBaseTask, TriggerTask):
    MAX_RESULT_AGE = 0.5

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '💬 自动跳过对话'
        self.description = '实时识别剧情、对话及选项；无对话时不点击，可与战斗助手同时启用'
        self.trigger_interval = 0.1
        self.default_config.update({
            '_enabled': False, '剧情模式': '跳过剧情', '对话选项': '最后一个',
            '识别间隔秒': 0.1, '对话点击间隔秒': 0.5, '后台时暂停': True,
        })
        self.config_type.update({
            '剧情模式': {'type': 'drop_down', 'options': ['跳过剧情', '自动点击', '等待剧情自动播放']},
            '对话选项': {'type': 'drop_down', 'options': ['第一个', '最后一个']},
        })
        self.config_description.update({
            '剧情模式': '优先跳过剧情、逐句推进，或开启游戏内自动播放',
            '对话选项': '出现明确对话选项时选择的位置',
            '识别间隔秒': '持续检测的间隔，范围 0.05～1 秒',
            '对话点击间隔秒': '两次已识别点击之间的最短间隔，范围 0.1～3 秒；不会定时盲点',
            '后台时暂停': '开启：切走时等待；关闭：只向游戏窗口发点击消息，不切前台、不移动鼠标，部分游戏界面可能忽略后台消息',
        })
        self._lock = threading.RLock()
        self._generation = 0
        self._ready = False
        self._detector = None
        self._detector_ctx = None
        self._last_check = None
        self._last_click = None
        self._menu_until = 0.0

    def validate_config(self, key, value):
        error = super().validate_config(key, value)
        if error:
            return error
        bounds = {'识别间隔秒': (0.05, 1), '对话点击间隔秒': (0.1, 3)}
        if key in bounds:
            low, high = bounds[key]
            try:
                number = float(value)
            except (TypeError, ValueError):
                return f'{key}必须是数字'
            if not math.isfinite(number) or not low <= number <= high:
                return f'{key}应在 {low}～{high} 之间'

    def _reset(self):
        self._generation += 1
        self._ready = False
        self._last_check = None
        self._last_click = None
        self._menu_until = 0.0
        self.info['助手状态'] = '等待对话'

    def enable(self):
        with self._lock:
            self._reset()
            self.enable_passive_trigger()

    def disable(self):
        with self._lock:
            self._reset()
            super().disable()

    def on_create(self):
        super().on_create()
        from ok.core.events import communicate
        communicate.executor_paused.connect(self._on_executor_paused)

    def _on_executor_paused(self, paused):
        if paused:
            with self._lock:
                self._reset()

    def on_destroy(self):
        from ok.core.events import communicate
        communicate.executor_paused.disconnect(self._on_executor_paused)
        self.disable()
        super().on_destroy()

    def should_trigger(self):
        for key in ('识别间隔秒', '对话点击间隔秒'):
            error = self.validate_config(key, self.config[key])
            if error:
                self.log_error(error, notify=True)
                self.disable()
                return False
        self.trigger_interval = float(self.config['识别间隔秒'])
        return self.enabled and super().should_trigger()

    def _settings(self):
        return tuple(self.config[key] for key in (
            '剧情模式', '对话选项', '对话点击间隔秒', '后台时暂停'))

    def _blocked(self, ctx):
        if not ctx.controller.game_win.is_win_valid:
            self._ready = False
            self._menu_until = 0.0
            self.info['助手状态'] = '等待游戏窗口'
            return True
        if any(task.running for task in self.get_tasks()
               if task is not self and not isinstance(task, TriggerTask)):
            self.info['助手状态'] = '等待独立任务结束'
            return True
        if self.config['后台时暂停'] and not ctx.controller.game_win.is_win_active:
            self.info['助手状态'] = '等待游戏前台'
            return True
        return False

    def run(self):
        if not self.enabled:
            return
        ctx = self.ctx
        if ctx is not self._detector_ctx:
            ctx.init()
            if ctx.controller is None:
                ctx.init_controller(activate=False)
            self._detector = DialogueDetector(ctx)
            self._detector_ctx = ctx
            self._ready = False
        if not self._ready:
            if not ctx.controller.init_game_win():
                self.info['助手状态'] = '等待游戏窗口'
                return
            self._ready = True
        if self._blocked(ctx):
            self._menu_until = 0.0
            return
        now = time.monotonic()
        if self._last_check is not None and now-self._last_check < float(self.config['识别间隔秒']):
            return
        self._last_check = now
        controller = ctx.controller
        hwnd = controller.game_win.get_hwnd()
        captured_at = time.monotonic()
        frame = ctx.controller.normalize_frame(self.frame)
        geometry = getattr(controller, 'frame_geometry', None)
        if geometry:
            self.info['窗口分辨率'] = '×'.join(map(str, geometry['source']))
        if frame is None:
            self._menu_until = 0.0
            self.info['助手状态'] = '等待有效画面'
            return
        with self._lock:
            generation = self._generation
            settings = self._settings()
        action = self._detector.detect(frame, mode=settings[0], option=settings[1],
                                       menu_opened=captured_at < self._menu_until)
        record_event('dialogue_detection', action=None if action is None else action.kind,
                     text=None if action is None else action.text, hwnd=hwnd)
        with self._lock:
            if (not self.enabled or generation != self._generation or ctx is not self.ctx
                    or controller is not ctx.controller
                    or hwnd != controller.game_win.get_hwnd()
                    or settings != self._settings() or self._blocked(ctx)):
                self._menu_until = 0.0
                return
            now = time.monotonic()
            if now-captured_at > self.MAX_RESULT_AGE:
                self.info['助手状态'] = '识别结果过期，等待新画面'
                return
            if action is None:
                self.info['助手状态'] = '等待对话'
                return
            self.info['助手状态'] = f'检测到：{action.text}'
            if self._last_click is not None and now-self._last_click < float(settings[2]):
                return
            if controller.click_dialogue_event(action.point, expected_hwnd=hwnd,
                                               allow_background=not settings[3]):
                self._last_click = time.monotonic()
                self._menu_until = self._last_click + 2 if action.kind == 'menu' else 0.0
                self.info['助手状态'] = action.text
                self.log_info(f'对话助手：已执行{action.text}')
            else:
                self.info['助手状态'] = '点击未发送，等待有效窗口或游戏前台'
