# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/hollow_zero/event/old_capital.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from onedragon.base.operation.operation_node import operation_node
from onedragon.base.operation.operation_round_result import OperationRoundResult
from onedragon.utils.i18_utils import gt
from zzz_od.context.zzz_context import ZContext
from zzz_od.hollow_zero.game_data.hollow_zero_event import HollowZeroSpecialEvent
from zzz_od.operation.zzz_operation import ZOperation


class OldCapital(ZOperation):

    def __init__(self, ctx: ZContext):
        """
        在旧都失物的画面了 选择返回
        :param ctx:
        """
        event_name = HollowZeroSpecialEvent.OLD_CAPITAL.value.event_name
        ZOperation.__init__(
            self, ctx,
            op_name=gt(event_name, 'game')
        )

    @operation_node(name='选择', is_start_node=True)
    def choose_one(self) -> OperationRoundResult:
        if getattr(self.ctx.controller, 'background_mode', False):
            from src.navigation.hollow_events import back_out
            visible = self.round_by_find_area(self.last_screenshot, '零号空洞-事件', '旧都失物-返回').is_success
            return back_out(self, self.last_screenshot, visible)
        return self.round_by_find_and_click_area(self.last_screenshot, '零号空洞-事件', '旧都失物-返回',
                                                 success_wait=1, retry_wait=1)
