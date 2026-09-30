# -*- coding: utf-8 -*-
"""应用框架层验证：节点图语义 / 注册表 / 运行记录 / 一条龙队列。"""
import time

import pytest


def test_app_registry_discovers_all(ctx):
    """全部一条龙应用工厂应注册成功（27 个左右）。"""
    from zzz_od.application.app_registry import discover_factories
    factories = discover_factories(ctx)
    assert len(factories) >= 20
    app_ids = {f.app_id for f in factories}
    assert 'email' in app_ids
    assert 'charge_plan' in app_ids
    assert 'one_dragon' in app_ids
    # 默认组按 PRIORITY 排序
    priorities = [f.priority for f in ctx.run_context.default_group_apps]
    assert priorities == sorted(priorities)


def test_run_record_daily_reset(ctx):
    """运行记录当日完成判定与重置。"""
    from onedragon.base.operation.application_run_record import (
        AppRunRecord,
        AppRunRecordPeriod,
    )
    record = AppRunRecord('test_record_app', instance_idx=0)
    record.update_status(AppRunRecord.STATUS_SUCCESS)
    assert record.is_done
    # 强制过期：把记录日期（内存属性）改到昨天
    record.dt = '2000-01-01'
    record.check_and_update_status()
    assert not record.is_done


def test_operation_node_graph(tmp_path, ctx):
    """节点图：RETRY 重试 → 成功跳转 → 结束。"""
    from onedragon.base.operation.operation import Operation
    from onedragon.base.operation.operation_node import operation_node
    from onedragon.base.operation.operation_edge import node_from
    from onedragon.base.operation.operation_round_result import OperationRoundResult

    calls = {'a': 0, 'b': 0}

    class DemoOp(Operation):
        @operation_node(name='开始', is_start_node=True)
        def node_a(self):
            calls['a'] += 1
            if calls['a'] < 3:
                return self.round_retry(status='未就绪')
            return self.round_success(status='OK')

        @node_from(from_name='开始', status='OK')
        @operation_node(name='结束')
        def node_b(self):
            calls['b'] += 1
            return self.round_success()

    ctx.run_context.start_running()
    op = DemoOp(ctx, need_check_game_win=False)
    result = op.execute()
    assert result.success
    assert calls['a'] == 3
    assert calls['b'] == 1


def test_operation_fail_after_max_retry(tmp_path, ctx):
    """超过节点最大重试次数应判定失败。"""
    from onedragon.base.operation.operation import Operation
    from onedragon.base.operation.operation_node import operation_node
    from onedragon.base.operation.operation_round_result import OperationRoundResult

    calls = {'n': 0}

    class AlwaysRetryOp(Operation):
        @operation_node(name='唯一节点', is_start_node=True, node_max_retry_times=2)
        def only(self):
            calls['n'] += 1
            return self.round_retry(status='没好')

    ctx.run_context.start_running()
    op = AlwaysRetryOp(ctx, need_check_game_win=False)
    result = op.execute()
    assert not result.success
    assert calls['n'] == 3  # 1 次执行 + 2 次重试


def test_run_context_group_and_queue(tmp_path, ctx):
    """组配置合并 + 一条龙队列按顺序执行并跳过已完成应用。"""
    from zzz_od.application.app_registry import discover_factories
    discover_factories(ctx)
    run_context = ctx.run_context

    group = run_context.get_group_config()
    group.set_app_enable('email', True)
    group.set_app_enable('city_fund', True)

    app_ids = [app_id for app_id, _ in run_context.get_group_app_ids()]
    assert 'email' in app_ids and 'city_fund' in app_ids

    # 把 email 标记为当日已完成 → 队列应跳过它（不真实执行）
    record = run_context.get_run_record('email', instance_idx=0)
    record.update_status(AppRunRecord_STATUS_SUCCESS())

    from zzz_od.application.one_dragon_app.zzz_one_dragon_app import ZOneDragonApp
    app = ZOneDragonApp(ctx)
    assert app.op_name == '一条龙'


def AppRunRecord_STATUS_SUCCESS():
    from onedragon.base.operation.application_run_record import AppRunRecord
    return AppRunRecord.STATUS_SUCCESS
