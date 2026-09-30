# -*- coding: utf-8 -*-
"""应用任务基类：把任务配置写回一条龙应用配置并运行。

生成器（tools/gen_app_tasks.py）产出的每个应用任务继承本类；
细则选项与一条龙配置键一致，运行前经 run_context.get_config 写回，
保证 config/{实例}/{组}/{app_id}.yml 与原版格式互通。
"""
import json

from ok import BaseTask

from onedragon.base.operation.one_dragon_finalizer import (
    AfterDoneRequest,
    execute_after_done,
)
from onedragon.utils.log_utils import log
from src.tasks.zzz_base_task import ZzzBaseTask

# 任务 UI 专用键（不写回应用配置）
UI_KEYS = ('结束后', '关机延迟秒')


class AppTaskBase(ZzzBaseTask, BaseTask):
    """单应用运行任务（app_id 由子类声明）。"""

    app_id: str = ''

    def apply_options(self):
        """把任务配置写回应用配置（JSON 文本 → list/dict）。"""
        if not self._option_keys:
            return
        ctx = self.ctx
        app_config = ctx.run_context.get_config(
            self.app_id, instance_idx=ctx.current_instance_idx)
        for key in self._option_keys:
            if key not in self.config:
                continue
            value = self.config.get(key)
            if isinstance(value, str) and self.config_type.get(key, {}).get('type') == 'text_edit':
                raw = value.strip()
                if raw and raw[0] in '[{':
                    try:
                        value = json.loads(raw)
                    except Exception as e:
                        log.warning(f'{self.app_id} 选项 {key} 不是合法 JSON，保持原值: {e}')
                        continue
            try:
                app_config.update(key, value)
            except Exception as e:
                log.warning(f'{self.app_id} 写回选项 {key} 失败: {e}')
        log.info(f'{self.app_id} 选项已写回')

    def run(self):
        ctx = self.ctx
        ctx.init_for_application()
        self.apply_options()

        run_result = ctx.run_context.run_application(
            self.app_id, instance_idx=ctx.current_instance_idx)

        after_done = str(self.config.get('结束后', '无'))
        request = AfterDoneRequest(
            close_game=after_done == '关闭游戏',
            shutdown_seconds=int(self.config.get('关机延迟秒', 60))
            if after_done == '关机' else None,
        )
        execute_after_done(ctx, run_result, request)
        self.log_info(f"{self.app_id} 运行结束: {run_result.finish_reason}", notify=True)
