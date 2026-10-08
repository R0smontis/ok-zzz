# -*- coding: utf-8 -*-
"""一条龙总调度（ok-zzz 重建）。

对齐 GroupApplication + OneDragonApp 的语义（自 one_dragon 重建而非逐行移植）：
按组配置顺序执行启用的应用 → 当日已完成的应用跳过 → 全部完成后
切换下一个实例（游戏路径不同则先关游戏再切）→ 循环直到实例跑完。

与原版的差异：多实例循环节点图简化为单节点内的协作循环
（暂停/停止检查点仍由 Operation 主循环在轮间执行）。
"""
import time

from onedragon.base.config.game_account_config import GameAccountConfig
from onedragon.base.operation.operation_edge import node_from
from onedragon.base.operation.operation_node import operation_node
from onedragon.base.operation.operation_round_result import OperationRoundResult
from onedragon.utils.log_utils import log
from zzz_od.application.one_dragon_app import one_dragon_app_const
from zzz_od.application.zzz_application import ZApplication

STATUS_NEXT = 'next'
STATUS_ALL_DONE = 'all_done'
STATUS_INSTANCE_NEXT = 'instance_next'
STATUS_INSTANCE_ALL_DONE = 'instance_all_done'


class ZOneDragonApp(ZApplication):

    def __init__(self, ctx, op_name: str = '一条龙'):
        ZApplication.__init__(
            self, ctx=ctx, app_id=one_dragon_app_const.APP_ID, op_name=op_name)
        self.current_instance_idx: int = -1  # 当前实例在实例列表中的下标
        self.current_app_idx: int = -1  # 当前应用在组列表中的下标
        self._fail_app_list: list[str] = []
        self._enabled_app_count = 0
        self._executed_app_count = 0
        self._success_app_count = 0
        self._skipped_done_count = 0

    def _instance_list(self):
        """本轮需要运行的实例列表（一条龙配置决定全部/当前）。"""
        from onedragon.base.config.one_dragon_config import InstanceRun
        one_dragon_config = self.ctx.one_dragon_config
        if one_dragon_config.instance_run == InstanceRun.CURRENT.value.value:
            current = one_dragon_config.current_active_instance
            return [current] if current is not None else []
        return self.ctx.instance_list_in_od

    def _group_app_list(self):
        """[(app_id, enabled)] 按组配置顺序。"""
        return self.ctx.run_context.get_group_app_ids(
            instance_idx=self.ctx.current_instance_idx)

    @node_from(from_name='执行应用', status=STATUS_ALL_DONE)
    @operation_node(name='切换到下一个实例', is_start_node=True)
    def switch_instance(self) -> OperationRoundResult:
        instance_list = self._instance_list()
        if not instance_list:
            return self.round_fail('一条龙未选择运行账号')
        self.current_instance_idx += 1
        if self.current_instance_idx >= len(instance_list):
            return self.round_success(status=STATUS_INSTANCE_ALL_DONE)
        instance = instance_list[self.current_instance_idx]

        # 游戏路径不同则先关闭游戏再切（沿用原版语义）
        if self.current_instance_idx > 0:
            game_account_config = self.ctx.game_account_config
            if GameAccountConfig.is_different_game_path(
                    self.ctx.current_instance_idx, instance.idx):
                self.ctx.controller.close_game()

        self.ctx.switch_instance(instance.idx)
        self.current_app_idx = -1
        log.info('一条龙账号 %02d 执行队列：%s', instance.idx,
                 ' → '.join(app_id for app_id, enabled in self._group_app_list() if enabled)
                 or '未启用任何应用')
        return self.round_success(status=STATUS_INSTANCE_NEXT)

    @node_from(from_name='切换到下一个实例', status=STATUS_INSTANCE_NEXT)
    @node_from(from_name='执行应用', status=STATUS_NEXT)
    @operation_node(name='执行应用')
    def run_app(self) -> OperationRoundResult:
        app_list = self._group_app_list()
        self.current_app_idx += 1
        if self.current_app_idx >= len(app_list):
            return self.round_success(status=STATUS_ALL_DONE)
        app_id, enabled = app_list[self.current_app_idx]
        if not enabled:
            return self.round_success(status=STATUS_NEXT)
        self._enabled_app_count += 1
        try:
            app = self.ctx.run_context.get_application(
                app_id, instance_idx=self.ctx.current_instance_idx)
            app_name = app.op_name
        except Exception as exc:
            self._fail_app_list.append(f'账号 {self.ctx.current_instance_idx:02d} {app_id}')
            log.error('一条龙应用初始化失败 %s：%s', app_id, exc, exc_info=True)
            return self.round_success(status=STATUS_NEXT)

        run_record = self.ctx.run_context.get_run_record(
            app_id, instance_idx=self.ctx.current_instance_idx)
        if run_record is not None:
            run_record.check_and_update_status()
            if run_record.is_done:
                self._skipped_done_count += 1
                log.info(f'跳过已完成应用 {app_name}')
                return self.round_success(status=STATUS_NEXT)

        self._executed_app_count += 1
        log.info('一条龙开始执行 %s（账号 %02d）', app_name, self.ctx.current_instance_idx)
        try:
            app_result = app.execute()
            success = getattr(app_result, 'success', False)
            detail = getattr(app_result, 'status', None)
        except Exception as exc:
            success, detail = False, str(exc)
            log.error('一条龙应用运行异常 %s', app_name, exc_info=True)
        if success:
            self._success_app_count += 1
        else:
            self._fail_app_list.append(f'账号 {self.ctx.current_instance_idx:02d} {app_name}')
        log.info('一条龙应用结束 %s：%s；%s', app_name, '成功' if success else '失败', detail or '')
        return self.round_success(status=STATUS_NEXT)

    @node_from(from_name='切换到下一个实例', status=STATUS_INSTANCE_ALL_DONE)
    @operation_node(name='一条龙结束')
    def finish(self) -> OperationRoundResult:
        summary = (f'执行 {self._executed_app_count} 项，成功 {self._success_app_count} 项，'
                   f'已完成跳过 {self._skipped_done_count} 项，失败 {len(self._fail_app_list)} 项')
        if len(self._fail_app_list) > 0:
            log.error('失败的应用 %s', self._fail_app_list)
            return self.round_fail(summary + '；' + '、'.join(self._fail_app_list))
        if self._enabled_app_count == 0:
            return self.round_fail('未启用任何日常应用，请先勾选要执行的项目')
        if self._executed_app_count == 0:
            return self.round_success(f'所选 {self._skipped_done_count} 项均已完成，本次无需执行')
        return self.round_success(summary)


def __debug():
    ctx = None  # 与其他应用一致的无 GUI 调试入口（真实运行走 ok-script 任务）
    print(ctx)
    time.sleep(0)


if __name__ == '__main__':
    __debug()
