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
from src.controls.application_input import application_inputs


class OneDragonDailyTask(ZzzBaseTask, BaseTask):

    use_background_application = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "🐉 一条龙日常"
        from qfluentwidgets import FluentIcon
        self.group_name = '一条龙日常'
        self.group_icon = FluentIcon.CALENDAR
        self.default_expanded = True
        self.description = '按下方编排顺序执行已勾选应用；可编辑各应用设置，当日已完成的应用自动跳过'
        self.default_config = {
            '启用应用': ['兑换码', '邮件', '每日签到', '录像店营业', '咖啡店',
                       '体力刷本', '活跃度奖励', '丽都城募', '丽都周纪 (领奖励)'],
            '结束后': '无',
            '关机延迟秒': 60,
            '执行顺序': self._all_app_names(),
        }
        self.config_type.update({
            '启用应用': {
                'type': 'daily_plan',
                'options': self._all_app_names(),
            },
            '执行顺序': {'hidden': True},
        })
        self.config_description.update({
            '启用应用': '勾选启用，拖动行调整执行顺序；点击编辑修改应用设置，也可按Ctrl+↑/↓排序',
        })

    @staticmethod
    def _all_app_names() -> list[str]:
        """默认组全部应用中文名（按 PRIORITY 排序）。"""
        from zzz_od.application.app_options_data import APP_OPTIONS
        apps = [a for a in APP_OPTIONS
                if a.get('default_group') and 'app_id' in a and a['app_id'] != 'one_dragon']
        apps.sort(key=lambda a: (a.get('priority') is None,
                                 a.get('priority') or 0, a['app_id']))
        return [a['app_name'] for a in apps]

    def _sync_group_config(self, instance_idx=None) -> None:
        """把 UI 勾选写回应用组配置（app_id↔中文名映射）。"""
        from zzz_od.application.app_options_data import APP_OPTIONS
        id2name = {a['app_id']: a['app_name'] for a in APP_OPTIONS if 'app_id' in a}
        enabled_names = set(self.config.get('启用应用') or [])
        ordered_names = list(dict.fromkeys([*(self.config.get('执行顺序') or []), *self._all_app_names()]))
        if instance_idx is None:
            instance_idx = self.ctx.current_instance_idx
        group = self.ctx.run_context.get_group_config(instance_idx=instance_idx)
        for app_id, _enabled in self.ctx.run_context.get_group_app_ids(instance_idx=instance_idx):
            name = id2name.get(app_id, app_id)
            group.set_app_enable(app_id, name in enabled_names, save=False)
        name2id = {name: app_id for app_id, name in id2name.items()}
        group.set_app_order([name2id[name] for name in ordered_names if name in name2id])
        sequence = [name for name in ordered_names if name in enabled_names]
        self.info[f'账号 {instance_idx:02d} 执行计划'] = ' → '.join(sequence)
        self.log_info(f'账号 {instance_idx:02d} 一条龙执行顺序：'+' → '.join(sequence))

    def run(self):
        ctx = self.ctx
        self.stop_battle_triggers()
        from zzz_od.application.app_options_data import APP_OPTIONS
        enabled_names = set(self.config.get('启用应用') or [])
        enabled = {app['app_id'] for app in APP_OPTIONS if app.get('app_name') in enabled_names}
        if not enabled:
            self.info['执行结果'] = '未启用任何日常应用'
            self.log_error('一条龙未启动：请先勾选要执行的日常应用', notify=True)
            raise ValueError('未启用任何日常应用')
        for task in self.get_tasks():
            if task is not self and getattr(task, 'app_id', None) in enabled:
                task.apply_options()
        from onedragon.base.config.one_dragon_config import InstanceRun
        if ctx.one_dragon_config.instance_run == InstanceRun.CURRENT.value.value:
            instances = [ctx.one_dragon_config.current_active_instance]
        else:
            instances = ctx.instance_list_in_od
        if not instances or any(instance is None for instance in instances):
            self.info['执行结果'] = '未选择运行账号'
            raise ValueError('一条龙未启动：未选择运行账号')
        for instance in instances:
            self._sync_group_config(instance.idx)
        with application_inputs(self):
            return self._run_application()

    def _run_application(self):
        ctx = self.ctx
        ctx.init_for_application()

        run_result = ctx.run_context.run_application(
            'one_dragon', instance_idx=ctx.current_instance_idx)

        from onedragon.base.operation.application.application_run_context import RunFinishReason
        result = ctx.run_context.last_application_result
        detail = getattr(result, 'status', None) or str(run_result.finish_reason)
        if run_result.finish_reason == RunFinishReason.STOPPED:
            self.info['执行结果'] = '已停止，尚未完成一条龙'
            self.log_info('一条龙已停止，尚未完成；不执行结束后操作')
            return
        self.info['执行结果'] = detail
        if run_result.finish_reason in (RunFinishReason.FAILED, RunFinishReason.NOT_STARTED):
            self.log_error(f'一条龙运行失败：{detail}', notify=True)
            raise RuntimeError(f'一条龙运行失败：{detail}')

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
        self.log_info(f'一条龙运行结束：{detail}', notify=True)
