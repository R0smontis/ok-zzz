# -*- coding: utf-8 -*-
"""应用任务基类：把任务配置写回一条龙应用配置并运行。

生成器（tools/gen_app_tasks.py）产出的每个应用任务继承本类；
细则选项与一条龙配置键一致，运行前经 run_context.get_config 写回，
保证 config/{实例}/{组}/{app_id}.yml 与原版格式互通。
"""
import json
import copy

from ok import BaseTask

from onedragon.base.operation.one_dragon_finalizer import execute_after_done
from src.tasks.zzz_base_task import ZzzBaseTask, after_done_request
from src.controls.application_input import application_inputs


class AppTaskBase(ZzzBaseTask, BaseTask):
    """单应用运行任务（app_id 由子类声明）。"""

    app_id: str = ''
    use_background_application = True

    # 成功结果里含有用户需要知道的说明（如电量不足未刷本）的应用
    SUCCESS_STATUS_APPS = frozenset({'charge_plan'})

    @property
    def report_success_status(self):
        return self.app_id in self.SUCCESS_STATUS_APPS

    def post_init(self):
        super().post_init()
        from src.tasks.app_option_ui import configure_app_options
        configure_app_options(self)

    def _parse_option(self, key, value):
        from zzz_od.application.app_options_data import APP_OPTIONS
        from src.tasks.app_option_ui import OPTION_LABELS
        label = OPTION_LABELS.get(key, key)
        if self.app_id == 'charge_plan' and key == 'plan_list':
            from src.tasks.plan_widgets import parse_charge_plans
            return parse_charge_plans(value)
        if self.app_id == 'notorious_hunt' and key == 'plan_list':
            from src.tasks.plan_widgets import NOTORIOUS_HUNT, parse_charge_plans
            return parse_charge_plans(value, category=NOTORIOUS_HUNT)
        option = next((o for a in APP_OPTIONS if a.get('app_id') == self.app_id
                       for o in a.get('options', []) if o['key'] == key), None)
        if option and option['type'] == 'json':
            try:
                parsed = json.loads(value) if isinstance(value, str) else value
            except (ValueError, TypeError) as exc:
                raise ValueError(f'{label}：JSON 格式错误（{exc}）') from None
            expected = dict if option['default'].lstrip().startswith('{') else list
            if not isinstance(parsed, expected):
                raise ValueError(f'{label}：需要 JSON {"对象" if expected is dict else "数组"}')
            return parsed
        return value

    def apply_options(self):
        """把任务配置写回应用配置（JSON 文本 → list/dict）。"""
        if not self._option_keys:
            return
        ctx = self.ctx
        app_config = ctx.run_context.get_config(
            self.app_id, instance_idx=ctx.current_instance_idx)
        # 先验证所有输入，再写回，避免配置错误后仍按旧配置操作游戏。
        updates = {}
        from src.tasks.app_option_ui import PLAN_LIST_APPS
        for key in self._option_keys:
            if key not in self.config:
                continue
            if key == 'plan_list' and self.app_id in PLAN_LIST_APPS and self.config.get(key) in ('', None):
                continue  # 尚未从引擎读取计划，保留引擎中的计划。
            updates[key] = self._parse_option(key, self.config.get(key))
        from zzz_od.application.charge_plan.charge_plan_config import ChargePlanItem
        if self.app_id == 'charge_plan':
            from zzz_od.application.charge_plan.charge_plan_config import ChargePlanConfig
            for row in updates.get('plan_list', []):
                error = ChargePlanConfig.validate_item(ctx, ChargePlanItem.from_dict(row))
                if error:
                    raise ValueError(f'刷本计划：{error}')
        if self.app_id == 'notorious_hunt':
            from zzz_od.application.notorious_hunt.notorious_hunt_config import NotoriousHuntConfig
            for row in updates.get('plan_list', []):
                error = NotoriousHuntConfig.validate_item(ctx, ChargePlanItem.from_dict(row))
                if error:
                    raise ValueError(f'狩猎计划：{error}')
        if self.app_id in PLAN_LIST_APPS:
            # Counts belong to the engine's runtime, not to an old UI snapshot.
            existing = {item.plan_id: item for item in app_config.plan_list}
            for row in updates.get('plan_list', []):
                if row['plan_id'] in existing:
                    row['run_times'] = existing[row['plan_id']].run_times
                    prior = existing[row['plan_id']]
                    row['fallback_single_runs'] = (prior.fallback_single_runs
                        if row.get('double_fallback') == prior.double_fallback
                        and row.get('category_name') == prior.category_name
                        and row.get('double_times', 0) > prior.run_times else 0)
        if self.app_id == 'lost_void' and updates.get('mission_name') == '矩阵行动' \
                and updates.get('matrix_team_mode') == '自定义编队':
            from zzz_od.application.hollow_zero.lost_void.matrix_team import resolve_agent_ids
            resolve_agent_ids([updates.get(f'matrix_agent_{idx}') for idx in range(1, 4)])
        previous = copy.deepcopy(app_config.data)
        try:
            previous_plans = getattr(app_config, 'plan_list', None)
            for key, value in updates.items():
                if key == 'plan_list' and self.app_id in PLAN_LIST_APPS:
                    app_config.plan_list = [ChargePlanItem.from_dict(row) for row in value]
                else:
                    app_config.update(key, value, save=False)
            app_config.save()
        except Exception:
            app_config.data = previous
            if self.app_id in PLAN_LIST_APPS:
                app_config.plan_list = previous_plans
            raise
        self.log_info(f'{self.name}：配置已应用')
        if self.app_id == 'lost_void':
            record = ctx.run_context.get_run_record(self.app_id, ctx.current_instance_idx)
            self.log_info(f'迷失之地计划：{app_config.extra_task}；'
                          f'今日 {record.daily_run_times}/{app_config.daily_plan_times} 次；'
                          f'本周 {record.weekly_run_times}/{app_config.weekly_plan_times} 次；'
                          f'悬赏已满额：{"是" if record.bounty_commission_complete else "否"}')

    def run(self):
        ctx = self.ctx
        try:
            self.apply_options()
        except Exception as exc:
            self.log_error(f'配置未能应用，任务已停止：{exc}', notify=True)
            raise
        self.stop_battle_triggers()
        with application_inputs(self):
            return self._run_application()

    def _run_application(self):
        ctx = self.ctx
        ctx.init_for_application()

        run_result = ctx.run_context.run_application(
            self.app_id, instance_idx=ctx.current_instance_idx)
        from src.tasks.app_option_ui import PLAN_LIST_APPS
        if self.app_id in PLAN_LIST_APPS:
            app_config = ctx.run_context.get_config(self.app_id, instance_idx=ctx.current_instance_idx)
            self.config['plan_list'] = json.dumps([item.to_dict() for item in app_config.plan_list], ensure_ascii=False)

        execute_after_done(ctx, run_result, after_done_request(self.config))
        self.report_run_result(run_result)

    def report_run_result(self, run_result):
        from onedragon.base.operation.application.application_run_context import RunFinishReason
        reason = run_result.finish_reason
        if reason == RunFinishReason.FAILED:
            result = self.ctx.run_context.last_application_result
            detail = getattr(result, 'status', None) or '未返回具体原因，请查看程序节点日志'
            self.info['执行结果'] = f'失败：{detail}'
            self.log_error(f'{self.name}运行失败：{detail}', notify=True)
        else:
            label = {RunFinishReason.COMPLETED: '已完成', RunFinishReason.STOPPED: '已停止',
                     RunFinishReason.NOT_STARTED: '未能启动'}.get(reason, str(reason))
            if reason == RunFinishReason.COMPLETED and self.report_success_status:
                # 成功也可能有需要用户知道的情况，例如体力刷本因电量不足未刷本。
                notice = getattr(self.ctx.run_context.last_application_result, 'status', None)
                if notice:
                    label = f'{label}：{notice}'
            self.info['执行结果'] = label
            self.log_info(f'{self.name}：{label}', notify=True)
