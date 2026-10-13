# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/hollow_zero/event/remove_corruption.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from onedragon.base.operation.operation_node import operation_node
from onedragon.base.operation.operation_round_result import OperationRoundResult
from onedragon.utils.i18_utils import gt
from zzz_od.context.zzz_context import ZContext
from zzz_od.operation.zzz_operation import ZOperation


class RemoveCorruption(ZOperation):

    def __init__(self, ctx: ZContext):
        """
        在选择鸣徽的画面了 选择一个
        :param ctx:
        """
        ZOperation.__init__(
            self, ctx,
            op_name=gt('清除侵蚀症状', 'game')
        )

    @operation_node(name='选择', is_start_node=True)
    def choose_one(self) -> OperationRoundResult:
        if getattr(self.ctx.controller, 'background_mode', False):
            from src.navigation.hollow_events import remove_corruption
            return remove_corruption(self, self.last_screenshot)
        area = self.ctx.screen_loader.get_area('零号空洞-事件', '底部-清除列表')
        return self.round_by_ocr_and_click(self.last_screenshot, '清除', area=area,
                                           color_range=[(240, 240, 240), (255, 255, 255)],
                                           crop_first=False,
                                           success_wait=1, retry_wait=1)
