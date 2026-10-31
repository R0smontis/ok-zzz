"""Account queues and daily results must reach the selected applications."""
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from onedragon.base.config.one_dragon_config import InstanceRun
from onedragon.base.operation.application.application_run_context import ApplicationRunContext, RunFinishReason
from onedragon.base.operation.operation_base import OperationResult
from onedragon.utils import os_utils
from src.tasks.daily_task import OneDragonDailyTask
from zzz_od.application.one_dragon_app.zzz_one_dragon_app import ZOneDragonApp, STATUS_ALL_DONE
from test_runtime_interactions import task_factory


@pytest.fixture
def daily_context(tmp_path, monkeypatch):
    monkeypatch.setattr(os_utils, '_work_dir', tmp_path)
    instances=[SimpleNamespace(idx=1),SimpleNamespace(idx=2)]
    ctx=SimpleNamespace(current_instance_idx=1, controller=Mock(), game_account_config=Mock(),
        one_dragon_config=SimpleNamespace(instance_run=InstanceRun.ALL.value.value,
            current_active_instance=instances[0]),instance_list_in_od=instances,
        init_for_application=Mock())
    ctx.run_context=ApplicationRunContext(ctx)
    # Reproduce an empty group opened before registration, plus another account.
    ctx.run_context.get_group_config(1)
    ctx.run_context.get_group_config(2)
    factories={}
    for priority, (app_id,name) in enumerate([('email','邮件'),('coffee','咖啡店')]):
        app=SimpleNamespace(op_name=name,execute=Mock(return_value=OperationResult(True,'已核验')))
        factory=SimpleNamespace(app_id=app_id,app_name=name,default_group=True,priority=priority,
            need_notify=False,create_application=Mock(return_value=app),
            get_run_record=Mock(return_value=None))
        ctx.run_context.registry_application(factory)
        factories[app_id]=factory
    def switch(index):ctx.current_instance_idx=index
    ctx.switch_instance=Mock(side_effect=switch)
    monkeypatch.setattr('zzz_od.application.one_dragon_app.zzz_one_dragon_app.GameAccountConfig.is_different_game_path',lambda *_:False)
    return ctx,factories


def queue(ctx):
    app=ZOneDragonApp(ctx)
    app._after_round_wait=lambda **_:None
    return app


def drain_account(app):
    for _ in range(5):
        if app.run_app().status==STATUS_ALL_DONE:return
    raise AssertionError('Queue did not terminate')


def test_default_groups_follow_actual_account_and_repopulate_cached_empty_groups(daily_context):
    ctx,_=daily_context
    assert ctx.run_context.current_instance_idx==1
    for index in (1,2,3):
        assert ctx.run_context.get_group_app_ids(index)==[('email',False),('coffee',False)]
    ctx.current_instance_idx=2
    assert ctx.run_context.get_group_config() is ctx.run_context.get_group_config(2)


def test_daily_selection_reaches_actual_account_and_executes_in_user_order(daily_context,task_factory):
    ctx,factories=daily_context
    task=task_factory(OneDragonDailyTask,ctx)
    task.config['启用应用']=['邮件','咖啡店']
    task.config['执行顺序']=['咖啡店','邮件']
    task._sync_group_config()
    assert ctx.run_context.get_group_app_ids(1)==[('coffee',True),('email',True)]
    assert not any(enabled for _,enabled in ctx.run_context.get_group_app_ids(2))
    app=queue(ctx)
    app.switch_instance()
    drain_account(app)
    assert app.finish().is_success
    assert app._executed_app_count==app._success_app_count==2
    factories['email'].create_application.return_value.execute.assert_called_once()
    factories['coffee'].create_application.return_value.execute.assert_called_once()


def test_unselected_or_disabled_queue_is_not_success(daily_context):
    ctx,_=daily_context
    app=queue(ctx)
    app.switch_instance()
    drain_account(app)
    assert app.finish().is_fail
    assert '未启用' in app.finish().status
    ctx.instance_list_in_od=[]
    assert queue(ctx).switch_instance().is_fail


def test_completed_records_are_skipped_with_explicit_no_work_result(daily_context):
    ctx,factories=daily_context
    ctx.run_context.get_group_config(1).set_app_enable('email',True)
    record=SimpleNamespace(check_and_update_status=Mock(),is_done=True)
    factories['email'].get_run_record.return_value=record
    app=queue(ctx)
    app.switch_instance()
    drain_account(app)
    assert app.finish().is_success
    assert '本次无需执行' in app.finish().status
    record.check_and_update_status.assert_called_once()
    factories['email'].create_application.return_value.execute.assert_not_called()


@pytest.mark.parametrize('failure',['result','exception','initialization'])
def test_child_failure_is_preserved_across_accounts(daily_context,failure):
    ctx,factories=daily_context
    for index in (1,2):ctx.run_context.get_group_config(index).set_app_enable('email',True)
    factory=factories['email']
    if failure=='result':factory.create_application.return_value.execute.return_value=OperationResult(False,'领取失败')
    elif failure=='exception':factory.create_application.return_value.execute.side_effect=RuntimeError('异常')
    else:factory.create_application.side_effect=RuntimeError('初始化失败')
    app=queue(ctx)
    app.switch_instance()
    drain_account(app)
    failures=list(app._fail_app_list)
    app.switch_instance()
    drain_account(app)
    assert app._fail_app_list[:len(failures)]==failures
    assert len(app._fail_app_list)==2 and app.finish().is_fail


