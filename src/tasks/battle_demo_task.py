# -*- coding: utf-8 -*-
"""自动战斗单场演示任务（一次性任务）。

用于实机验证 ok-script ↔ 一条龙战斗引擎链路：
启动引擎 → 等待进入战斗 → 引擎接管直到战斗结束/超时 → 停止引擎。
"""
import time

from ok import BaseTask

from onedragon.utils.log_utils import log
from src.tasks.zzz_base_task import ZzzBaseTask


class BattleDemoTask(ZzzBaseTask, BaseTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "🧪 战斗演示（单场）"
        self.visible = False
        self.debug_tool = True
        self.description = ("启动一条龙战斗引擎验证链路：请先手动进入战斗或开启引擎后手动开怪；"
                            "识别到战斗结束后自动停止。仅用于验证，日常请使用「自动战斗」触发器。")
        self.default_config = {
            '战斗配置': '全配队通用',
            '最长运行秒数': 180,
        }
        self.config_description = {
            '战斗配置': 'config/auto_battle 下的战斗模板名',
            '最长运行秒数': '超时后自动停止引擎',
        }
        self._started_at = 0.0
        self._running = False

    def run(self):
        battle_ctx = self.ctx.auto_battle_context
        config_name = str(self.config.get('战斗配置', '全配队通用'))

        if not self._running:
            battle_ctx.init_auto_op(config_name)
            battle_ctx.start_auto_battle()
            self._running = True
            self._started_at = time.time()
            log.info(f'战斗演示开始: {config_name}')

        frame = self.frame
        if frame is None:
            return
        in_battle = battle_ctx.check_battle_state(frame, time.time())

        timeout = float(self.config.get('最长运行秒数', 180))
        ended = (not in_battle) and battle_ctx.last_check_end_result is not None
        if ended:
            self.log_info(f'战斗结束: {battle_ctx.last_check_end_result}', notify=True)
        if ended or time.time() - self._started_at > timeout:
            battle_ctx.stop_auto_battle()
            self._running = False
            self.log_info('战斗演示结束，引擎已停止', notify=True)
