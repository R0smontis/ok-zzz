# -*- coding: utf-8 -*-
"""应用运行任务（ok-script 桥）。

把任意一条龙应用包装为 ok-script 一次性任务：用户在 UI 上选应用、
跑完自动收尾（关游戏/关机可选）。应用自身的细则选项经 AppOptionsTask
暴露（见 options_bridge）。
"""
from ok import BaseTask

from onedragon.base.operation.one_dragon_finalizer import execute_after_done
from onedragon.utils.log_utils import log
from src.tasks.zzz_base_task import ZzzBaseTask, after_done_request


class AppRunnerTask(ZzzBaseTask, BaseTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "🚀 运行指定应用"
        self.description = "选择并运行一条龙的单个应用（细节选项见同名的选项任务）"
        self.default_config = {
            '应用': 'email_app',
            '结束后': '无',       # 无 / 关闭游戏 / 关机 / 休眠 / 睡眠
            '关机延迟秒': 60,
        }
        self._app_options_cache = {}

    def _refresh_app_options(self):
        """确保默认应用在注册表内。"""
        ctx = self.ctx
        apps = ctx.run_context.get_application_name_map()
        if apps and self.config.get('应用') not in apps:
            self.config['应用'] = 'one_dragon' if 'one_dragon' in apps else sorted(apps.keys())[0]

    def run(self):
        ctx = self.ctx
        ctx.init_for_application()
        self._refresh_app_options()

        app_id = str(self.config.get('应用', 'email_app'))
        after_done = str(self.config.get('结束后', '无'))
        log.info(f'AppRunner 开始: {app_id} 结束后={after_done}')

        run_result = ctx.run_context.run_application(
            app_id, instance_idx=ctx.current_instance_idx)

        execute_after_done(ctx, run_result, after_done_request(self.config))
        self.log_info(f'{app_id} 运行结束: {run_result.finish_reason}', notify=True)


class OneDragonTask(ZzzBaseTask, BaseTask):
    """一条龙队列任务：按组配置顺序执行全部启用应用（含多实例）。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "🐉 一条龙"
        self.description = "按应用列表顺序执行日常（当日已完成的自动跳过），支持多账号实例"
        self.default_config = {
            '结束后': '无',
            '关机延迟秒': 60,
        }

    def run(self):
        ctx = self.ctx
        ctx.init_for_application()

        run_result = ctx.run_context.run_application(
            'one_dragon', instance_idx=ctx.current_instance_idx)

        execute_after_done(ctx, run_result, after_done_request(self.config))
        self.log_info(f'一条龙运行结束: {run_result.finish_reason}', notify=True)
