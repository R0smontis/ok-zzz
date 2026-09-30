# -*- coding: utf-8 -*-
"""自动战斗触发任务 — ok-script 帧循环与一条龙战斗引擎的桥。

一条龙原驱动方式（auto_battle_app）：
    ctx.auto_battle_context.check_battle_state(last_screenshot, last_screenshot_time)
本任务在 ok-script TriggerTask 的帧循环中做同样的事：
引擎内部的战斗 DSL 线程、闪避检测线程与一条龙完全一致。
"""
import os
import time

from ok import TriggerTask

from onedragon.utils.log_utils import log
from src.tasks.zzz_base_task import ZzzBaseTask


def list_battle_templates(sub_dir: str, suffix: str = '.merged.yml') -> list[str]:
    """扫描 config/<sub_dir> 下的模板名（ok-ww 式文件枚举下拉）。

    兼容 merged/普通/sample 三种后缀；同名时按 merged > sample 优先。
    """
    from onedragon.utils import os_utils
    suffixes = ('.merged.yml', '.sample.yml', '.yml')
    try:
        d = os_utils.get_path_under_work_dir('config', sub_dir)
        names = set()
        for f in os.listdir(d):
            for suf in suffixes:
                if f.endswith(suf):
                    names.add(f[:-len(suf)])
                    break
        names.discard('_od_merged')
        return sorted(names) or ['全配队通用']
    except Exception:
        return ['全配队通用']


class AutoCombatTask(ZzzBaseTask, TriggerTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "⚔️ 自动战斗"
        self.description = "在战斗中自动执行连招/闪避/连携技/自动终结技（基于一条龙战斗引擎）"
        self.trigger_interval = 0.02
        self.default_config = {
            '_enabled': False,
            '战斗配置': '全配队通用',
            '自动终结技': True,
            '战斗结束停止': False,
        }
        self.config_type = {
            '战斗配置': {'type': 'drop_down',
                       'options': list_battle_templates('auto_battle', '.merged.yml')},
        }
        self.config_description = {
            '战斗配置': 'config/auto_battle 下的战斗模板；专属配队会在匹配队伍后自动生效',
            '自动终结技': '终结技可用时自动释放',
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


class DodgeAssistantTriggerTask(ZzzBaseTask, TriggerTask):
    """闪避助手触发器：只加载 config/dodge 闪避指令，专司闪避/格挡。

    对应一条龙 DodgeAssistantApp（挂机陪玩场景），但改为 ok-script
    触发器驱动，与自动战斗触发器共用同一引擎上下文。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "🛡️ 闪避助手"
        self.description = "识别攻击预警自动闪避/格挡（手动操作陪玩用；与自动战斗二选一开启）"
        self.trigger_interval = 0.02
        self.default_config = {
            '_enabled': False,
            '闪避配置': '闪避',
            '截图间隔秒': 0.02,
            '后台模式': False,
        }
        self.config_type = {
            '闪避配置': {'type': 'drop_down',
                       'options': list_battle_templates('dodge', '.merged.yml')},
        }
        self._engine_started = False
        self._last_config_name = None

    def _start_engine(self, config_name: str) -> bool:
        try:
            battle_ctx = self.ctx.auto_battle_context
            if self._last_config_name != config_name or battle_ctx.auto_op is None:
                battle_ctx.init_auto_op(config_name, sub_dir='dodge')
                self._last_config_name = config_name
            # 应用输入模式（后台手柄/前台键鼠）
            battle_cfg = self.ctx.battle_assistant_config
            battle_cfg.background_mode = bool(self.config.get('后台模式', False))
            self.ctx.controller.init_before_context_run()
            if not self._engine_started:
                battle_ctx.start_auto_battle()
                self._engine_started = True
                log.info(f'闪避助手引擎已启动: {config_name}')
            return True
        except Exception as e:
            log.error(f'启动闪避助手引擎失败: {e}', exc_info=True)
            return False

    def _stop_engine(self) -> None:
        if not self._engine_started:
            return
        try:
            self.ctx.auto_battle_context.stop_auto_battle()
            log.info('闪避助手引擎已停止')
        except Exception as e:
            log.warning(f'停止闪避助手引擎异常: {e}')
        self._engine_started = False

    def enable(self):
        super().enable()
        if not self._start_engine(str(self.config.get('闪避配置', '闪避'))):
            self.disable()

    def disable(self):
        self._stop_engine()
        super().disable()

    def should_trigger(self):
        return self.enabled

    def run(self):
        if not self._engine_started:
            if not self._start_engine(str(self.config.get('闪避配置', '闪避'))):
                self.disable()
                return
        frame = self.frame
        if frame is None:
            return
        self.ctx.auto_battle_context.check_battle_state(frame, time.time())
