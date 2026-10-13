# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/hollow_zero/hollow_exit_by_menu.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from onedragon.base.operation.operation_edge import node_from
from onedragon.base.operation.operation_node import operation_node
from onedragon.base.operation.operation_round_result import OperationRoundResult
from onedragon.utils.i18_utils import gt
from zzz_od.context.zzz_context import ZContext
from zzz_od.operation.zzz_operation import ZOperation


class HollowExitByMenu(ZOperation):

    def __init__(self, ctx: ZContext):
        """
        需要在空洞中 右下角有显示背包时使用
        如果有对话框的话会卡住
        :param ctx:
        """
        ZOperation.__init__(
            self, ctx,
            op_name=gt('离开空洞', 'game')
        )

    @operation_node(name='点击菜单', is_start_node=True)
    def click_menu(self) -> OperationRoundResult:
        if getattr(self.ctx.controller, 'background_mode', False):
            from src.navigation.hollow_events import exit_open_menu
            return exit_open_menu(self, self.last_screenshot)
        result = self.round_by_find_area(self.last_screenshot, '零号空洞-事件', '放弃')
        if result.is_success:  # 点击到出现了放弃按钮为止
            return self.round_success()

        result = self.round_by_click_area('零号空洞-事件', '菜单')
        if result.is_success:
            return self.round_wait(wait=1)

        return self.round_retry(result.status, wait=1)

    @node_from(from_name='点击菜单')
    @operation_node(name='点击离开')
    def click_leave(self) -> OperationRoundResult:
        if getattr(self.ctx.controller, 'background_mode', False):
            from src.navigation.hollow_events import exit_abandon
            return exit_abandon(self, self.last_screenshot)
        return self.round_by_find_and_click_area(self.last_screenshot, '零号空洞-事件', '放弃',
                                                 success_wait=1, retry_wait=1)

    @node_from(from_name='点击离开')
    @operation_node(name='确认离开')
    def confirm_leave(self) -> OperationRoundResult:
        if getattr(self.ctx.controller, 'background_mode', False):
            from src.navigation.hollow_events import exit_confirm
            return exit_confirm(self, self.last_screenshot)
        return self.round_by_find_and_click_area(self.last_screenshot, '零号空洞-事件', '放弃-确认',
                                                 success_wait=1, retry_wait=1)

    @node_from(from_name='确认离开')
    @operation_node(name='点击完成', node_max_retry_times=20)
    def click_finish(self) -> OperationRoundResult:
        # 这个按钮刚出现的时候可以按不到 需要重复按它
        if getattr(self.ctx.controller, 'background_mode', False):
            if self.round_by_find_area(self.last_screenshot, '零号空洞-入口', '街区').is_success:
                return self.round_success()
            if self.round_by_find_area(self.last_screenshot, '零号空洞-事件', '通关-完成').is_success:
                from src.controls.gamepad import press
                presses = getattr(self, '_pad_finish_presses', 0)
                if presses >= 10:
                    return self.round_fail('手柄确认通关完成未生效')
                self._pad_finish_presses = presses + 1
                press(self.ctx, 'a')
                return self.round_wait('手柄确认通关完成', wait=1.5)
            return self.round_retry(wait=1)
        result = self.round_by_find_and_click_area(self.last_screenshot, '零号空洞-事件', '通关-完成')
        if result.is_success:
            return self.round_wait(wait=1)

        result = self.round_by_find_area(self.last_screenshot, '零号空洞-入口', '街区')
        if result.is_success:  # 点击直到返回显示街区为止
            return self.round_success()

        return self.round_retry(wait=1)