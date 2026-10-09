# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/application/hollow_zero/lost_void/operation/interact/lost_void_lottery.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from typing import ClassVar
import re

from onedragon.base.operation.operation_edge import node_from
from onedragon.base.operation.operation_node import operation_node
from onedragon.base.operation.operation_round_result import OperationRoundResult
from onedragon.base.geometry.rectangle import Rect
from onedragon.utils import str_utils
from zzz_od.application.hollow_zero.lost_void.operation.interact.lost_void_choose_common import (
    LostVoidChooseCommon,
)
from zzz_od.context.zzz_context import ZContext
from zzz_od.operation.zzz_operation import ZOperation
from zzz_od.application.hollow_zero.lost_void.mission_screen import common_choice, lottery_counts
from src.controls.gamepad import press as pad


class LostVoidLottery(ZOperation):

    STATUS_NO_TIMES_LEFT: ClassVar[str] = '无剩余次数'
    STATUS_CONTINUE: ClassVar[str] = '继续抽奖'

    def __init__(self, ctx: ZContext):
        ZOperation.__init__(self, ctx, op_name='迷失之地-抽奖机')

    @node_from(from_name='点击后确定', status=STATUS_CONTINUE)
    @operation_node(name='点击开始', is_start_node=True)
    def click_start(self) -> OperationRoundResult:
        if getattr(self.ctx.controller, 'background_mode', False):
            matches = self.ctx.ocr_service.get_ocr_result_list(image=self.last_screenshot,
                rect=Rect(804,885,1120,985))
            text = ''.join(str(m.data).replace(' ', '') for m in matches)
            count = re.search(r'(\d+)\s*/\s*(\d+)', text)
            if count is None:
                return self.round_retry('未识别抽奖次数，未开始或退出', wait=.5)
            remaining, total = map(int, count.groups())
            if total <= 0 or remaining > total:
                return self.round_retry('抽奖次数无效，未操作', wait=.5)
            if remaining == 0:
                return self.round_success(self.STATUS_NO_TIMES_LEFT)
            requests = getattr(self, '_start_requests', 0) + 1 if getattr(self, '_last_count', None) == remaining else 1
            if requests > 3:
                return self.round_fail('抽奖开始未生效，次数未减少')
            self._last_count, self._start_requests = remaining, requests
            self._pad('confirm')
            return self.round_success('手柄开始抽奖，等待结果', wait=4)
        # 识别剩余次数
        area = self.ctx.screen_loader.get_area('迷失之地-抽奖机', '文本-剩余次数')

        ocr_result_map = self.ctx.ocr.crop_and_run_ocr(self.last_screenshot, area.rect)
        if len(ocr_result_map) == 0:
            return self.round_success(LostVoidLottery.STATUS_NO_TIMES_LEFT)

        is_valid = False
        for ocr_result in ocr_result_map:
            digit = str_utils.get_positive_digits(ocr_result, err=0)
            if digit is not None and digit > 0:
                is_valid = True
                break

        if not is_valid:
            return self.round_success(LostVoidLottery.STATUS_NO_TIMES_LEFT)

        return self.round_by_find_and_click_area(self.last_screenshot, '迷失之地-抽奖机', '按钮-开始',
                                                 success_wait=4, retry_wait=1)

    @node_from(from_name='点击开始')
    @operation_node(name='点击后确定')
    def confirm_after_click(self) -> OperationRoundResult:
        screen_name = self.check_and_update_current_screen(self.last_screenshot)
        interact_op = None

        if screen_name == '迷失之地-通用选择' or common_choice(self.ctx, self.last_screenshot):
            interact_op = LostVoidChooseCommon(self.ctx)
            interact_op.return_screen_name = '迷失之地-抽奖机'
        elif screen_name == '迷失之地-抽奖机' or lottery_counts(self.ctx, self.last_screenshot) is not None:
            return self.round_success(LostVoidLottery.STATUS_CONTINUE)

        if interact_op is not None:
            op_result = interact_op.execute()
            if op_result.success:
                return self.round_wait(op_result.status, wait=1)
            else:
                return self.round_fail(op_result.status)

        if getattr(self.ctx.controller, 'background_mode', False):
            result = self.round_by_find_area(self.last_screenshot, '迷失之地-抽奖机', '按钮-获取确定')
            if result.is_success:
                self._pad('confirm')
                return self.round_wait('手柄确认抽奖奖励，等待画面变化', wait=1)
            return self.round_retry('未能识别抽奖结果，未操作', wait=1)
        result = self.round_by_find_and_click_area(self.last_screenshot, '迷失之地-抽奖机', '按钮-获取确定')
        if result.is_success:
            return self.round_wait(result.status, wait=1)

        return self.round_retry('未能识别当前画面', wait=1)

    @node_from(from_name='点击开始', status=STATUS_NO_TIMES_LEFT)
    @node_from(from_name='点击后确定', success=False)
    @operation_node(name='返回大世界')
    def back_to_world(self) -> OperationRoundResult:
        in_world = self.ctx.lost_void.in_normal_world(self.last_screenshot)
        if not in_world:
            if getattr(self.ctx.controller, 'background_mode', False):
                requests = getattr(self, '_back_requests', 0)
                if requests >= 3:
                    return self.round_fail('抽奖菜单退出未生效')
                self._pad('back')
                self._back_requests = requests + 1
                return self.round_wait('手柄退出抽奖机，等待大世界', wait=1)
            result = self.round_by_find_and_click_area(self.last_screenshot, '迷失之地-抽奖机', '按钮-返回')
            return self.round_retry(result.status, wait=1)

        return self.round_success()

    def _pad(self, action):
        pad(self.ctx, 'b' if action == 'back' else 'a')



def __debug():
    ctx = ZContext()
    ctx.init_by_config()
    ctx.init_ocr()
    ctx.lost_void.init_before_run()
    ctx.run_context.start_running()

    op = LostVoidLottery(ctx)
    op.execute()


if __name__ == '__main__':
    __debug()
