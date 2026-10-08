# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/application/hollow_zero/lost_void/operation/interact/lost_void_route_change.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from onedragon.base.operation.operation_node import operation_node
from onedragon.base.operation.operation_round_result import OperationRoundResult
from zzz_od.context.zzz_context import ZContext
from zzz_od.operation.zzz_operation import ZOperation
from zzz_od.application.hollow_zero.lost_void.mission_screen import dialogue_visible


class LostVoidRouteChange(ZOperation):

    def __init__(self, ctx: ZContext):
        ZOperation.__init__(self, ctx, op_name='迷失之地-路径迭换')
        self._back_requested = False

    @operation_node(name='返回', is_start_node=True, node_max_retry_times=5, timeout_seconds=20)
    def back_to_world(self) -> OperationRoundResult:
        in_world = self.ctx.lost_void.in_normal_world(self.last_screenshot)
        if getattr(self.ctx.controller, 'background_mode', False) and dialogue_visible(self.ctx, self.last_screenshot):
            return self.round_success('路径菜单已关闭，继续 NPC 对话')
        if not in_world:
            if getattr(self.ctx.controller, 'background_mode', False):
                found = self.round_by_find_area(self.last_screenshot, '迷失之地-路径迭换', '按钮-图例详情')
                if not found.is_success:
                    if getattr(self, '_back_requested', False):
                        return self.round_success('已核验路径菜单关闭')
                    return self.round_retry('等待路径迭换菜单，未操作', wait=.5)
                if getattr(self, '_back_requested', False):
                    return self.round_wait('等待路径菜单关闭', wait=.5)
                ds4=self.ctx.game_config.background_gamepad_type == 'ds4'
                self.ctx.controller.btn_press('ds4_circle' if ds4 else 'xbox_b', press_time=.12)
                self._back_requested = True
                return self.round_wait('返回路径菜单，等待画面确认', wait=.5)
            result = self.round_by_find_and_click_area(self.last_screenshot, '迷失之地-路径迭换', '按钮-返回')
            return self.round_retry(result.status, wait=1)

        return self.round_success()