def test_summary_names_each_failure_reason_and_low_charge_notice(daily_context):
    # Report 2026-10-22: the result only listed failed app names, so users could not tell why.
    ctx,factories=daily_context
    group=ctx.run_context.get_group_config(1)
    group.set_app_enable('email',True); group.set_app_enable('coffee',True)
    factories['email'].create_application.return_value.execute.return_value=OperationResult(False,'领取失败')
    coffee=factories['coffee'].create_application.return_value
    coffee.result_notice='电量不足：实战模拟室 音擎改装需要 20，本次未刷本；剩余电量 10'
    app=queue(ctx)
    app.switch_instance()
    drain_account(app)
    result=app.finish()
    assert result.is_fail
    assert '账号 01 邮件：领取失败' in result.status
    assert '账号 01 咖啡店：电量不足：实战模拟室 音擎改装需要 20' in result.status
    # A successful app's notice alone does not turn the run into a failure.
    factories['email'].create_application.return_value.execute.return_value=OperationResult(True,'已核验')
    app=queue(ctx)
    app.switch_instance()
    drain_account(app)
    result=app.finish()
    assert result.is_success and '电量不足' in result.status and '领取失败' not in result.status


@pytest.mark.parametrize('current_only',[False,True])
def test_daily_start_syncs_exactly_selected_accounts(daily_context,task_factory,monkeypatch,current_only):
    ctx,_=daily_context
    if current_only:ctx.one_dragon_config.instance_run=InstanceRun.CURRENT.value.value
    task=task_factory(OneDragonDailyTask,ctx)
    task.config['启用应用']=['邮件']
    task._run_application=Mock()
    monkeypatch.setattr('src.tasks.daily_task.application_inputs',lambda _:nullcontext())
    task.run()
    assert dict(ctx.run_context.get_group_app_ids(1))['email']
    assert dict(ctx.run_context.get_group_app_ids(2))['email']==(not current_only)
    task._run_application.assert_called_once()


@pytest.mark.parametrize('reason',[RunFinishReason.FAILED,RunFinishReason.NOT_STARTED])
def test_failed_daily_result_is_reported_as_failure_and_never_finalized(daily_context,task_factory,monkeypatch,reason):
    ctx,_=daily_context
    ctx.run_context.run_application=Mock(return_value=SimpleNamespace(finish_reason=reason))
    ctx.run_context.last_application_result=OperationResult(False,'未启用任何日常应用')
    finalizer=Mock()
    monkeypatch.setattr('onedragon.base.operation.one_dragon_finalizer.execute_after_done',finalizer)
    task=task_factory(OneDragonDailyTask,ctx)
    task.config['结束后']='关闭游戏'
    with pytest.raises(RuntimeError,match='未启用'):
        task._run_application()
    assert '未启用' in task.info['执行结果']
    finalizer.assert_not_called()


def test_unchecked_daily_cannot_start(daily_context,task_factory):
    ctx,_=daily_context
    task=task_factory(OneDragonDailyTask,ctx)
    task.config['启用应用']=[]
    task._run_application=Mock()
    with pytest.raises(ValueError,match='未启用'):task.run()
    task._run_application.assert_not_called()


@pytest.mark.parametrize('current_only',[False,True])
def test_real_queue_graph_visits_every_selected_account_before_finishing(daily_context,current_only):
    ctx,factories=daily_context
    if current_only:ctx.one_dragon_config.instance_run=InstanceRun.CURRENT.value.value
    for index in (1,2):ctx.run_context.get_group_config(index).set_app_enable('email',True)
    app=queue(ctx)
    app._init_network()
    app._current_node=app._node_map['切换到下一个实例']
    for _ in range(20):
        result=app._current_node.op_method(app)
        next_node=app._get_next_node(result)
        if next_node is None:break
        app._current_node=next_node
    else:raise AssertionError('Account graph did not terminate')
    expected=[1] if current_only else [1,2]
    assert [call.args[0] for call in ctx.switch_instance.call_args_list]==expected
    assert factories['email'].create_application.return_value.execute.call_count==len(expected)
    assert result.is_success and app._current_node.cn=='一条龙结束'


def test_stopped_daily_does_not_finalize_or_report_completion(daily_context,task_factory,monkeypatch):
    ctx,_=daily_context
    ctx.run_context.run_application=Mock(return_value=SimpleNamespace(finish_reason=RunFinishReason.STOPPED))
    ctx.run_context.last_application_result=OperationResult(False,'停止')
    finalizer=Mock()
    monkeypatch.setattr('onedragon.base.operation.one_dragon_finalizer.execute_after_done',finalizer)
    task=task_factory(OneDragonDailyTask,ctx)
    task._run_application()
    assert task.info['执行结果']=='已停止，尚未完成一条龙'
    finalizer.assert_not_called()
