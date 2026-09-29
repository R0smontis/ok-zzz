# -*- coding: utf-8 -*-
"""自动战斗触发任务 — ok-script 帧循环与一条龙战斗引擎的桥。

一条龙原驱动方式（auto_battle_app）：
    ctx.auto_battle_context.check_battle_state(last_screenshot, last_screenshot_time)
本任务在 ok-script TriggerTask 的帧循环中做同样的事：
引擎内部的战斗 DSL 线程、闪避检测线程与一条龙完全一致。
"""
import time

from ok import TriggerTask

from onedragon.utils.log_utils import log
from src.tasks.zzz_base_task import ZzzBaseTask


class AutoCombatTask(ZzzBaseTask, TriggerTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "⚔️ 自动战斗"
        self.description = "在战斗中自动执行连招/闪避/连携技/自动终结技（基于一条龙战斗引擎）"
        self.trigger_interval = 0.02
        self.default_config = {
            '_enabled': False,
            '战斗配置': '全配队通用',
            '战斗结束停止': False,
        }
        self.config_description = {
            '战斗配置': 'config/auto_battle 下的战斗模板名；专属配队会在匹配队伍后自动生效',
            '战斗结束停止': '识别到战斗结束画面后自动停止引擎（挂机单场时开启）',
        }
        self._engine_started = False
        self._last_config_name = None

    # ------------------------------------------------------------------ #
    # 引擎生命周期
    # ------------------------------------------------------------------ #

    def _start_engine(self, config_name: str) -> bool:
        try:
            battle_ctx = self.ctx.auto_battle_context
            if self._last_config_name != config_name or battle_ctx.auto_op is None:
                battle_ctx.init_auto_op(config_name)
                self._last_config_name = config_name
            battle_ctx.auto_ultimate_enabled = bool(self.config.get('自动终结技', True))
            if not self._engine_started:
                battle_ctx.start_auto_battle()
                self._engine_started = True
                log.info(f'自动战斗引擎已启动: {config_name}')
            return True
        except Exception as e:
            log.error(f'启动自动战斗引擎失败: {e}', exc_info=True)
            return False

    def _stop_engine(self) -> None:
        if not self._engine_started:
            return
        try:
            self.ctx.auto_battle_context.stop_auto_battle()
            log.info('自动战斗引擎已停止')
        except Exception as e:
            log.warning(f'停止自动战斗引擎异常: {e}')
        self._engine_started = False

    def enable(self):
        super().enable()
        # 勾选任务时启动引擎；失败则回退为禁用，避免静默不工作
        if not self._start_engine(str(self.config.get('战斗配置', '全配队通用'))):
            self.disable()

    def disable(self):
        self._stop_engine()
        super().disable()

    # ------------------------------------------------------------------ #
    # 帧循环
    # ------------------------------------------------------------------ #

    def should_trigger(self):
        return self.enabled

    def run(self):
        if not self._engine_started:
            if not self._start_engine(str(self.config.get('战斗配置', '全配队通用'))):
                self.disable()
                return
        frame = self.frame
        if frame is None:
            return
        screenshot_time = time.time()
        in_battle = self.ctx.auto_battle_context.check_battle_state(frame, screenshot_time)
        if (not in_battle and self._engine_started
                and self.config.get('战斗结束停止', False)
                and self.ctx.auto_battle_context.last_check_end_result is not None):
            log.info(f'战斗结束({self.ctx.auto_battle_context.last_check_end_result})，自动停止引擎')
            self._stop_engine()
