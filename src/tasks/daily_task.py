# -*- coding: utf-8 -*-
"""一条龙日常任务（ok-ww DailyTask 式组织）。

单任务承载全部日常：从 UI 勾选要跑的应用（按一条龙默认优先级顺序
执行），写回应用组配置后交给一条龙队列执行——当日已完成的应用自动
跳过，支持多账号实例循环（instance_run 配置）。

与原版差异：应用启用状态从"组配置文件编辑"变为任务下拉多选，
底层仍是同一份 config/{实例}/one_dragon/_group.yml，互通。
"""
from onedragon.utils.log_utils import log
from src.tasks.zzz_base_task import ZzzBaseTask
from ok import BaseTask


class OneDragonDailyTask(ZzzBaseTask, BaseTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "🐉 一条龙日常"
        self.description = ("按优先级顺序执行勾选的日常应用（当日已完成的自动跳过）；"
                            "多账号在 设置-一条龙配置 里选择实例范围")
        self.default_config = {
            '启用应用': ['兑换码', '邮件', '每日签到', '录像店营业', '咖啡店',
                       '体力刷本', '活跃度奖励', '丽都城募', '丽都周纪 (领奖励)'],
            '结束后': '无',
            '关机延迟秒': 60,
        }
        self.config_type = {
            '启用应用': {
                'type': 'multi_selection',
                'options': self._all_app_names(),
            },
        }
        self.config_description = {
            '启用应用': '按一条龙默认优先级顺序执行；应用当日成功后自动跳过',
        }

    @staticmethod
    def _all_app_names() -> list[str]:
        """默认组全部应用中文名（按 PRIORITY 排序）。"""
        from zzz_od.application.app_options_data import APP_OPTIONS
        apps = [a for a in APP_OPTIONS
                if a.get('default_group') and 'app_id' in a and a['app_id'] != 'one_dragon']
        apps.sort(key=lambda a: (a.get('priority') is None,
                                 a.get('priority') or 0, a['app_id']))
        return [a['app_name'] for a in apps]

    def _sync_group_config(self) -> None:
        """把 UI 勾选写回应用组配置（app_id↔中文名映射）。"""
        from zzz_od.application.app_options_data import APP_OPTIONS
        name2id = {a['app_name']: a['app_id'] for a in APP_OPTIONS if 'app_id' in a}
        enabled_names = set(self.config.get('启用应用') or [])
        group = self.ctx.run_context.get_group_config()
        for app_id, _enabled in self.ctx.run_context.get_group_app_ids():
            name = name2id.get(app_id, app_id)
            group.set_app_enable(app_id, name in enabled_names)
        log.info(f'一条龙应用勾选已写回组配置：{len(enabled_names)} 个启用')

    def run(self):
        ctx = self.ctx
        ctx.init_for_application()
        self._sync_group_config()

        run_result = ctx.run_context.run_application(
            'one_dragon', instance_idx=ctx.current_instance_idx)

        from onedragon.base.operation.one_dragon_finalizer import (
            AfterDoneRequest,
            execute_after_done,
        )
        after_done = str(self.config.get('结束后', '无'))
        request = AfterDoneRequest(
            close_game=after_done == '关闭游戏',
            shutdown_seconds=int(self.config.get('关机延迟秒', 60))
            if after_done == '关机' else None,
        )
        execute_after_done(ctx, run_result, request)
        self.log_info(f'一条龙运行结束: {run_result.finish_reason}', notify=True)
