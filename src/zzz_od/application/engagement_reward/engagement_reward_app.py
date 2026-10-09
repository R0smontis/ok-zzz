# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/application/engagement_reward/engagement_reward_app.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from typing import ClassVar
from onedragon.base.geometry.rectangle import Rect
from src.navigation.menus import menu_words, pad_press, compendium_tab

from onedragon.base.operation.operation_edge import node_from
from onedragon.base.operation.operation_node import operation_node
from onedragon.base.operation.operation_notify import NotifyTiming, node_notify
from onedragon.base.operation.operation_round_result import OperationRoundResult
from onedragon.utils import cv2_utils, str_utils
from zzz_od.application.engagement_reward import engagement_reward_const
from zzz_od.application.zzz_application import ZApplication
from zzz_od.context.zzz_context import ZContext
from zzz_od.operation.back_to_normal_world import BackToNormalWorld


class EngagementRewardApp(ZApplication):

    """活跃度奖励:领取快捷手册-日常的活跃度奖励。日刷新、无消耗。"""

    STATUS_NO_REWARD: ClassVar[str] = '无奖励可领取'
    STATUS_CLAIM_SUCCESS: ClassVar[str] = '日常奖励领取成功'

    def __init__(self, ctx: ZContext):
        """
        领取活跃度奖励
        """
        ZApplication.__init__(
            self,
            ctx=ctx,
            app_id=engagement_reward_const.APP_ID,
            op_name=engagement_reward_const.APP_NAME,
        )
        self.timeout_seconds = 120

    def handle_init(self):
        self._pad_claims=0
        self._pad_reward_seen=False

    @operation_node(name='返回大世界', is_start_node=True)
    def back_at_first(self) -> OperationRoundResult:
        op = BackToNormalWorld(self.ctx)
        return self.round_by_op_result(op.execute())

    @node_from(from_name='返回大世界')
    @operation_node(name='快捷手册-日常')
    def goto_compendium_daily(self) -> OperationRoundResult:
        return self.round_by_goto_screen(screen_name='快捷手册-日常')

    @node_from(from_name='快捷手册-日常')
    @node_from(from_name='查看奖励结果', success=False)
    @operation_node(name='点击奖励')
    def click_reward(self) -> OperationRoundResult:
        if getattr(self.ctx.controller, 'background_mode', False):
            tab=compendium_tab(self,self.last_screenshot,'快捷手册-日常')
            if not tab.is_success:
                return tab
            words=menu_words(self,Rect(750,970,1230,1060))
            if '活跃奖励' in words:
                return self.round_success(self.STATUS_NO_REWARD)
            if '领取奖励' not in words:
                return self.round_retry('未核验活跃度领取提示，未操作',wait=1)
            if self._pad_claims>=4:
                return self.round_fail('活跃度奖励领取未生效，已停止重复领取')
            pad_press(self,'x');self._pad_claims+=1
            return self.round_success('手柄领取活跃度奖励，等待结果',wait=1)
        return self.round_by_find_and_click_area(self.last_screenshot, '快捷手册', '今日最大活跃度', success_wait=1, retry_wait=1)

    @node_from(from_name='点击奖励')
    @operation_node(name='查看奖励结果')
    def check_reward(self) -> OperationRoundResult:
        if getattr(self.ctx.controller, 'background_mode', False):
            words=menu_words(self,Rect(680,350,1240,860))
            if '获得' in words and '确认' in words:
                self._pad_reward_seen=True
                pad_press(self,'a')
                return self.round_retry('已核验获得奖励，确认后等待返回日常页',wait=1)
            tab=compendium_tab(self,self.last_screenshot,'快捷手册-日常')
            footer=menu_words(self,Rect(750,970,1230,1060))
            if tab.is_success and '活跃奖励' in footer:
                return self.round_success(self.STATUS_CLAIM_SUCCESS if self._pad_reward_seen else self.STATUS_NO_REWARD)
            return self.round_retry('等待实际活跃度奖励结果',wait=1)
        result = self.round_by_find_and_click_area(self.last_screenshot, '快捷手册', '活跃度奖励-确认', success_wait=1, retry_wait=1)
        if result.is_success:
            return self.round_success('日常奖励领取成功')

        result = self.round_by_find_area(self.last_screenshot, '快捷手册', '活跃度奖励-奖励预览')
        if result.is_success:
            result = self.round_by_find_and_click_area(self.last_screenshot, '画面-通用', '关闭', success_wait=1, retry_wait=1)
            if result.is_success:
                return self.round_success('日常奖励已领取或活跃度未满')

        return self.round_fail('未找到确认按钮或奖励预览')

    @node_from(from_name='查看奖励结果')
    @node_notify(when=NotifyTiming.CURRENT_DONE, detail=True)
    @operation_node(name='识别活跃度')
    def check_engagement(self) -> OperationRoundResult:
        result = self.round_by_find_area(self.last_screenshot, '快捷手册', '活跃度奖励-4')
        return self.round_success('活跃度已满') if result.is_success else self.round_fail('活跃度未满')

    @node_from(from_name='识别活跃度')
    @node_from(from_name='识别活跃度', success=False)
    @operation_node(name='完成后返回大世界')
    def back_afterwards(self) -> OperationRoundResult:
        op = BackToNormalWorld(self.ctx)
        result=op.execute()
        if not result.success:
            return self.round_by_op_result(result)
        return self.round_success(self.previous_node.status) if self.previous_node.is_success else self.round_fail(self.previous_node.status)


def __debug():
    ctx = ZContext()
    ctx.init()
    ctx.run_context.start_running()
    op = EngagementRewardApp(ctx)
    op.execute()


if __name__ == '__main__':
    __debug()
