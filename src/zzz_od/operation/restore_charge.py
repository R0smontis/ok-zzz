# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/operation/restore_charge.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from typing import ClassVar

from onedragon.base.geometry.point import Point
from onedragon.base.operation.application import application_const
from onedragon.base.operation.operation_edge import node_from
from onedragon.base.operation.operation_node import operation_node
from onedragon.base.operation.operation_round_result import OperationRoundResult
from onedragon.utils.i18_utils import gt
from onedragon.utils.log_utils import log
from zzz_od.application.charge_plan import charge_plan_const
from zzz_od.application.charge_plan.charge_plan_config import (
    ChargePlanConfig,
    RestoreChargeEnum,
)
from zzz_od.context.zzz_context import ZContext
from zzz_od.operation.zzz_operation import ZOperation
from src.controls.gamepad import press as pad
from src.navigation.restore_charge import quick_use, source_page, choose_source, confirm_source


class RestoreCharge(ZOperation):
    """
    电量恢复操作类
    负责处理副本内的恢复电量弹窗，支持储蓄电量和以太电池两种恢复方式
    """

    SOURCE_BACKUP_CHARGE: ClassVar[str] = '储蓄电量'
    SOURCE_ETHER_BATTERY: ClassVar[str] = '以太电池'
    STATUS_CHARGE_NOT_ENOUGH: ClassVar[str] = '电量不足'
    STATUS_RESTORE_SUCCESS: ClassVar[str] = '恢复电量成功'

    def __init__(self, ctx: ZContext) -> None:
        """
        初始化电量恢复操作

        Args:
            ctx: ZContext实例
        """
        ZOperation.__init__(
            self,
            ctx=ctx,
            op_name='恢复电量'
        )
        self.config: ChargePlanConfig = self.ctx.run_context.get_config(
            app_id=charge_plan_const.APP_ID,
            instance_idx=self.ctx.current_instance_idx,
            group_id=application_const.DEFAULT_GROUP_ID,
        )

        self.is_after_battle_retry: bool = False
        self.skip_backup_charge: bool = False

    def handle_init(self):
        self.skip_backup_charge = False
        self._restore_obtained_seen = False
        self._restore_source = None
        self._restore_before_amount = None
        self._restore_exchange_amount = None

    def _should_confirm_restore(self, current_amount: int, exchange_amount: int) -> bool:
        return 0 < exchange_amount <= current_amount

    def _should_reselect_source(self, source: str) -> bool:
        return (
            source == self.SOURCE_BACKUP_CHARGE
            and self.config.restore_charge == RestoreChargeEnum.BOTH.value.value
        )


    @node_from(from_name='关闭快捷使用', status='重新选择电量来源')
    @operation_node(name='打开恢复界面', is_start_node=True)
    def click_charge_text(self) -> OperationRoundResult:
        # 检查是否已经在恢复界面
        result = self.round_by_find_area(self.last_screenshot, '恢复电量', '标题-恢复电量')
        if result.is_success:
            return self.round_success()

        if getattr(self.ctx.controller, 'background_mode', False):
            if self.is_after_battle_retry:
                area = self.round_by_find_area(self.last_screenshot, '战斗画面', '战斗结果-再来一次')
                if not area.is_success:
                    return self.round_retry('未核验再来一次按钮，未操作', wait=.5)
                pad(self.ctx, 'x')
                return self.round_wait('打开战后恢复电量，等待实际弹窗', wait=.5)
            from src.navigation.menus import pad_next_step
            return pad_next_step(self)
        if self.is_after_battle_retry:
            return self.round_by_find_and_click_area(self.last_screenshot, '战斗画面', '战斗结果-再来一次', success_wait=0.5)
        return self.round_by_find_and_click_area(self.last_screenshot, '实战模拟室', '下一步', success_wait=0.5)

    @node_from(from_name='打开恢复界面')
    @operation_node(name='选择电量来源')
    def select_charge_source(self) -> OperationRoundResult:
        if self.config.restore_charge == RestoreChargeEnum.BACKUP_ONLY.value.value:
            target_list = [self.SOURCE_BACKUP_CHARGE]
        elif self.config.restore_charge == RestoreChargeEnum.ETHER_ONLY.value.value:
            target_list = [self.SOURCE_ETHER_BATTERY]
        elif self.config.restore_charge == RestoreChargeEnum.BOTH.value.value:
            target_list = [self.SOURCE_BACKUP_CHARGE, self.SOURCE_ETHER_BATTERY]
            if self.skip_backup_charge:
                target_list = target_list[1:]
        else:
            target_list = []
        if not target_list:
            return self.round_fail('未启用电量恢复，未操作')
        self._restore_source = target_list[0]
        if getattr(self.ctx.controller, 'background_mode', False):
            return choose_source(self, self._restore_source)

        target_text_list = [gt(text, 'game') for text in target_list]
        target_area = self.ctx.screen_loader.get_area('恢复电量', '类型')

        return self.round_by_ocr_and_click_by_priority(
            screen=self.last_screenshot,
            target_cn_list=target_text_list,
            area=target_area,
            offset=Point(0, -100)
        )

    @node_from(from_name='选择电量来源')
    @operation_node(name='确认电量来源')
    def confirm_charge_source(self) -> OperationRoundResult:
        if getattr(self.ctx.controller, 'background_mode', False):
            return confirm_source(self, self._restore_source)
        click = self.round_by_find_and_click_area(self.last_screenshot, '恢复电量', '确认', success_wait=0.5, retry_wait=0.5)
        if click.is_success:
            return self.round_success(status=self.previous_node.status, wait=0.5)
        return self.round_retry('未找到确认按钮', wait=0.5)

    @node_from(from_name='确认电量来源')
    @operation_node(name='识别当前数量')
    def set_charge_amount(self) -> OperationRoundResult:
        source = self.previous_node.status
        if source is None:
            return self.round_retry('未识别到电量来源', wait=0.5)

        quick = quick_use(self)
        if quick is None:
            return self.round_retry('未核验快捷使用来源和数量，未操作', wait=.5)
        actual_source, current_amount, exchange_amount = quick
        if actual_source != source or source not in (self.SOURCE_BACKUP_CHARGE, self.SOURCE_ETHER_BATTERY):
            return self.round_fail('快捷使用来源与配置不一致，未消耗')
        self._restore_source = source
        self._restore_before_amount = current_amount
        self._restore_exchange_amount = exchange_amount
        log.info(f'{source} 当前数量 {current_amount}')

        log.info(f'{source} 兑换数量 {exchange_amount}')

        if not self._should_confirm_restore(current_amount, exchange_amount):
            if self._should_reselect_source(source):
                self.skip_backup_charge = True
                return self.round_success(status='重新选择电量来源', data=exchange_amount, wait=0.5)
            return self.round_success(status=self.STATUS_CHARGE_NOT_ENOUGH, data=exchange_amount, wait=0.5)

        return self.round_success(status=source, data=exchange_amount, wait=0.5)

    @node_from(from_name='识别当前数量', status='重新选择电量来源')
    @node_from(from_name='识别当前数量', status=STATUS_CHARGE_NOT_ENOUGH)
    @operation_node(name='关闭快捷使用')
    def close_quick_use_popup(self) -> OperationRoundResult:
        result = self.round_by_find_area(self.last_screenshot, '恢复电量', '标题-快捷使用')
        if not result.is_success:
            return self.round_success(status=self.previous_node.status, wait=0.5)

        if getattr(self.ctx.controller, 'background_mode', False):
            pad(self.ctx, 'b')
            return self.round_retry('关闭未使用的快捷使用页，等待实际画面', wait=.5)
        result = self.round_by_find_and_click_area(self.last_screenshot, '菜单', '关闭', success_wait=0.5, retry_wait=0.5)
        if result.is_success:
            return self.round_retry('尝试关闭快捷使用', wait=0.5)

        return self.round_retry('未关闭快捷使用', wait=0.5)

    @node_from(from_name='识别当前数量', status=SOURCE_BACKUP_CHARGE)
    @node_from(from_name='识别当前数量', status=SOURCE_ETHER_BATTERY)
    @operation_node(name='确认恢复电量')
    def confirm_restore_charge(self) -> OperationRoundResult:
        quick = quick_use(self)
        if quick is None or quick != (self._restore_source, self._restore_before_amount, self._restore_exchange_amount):
            return self.round_retry('恢复来源或数量发生变化，未确认', wait=.5)
        if not self._should_confirm_restore(quick[1], quick[2]):
            return self.round_fail('恢复数量无效，未消耗')
        if getattr(self.ctx.controller, 'background_mode', False):
            pad(self.ctx, 'a')
            return self.round_success('确认恢复，等待实际结果', wait=.5)
        return self.round_by_find_and_click_area(self.last_screenshot, '恢复电量', '确认', success_wait=1, retry_wait=.5)

    @node_from(from_name='确认恢复电量')
    @operation_node(name='恢复后处理')
    def confirm_after_restore(self) -> OperationRoundResult:
        """
        选副本阶段触发恢复：“恢复电量”的确认->“快捷使用”的确认->“获得”的确认
        战斗后点“再来一次”触发恢复：“恢复电量”的确认->“快捷使用”的确认
        上个节点已处理“快捷使用”的确认，这个节点处理后续可能出现的确认层
        """
        if getattr(self.ctx.controller, 'background_mode', False):
            quick = quick_use(self)
            if quick is not None:
                if quick[0] != self._restore_source or quick[1] == self._restore_before_amount:
                    return self.round_retry('等待快捷使用确认生效，未重复消耗', wait=.5)
                return self.round_fail('快捷使用数量变化异常，停止重复补充')
            result = self.round_by_find_area(self.last_screenshot, '恢复电量', '标题-获得')
            if result.is_success:
                self._restore_obtained_seen = True
                pad(self.ctx, 'a')
                return self.round_wait('确认补充获得结果，等待返回', wait=.5)
            if source_page(self) is not None:
                pad(self.ctx, 'b')
                return self.round_wait('关闭已补充电量来源页，等待返回', wait=.5)
            if getattr(self, '_restore_obtained_seen', False) or (self.is_after_battle_retry
                    and self.round_by_find_area(self.last_screenshot, '战斗画面', '战斗结果-再来一次').is_success):
                return self.round_success(self.STATUS_RESTORE_SUCCESS)
            return self.round_retry('未核验恢复结果或战斗结算画面，未报告成功', wait=.5)
        for area_name in ('标题-获得', '标题-快捷使用'):
            result = self.round_by_find_area(self.last_screenshot, '恢复电量', area_name)
            if not result.is_success:
                continue
            result = self.round_by_find_and_click_area(self.last_screenshot, '恢复电量', '确认', success_wait=0.5, retry_wait=0.5)
            if result.is_success:
                return self.round_wait('等待恢复完成', wait=0.5)
            return self.round_retry('恢复电量失败', wait=0.5)
        return self.round_success(self.STATUS_RESTORE_SUCCESS, wait=0.5)

def __debug():
    ctx = ZContext()
    ctx.init()
    ctx.init_ocr()
    ctx.run_context.start_running()
    op = RestoreCharge(ctx)
    op.execute()

if __name__ == '__main__':
    __debug()
