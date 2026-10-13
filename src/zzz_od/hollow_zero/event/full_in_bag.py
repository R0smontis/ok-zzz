# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/hollow_zero/event/full_in_bag.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from onedragon.base.operation.operation_node import operation_node
from onedragon.base.operation.operation_round_result import OperationRoundResult
from onedragon.utils.i18_utils import gt
from zzz_od.context.zzz_context import ZContext
from zzz_od.hollow_zero.game_data.hollow_zero_event import HollowZeroSpecialEvent
from zzz_od.operation.zzz_operation import ZOperation


class FullInBag(ZOperation):

    def __init__(self, ctx: ZContext):
        """
        确定出现事件后调用
        :param ctx:
        """
        ZOperation.__init__(
            self, ctx,
            op_name=gt(HollowZeroSpecialEvent.FULL_IN_BAG.value.event_name, 'game')
        )

    @operation_node(name='丢弃', is_start_node=True)
    def drop(self) -> OperationRoundResult:
        if getattr(self.ctx.controller, 'background_mode', False):
            from onedragon.base.geometry.rectangle import Rect
            from src.navigation.hollow_events import bottom_button
            return bottom_button(self, self.last_screenshot, ['丢弃'], band=Rect(240, 600, 1750, 960))
        return self.round_by_ocr_and_click(self.last_screenshot, '丢弃',
                                           success_wait=1, retry_wait=1)


def __debug():
    from zzz_od.context.zzz_context import ZContext
    ctx = ZContext()
    ctx.init_by_config()
    ctx.init_ocr()
    from onedragon.utils import debug_utils
    screen = debug_utils.get_debug_image('bag_full')
    op = FullInBag(ctx)
    op.round_by_ocr_and_click(screen, '丢弃')


if __name__ == '__main__':
    __debug()
