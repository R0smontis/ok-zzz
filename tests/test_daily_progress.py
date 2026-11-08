"""一条龙运行中，任务信息表要显示当前账号、应用、节点状态和每项结果，不必翻日志文件。"""
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from onedragon.base.geometry.point import Point
from onedragon.base.operation.operation import Operation
from onedragon.base.operation.operation_base import OperationResult
from onedragon.base.operation.operation_node import operation_node
from onedragon.base.operation.operation_round_result import OperationRoundResult, OperationRoundResultEnum
from src.tasks.daily_task import OneDragonDailyTask
from test_one_dragon_daily import daily_context, drain_account, queue  # noqa: F401 (pytest fixture)
from test_runtime_interactions import task_factory  # noqa: F401 (pytest fixture)


def test_queue_reports_account_app_and_each_result(daily_context):
    ctx, factories = daily_context
    shown = {}
    ctx.run_context.progress_listener = shown.__setitem__
    group = ctx.run_context.get_group_config(1)
    group.set_app_enable('email', True); group.set_app_enable('coffee', True)
    factories['email'].get_run_record.return_value = SimpleNamespace(check_and_update_status=Mock(), is_done=True)
    coffee = factories['coffee'].create_application.return_value
    seen = []
    coffee.execute.side_effect = lambda: seen.append(dict(shown)) or OperationResult(False, '未找到咖啡店')
    app = queue(ctx)
    app.switch_instance()
    drain_account(app)
    # While 咖啡店 ran, its position among the account's enabled apps was visible.
    assert seen[0]['当前账号'] == '01（第 1/2 个）'
    assert seen[0]['当前应用'] == '咖啡店（第 2/2 项）'
    assert shown['账号 01 邮件'] == '今日已完成，跳过'
    assert shown['账号 01 咖啡店'].startswith('失败：未找到咖啡店（')
    assert shown['进度'] == '执行 1，成功 0，跳过 1，失败 1'


def test_failure_screen_belongs_to_the_failed_app_not_a_later_recovered_one(daily_context):
    ctx, factories = daily_context
    shown = {}
    ctx.run_context.progress_listener = shown.__setitem__
    group = ctx.run_context.get_group_config(1)
    group.set_app_enable('email', True); group.set_app_enable('coffee', True)
    def failed_email():
        ctx.run_context.report_progress('失败画面', '邮件：收件箱')
        return OperationResult(False, '领取失败')
    def recovered_coffee():
        # A node inside 咖啡店 failed once (screen reported), then the app recovered and succeeded.
        ctx.run_context.report_progress('失败画面', '咖啡店：加载中')
        return OperationResult(True, '已核验')
    factories['email'].create_application.return_value.execute.side_effect = failed_email
    factories['coffee'].create_application.return_value.execute.side_effect = recovered_coffee
    app = queue(ctx)
    app.switch_instance()
    drain_account(app)
    assert shown['失败画面'] == '邮件：收件箱'


def test_node_rounds_and_failure_screen_reach_the_task_info(ctx, monkeypatch):
    shown = {}
    ctx.run_context.progress_listener = shown.__setitem__
    rows = [SimpleNamespace(data='全部领取', center=Point(1500, 1000)),
            SimpleNamespace(data='UID：12345678', center=Point(1700, 1070))]
    monkeypatch.setattr(type(ctx), 'ocr_service',
                        property(lambda _self: SimpleNamespace(get_ocr_result_list=Mock(return_value=rows))))
    states = []

    class Mail(Operation):
        @operation_node(name='领取', is_start_node=True, node_max_retry_times=1)
        def claim(self):
            self.last_screenshot = np.zeros((1080, 1920, 3), np.uint8)
            states.append(dict(shown))
            return self.round_retry('未识别领取按钮')

    ctx.run_context.start_running()
    try:
        assert not Mail(ctx, op_name='邮件', need_check_game_win=False).execute().success
    finally:
        ctx.run_context.progress_listener = None
        ctx.run_context.stop_running()
    # The second round sees what the first round reported, including the retry count.
    assert states[1]['当前步骤'] == '邮件 · 领取'
    assert states[1]['步骤状态'] == '未识别领取按钮（重试 1/1）'
    assert shown['失败画面'] == '邮件：全部领取'


def test_broken_listener_never_stops_automation(ctx):
    ctx.run_context.progress_listener = Mock(side_effect=RuntimeError('ui'))
    try:
        ctx.run_context.report_progress('当前应用', '邮件')
    finally:
        ctx.run_context.progress_listener = None


def test_daily_info_rows_keep_order_and_drop_live_step_after_run(daily_context, task_factory):
    ctx, _ = daily_context
    task = task_factory(OneDragonDailyTask, ctx)
    task.info['账号 01 执行计划'] = '邮件'
    during = []
    def run_application(*_args, **_kwargs):
        # Results arrive before the first node round reports a step; the step rows must still sit above them.
        for key, value in (('当前应用', '邮件（第 1/1 项）'), ('账号 01 邮件', '成功（0 分 3 秒）'),
                           ('当前步骤', '邮件 · 领取'), ('步骤状态', '等待')):
            ctx.run_context.report_progress(key, value)
        during.append(list(task.info))
        return SimpleNamespace(finish_reason='completed')
    ctx.run_context.run_application = run_application
    ctx.run_context.last_application_result = OperationResult(True, '执行 1 项，成功 1 项')
    task._run_application()
    assert during[0] == ['账号 01 执行计划', '当前账号', '当前应用', '当前步骤', '步骤状态', '进度', '失败画面',
                         '账号 01 邮件']
    assert task.info['账号 01 邮件'] == '成功（0 分 3 秒）'
    # Live rows and never-filled placeholders are gone; the result row and the final result remain.
    assert not {'当前账号', '当前应用', '当前步骤', '步骤状态', '进度', '失败画面'} & set(task.info)
    assert task.info['执行结果'] == '执行 1 项，成功 1 项'
    assert ctx.run_context.progress_listener is None
