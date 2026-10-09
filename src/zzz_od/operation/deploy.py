# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/operation/deploy.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from onedragon.base.operation.operation_edge import node_from
from onedragon.base.operation.operation_node import operation_node
from onedragon.base.operation.operation_notify import NotifyTiming, node_notify
from onedragon.base.operation.operation_round_result import OperationRoundResult
from onedragon.utils.i18_utils import gt
from zzz_od.context.zzz_context import ZContext
from zzz_od.operation.zzz_operation import ZOperation
from src.controls.gamepad import press as pad


class Deploy(ZOperation):

    def __init__(self, ctx: ZContext):
        """
        在出战页面 点击出战
        同时处理可能出现的对话框
        :param ctx:
        """
        ZOperation.__init__(self, ctx, op_name=gt('出战', 'game'))
        self._deploy_requests = 0

    @operation_node(name='出战', is_start_node=True, timeout_seconds=30)
    def deploy(self) -> OperationRoundResult:
        if getattr(self.ctx.controller, 'background_mode', False):
            button = self.round_by_find_area(self.last_screenshot, '通用-出战', '按钮-出战')
            if button.is_success:
                if self._deploy_requests >= 5:
                    return self.round_fail('手柄出战后画面未变化，请检查游戏状态')
                self._deploy_requests += 1
                pad(self.ctx, 'start')
                return self.round_wait('手柄出战，等待画面变化', wait=1)
            if self._deploy_requests:
                return self.round_success('已离开出战画面', wait=1)
            return self.round_retry('尚未识别出战画面，未操作', wait=.5)
        return self.round_by_find_and_click_area(
            self.last_screenshot, '通用-出战', '按钮-出战',
            success_wait=1, retry_wait=1,
            until_not_find_all=[('通用-出战', '按钮-出战')]
        )

    @node_from(from_name='出战')
    @node_notify(when=NotifyTiming.CURRENT_FAIL, detail=True)
    @operation_node(name='出战确认')
    def check_level(self) -> OperationRoundResult:
        result = self.round_by_find_area(self.last_screenshot, '通用-出战', '标题-驱动盘数量已达到可拥有上限')
        if result.is_success:
            return self.round_fail('驱动盘数量已达到可拥有上限')

        if getattr(self.ctx.controller, 'background_mode', False):
            for area in ('按钮-队员数量少-确认', '按钮-等级低-确定并出战'):
                result = self.round_by_find_area(self.last_screenshot, '通用-出战', area)
                if result.is_success:
                    pad(self.ctx, 'a')
                    return self.round_wait(result.status, wait=1)
            if self.node_retry_times == self.node_max_retry_times - 1:
                return self.round_success('无需确认', wait=1)
            return self.round_retry('等待出战确认', wait=.5)
        result = self.round_by_find_and_click_area(self.last_screenshot, '通用-出战', '按钮-队员数量少-确认')
        if result.is_success:
            return self.round_wait(result.status, wait=1)

        result = self.round_by_find_and_click_area(self.last_screenshot, '通用-出战', '按钮-等级低-确定并出战')
        if result.is_success:
            return self.round_wait(result.status, wait=1)

        if self.node_retry_times == self.node_max_retry_times - 1:
            # 这里返回成功, 从而不发送失败通知
            return self.round_success('无需确认', wait=1)
        return self.round_retry('无需确认', wait=1)


def __debug():
    ctx = ZContext()
    ctx.init()
    ctx.init_ocr()
    ctx.run_context.start_running()
    op = Deploy(ctx)
    op.execute()


if __name__ == '__main__':
    __debug()
