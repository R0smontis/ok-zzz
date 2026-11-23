"""Resident bridge to the OneDragon story policy and the shared input adapter."""
import math
import threading
import time

from ok import TriggerTask

from onedragon.base.controller.input_guard import execution_input_allowed
from src.diagnostics.recorder import record_event
from src.navigation.dialogue import send_story_action
from src.tasks.auto_combat_task import AutoCombatTask
from src.tasks.zzz_base_task import ZzzBaseTask
from zzz_od.application.commission_assistant.commission_assistant_config import StoryMode
from zzz_od.application.commission_assistant.story_dialogue import StoryDialogue


class AutoDialogueTriggerTask(ZzzBaseTask, TriggerTask):
    MAX_RESULT_AGE = 0.5

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '💬 自动跳过对话'
        self.description = '剧情跳过与自动对话'
        self.trigger_interval = 0.1
        self.default_config.update({
            '_enabled': False, '剧情模式': StoryMode.SKIP.value.value, '对话选项': '最后一个',
            '识别间隔秒': 0.1, '对话点击间隔秒': 0.5,
        })
        self.config_type.update({
            '剧情模式': {'type': 'drop_down', 'options': [mode.value.value for mode in StoryMode]},
            '对话选项': {'type': 'drop_down', 'options': ['第一个', '最后一个']},
        })
        self.config_description.update({
            '对话选项': '选项位置',
            '识别间隔秒': '识别间隔（0.05～1 秒）',
            '对话点击间隔秒': '对话点击间隔（0.1～3 秒）',
        })
        self._lock = threading.RLock()
        self._generation = 0
        self._ready = False
        self._story = None
        self._story_ctx = None
        self._story_settings = None

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

    def _migrate_config(self):
        if self.config.get('剧情模式') == '跳过剧情 + 自动点击':
            self.config['剧情模式'] = StoryMode.SKIP.value.value

    def _reset(self):
        self._generation += 1
        self._ready = False
        # Drop the old policy rather than mutating one an in-flight OCR call still owns.
        self._story = None
        self._story_ctx = None
        self._story_settings = None
        self.info['助手状态'] = '等待对话'

    def enable(self):
        with self._lock:
            self._migrate_config()
            self._reset()
            self.enable_passive_trigger()

    def disable(self):
        # Invalidate the in-flight action first: run() holds _lock while it activates and clicks,
        # and its input_allowed() must already see the stop before disable() gets the lock.
        self._generation += 1
        self._enabled = False
        with self._lock:
            self._reset()
            super().disable()

    def on_create(self):
        super().on_create()
        self._migrate_config()
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
        return self.enabled and not self._combat_blocked() and super().should_trigger()

    def _settings(self):
        return tuple(self.config[key] for key in ('剧情模式', '对话选项', '对话点击间隔秒'))

    def _combat_blocked(self):
        if not any(isinstance(task, AutoCombatTask) and task.combat_active for task in self.get_tasks()):
            return False
        with self._lock:
            if self._story is not None:
                self._reset()
            self.info['助手状态'] = '战斗中，暂停剧情检测'
        return True

    def _blocked(self, ctx):
        if getattr(self.executor, 'paused', False) or self.paused:
            self.info['助手状态'] = '已暂停'
            return True
        if self._combat_blocked():
            return True
        if not ctx.controller.game_win.is_win_valid:
            self._ready = False
            self.info['助手状态'] = '等待游戏窗口'
            return True
        if any(task.running for task in self.get_tasks()
               if task is not self and not isinstance(task, TriggerTask)):
            self.info['助手状态'] = '等待独立任务结束'
            return True
        return False

    def run(self):
        if not self.enabled or self._combat_blocked():
            return
        ctx = self.ctx
        if ctx is not self._story_ctx:
            ctx.init()
            if ctx.controller is None:
                ctx.init_controller(activate=False, sync_input=False)
        with self._lock:
            if not self.enabled:
                return
            if ctx is not self._story_ctx:
                self._story = StoryDialogue(ctx)
                self._story_ctx = ctx
                self._ready = False
            story = self._story
            if not self._ready:
                if not ctx.controller.init_game_win():
                    self.info['助手状态'] = '等待游戏窗口'
                    return
                self._ready = True
            if self._blocked(ctx):
                story.reset()
                return
            controller = ctx.controller
            hwnd = controller.game_win.get_hwnd()
            generation = self._generation
            settings = self._settings()
            if settings != self._story_settings:
                story.reset()
                self._story_settings = settings
        captured_at = time.monotonic()
        frame = controller.normalize_frame(self.frame)
        geometry = getattr(controller, 'frame_geometry', None)
        if geometry:
            self.info['窗口分辨率'] = '×'.join(map(str, geometry['source']))
        if frame is None:
            story.reset()
            self.info['助手状态'] = '等待有效画面'
            return
        action = story.detect(frame, mode=settings[0], option=settings[1],
                              click_interval=float(settings[2]))
        record_event('dialogue_detection', action=None if action is None else action.kind,
                     text=None if action is None else action.text, hwnd=hwnd)

        def input_allowed():
            if (not self.enabled or generation != self._generation or ctx is not self.ctx
                    or controller is not ctx.controller or story is not self._story
                    or hwnd != controller.game_win.get_hwnd()
                    or settings != self._settings() or self._blocked(ctx)
                    or not execution_input_allowed()):
                return False
            if time.monotonic() - captured_at > self.MAX_RESULT_AGE:
                self.info['助手状态'] = '识别结果过期，等待新画面'
                return False
            return True

        with self._lock:
            if not input_allowed():
                story.reset()
                return
            if action is None:
                self.info['助手状态'] = story.status
                return
            completed = send_story_action(ctx, frame, action, expected_hwnd=hwnd,
                                          input_allowed=input_allowed)
            story.feedback(action, completed)
            if completed:
                self.info['助手状态'] = action.text
                self.log_info(f'对话助手：{action.text}')
            elif input_allowed():
                self.info['助手状态'] = f'等待执行：{action.text}'
