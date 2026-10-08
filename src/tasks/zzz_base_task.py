# -*- coding: utf-8 -*-
"""ok-zzz 任务基类。"""
from ok import BaseTask, TriggerTask, og

from onedragon.utils.log_utils import log


class ZzzBaseTask(BaseTask):
    """提供 ZzzContext 访问与游戏窗口激活等公共能力。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config_type['结束后'] = {
            'type': 'drop_down', 'options': ['无', '关闭游戏', '关机'],
            'sub_configs': {'关机': ['关机延迟秒']},
        }
        self.config_description.update({
            '结束后': '仅任务成功完成后执行；失败或手动停止时不执行',
            '关机延迟秒': '选择关机时生效，单位为秒',
        })

    def validate_config(self, key, value):
        if key == '关机延迟秒' and (
                not isinstance(value, int) or isinstance(value, bool) or value < 0):
            return '关机延迟秒必须是非负整数'

    def enable(self):
        from src.application_input import task_input_mode
        if getattr(self, 'use_background_application', False) and task_input_mode() != '跟随交互方式':
            from ok.core.events import communicate
            if not self._enabled:
                self.ensure_capture()
                self._enabled = True
                self.info_clear()
                self.executor.enqueue_onetime_task(self)
            communicate.task.emit(self)
            return
        super().enable()

    def enable_passive_trigger(self):
        """Resident detectors do not invoke the framework's focus-stealing on_run."""
        from ok.core.events import communicate
        if not self._enabled:
            self.ensure_capture()
            self._enabled = True
            self.info_clear()
            self.executor.enqueue_onetime_task(self)
        self.config['_enabled'] = True
        communicate.task.emit(self)

    def stop_battle_triggers(self):
        """独立应用接管输入前停用常驻助手，避免两套逻辑同时操作游戏。"""
        from src.tasks.auto_combat_task import BattleTriggerTask
        for task in self.get_tasks():
            if isinstance(task, BattleTriggerTask) and task is not self and task.enabled:
                task.disable()

    def _sync_application_state(self, *, stopped=False):
        if not self.running or isinstance(self, TriggerTask):
            return
        run_context = self.ctx.run_context
        if stopped:
            run_context.stop_running()
        elif not run_context.is_context_stop and run_context.is_context_pause != self.paused:
            run_context.switch_context_pause_and_run()
        if stopped or self.paused:
            cancel = getattr(self.ctx.controller, 'cancel_inputs', None)
            if cancel is not None:
                cancel()

    def pause(self):
        super().pause()
        self._sync_application_state()

    def unpause(self):
        super().unpause()
        self._sync_application_state()

    def disable(self):
        self._sync_application_state(stopped=True)
        super().disable()

    @property
    def ctx(self):
        """ZzzContext（惰性创建，首次访问时完成 ok-script 设备桥接）。"""
        return og.my_app.context

    def activate_game_window(self):
        """把游戏窗口带到前台（委托给当前 interaction，如可用）。"""
        device_manager = getattr(og.executor, 'device_manager', None)
        interaction = getattr(device_manager, 'interaction', None)
        if interaction is None:
            return
        for method_name in ('try_activate', 'activate'):
            method = getattr(interaction, method_name, None)
            if callable(method):
                try:
                    method()
                    return
                except Exception as e:
                    log.warning(f'激活游戏窗口失败({method_name}): {e}')
