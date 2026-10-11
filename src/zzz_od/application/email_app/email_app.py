# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/application/email_app/email_app.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from onedragon.base.operation.operation_edge import node_from
from onedragon.base.operation.operation_node import operation_node
from onedragon.base.operation.operation_notify import node_notify, NotifyTiming
from onedragon.base.operation.operation_round_result import OperationRoundResult
from onedragon.base.geometry.rectangle import Rect
from src.controls.gamepad import press as pad
from zzz_od.application.email_app import email_app_const
from zzz_od.application.zzz_application import ZApplication
from zzz_od.context.zzz_context import ZContext
from zzz_od.operation.back_to_normal_world import BackToNormalWorld


class EmailApp(ZApplication):

    """邮件:自动领取游戏内未读邮件奖励(菲林/材料)。无消耗。"""

    def __init__(self, ctx: ZContext):
        """
        每天自动接收邮件奖励
        """
        ZApplication.__init__(
            self,
            ctx=ctx,
            app_id=email_app_const.APP_ID,
            op_name=email_app_const.APP_NAME,
        )

    def handle_init(self) -> None:
        """
        执行前的初始化 由子类实现
        注意初始化要全面 方便一个指令重复使用
        """
        pass

    @operation_node(name='打开邮件', is_start_node=True)
    def goto_email(self) -> OperationRoundResult:
        return self.round_by_goto_screen(screen_name='邮件')

    @node_from(from_name='打开邮件')
    @node_notify(when=NotifyTiming.CURRENT_SUCCESS)
    @operation_node(name='全部领取')
    def click_get_all(self) -> OperationRoundResult:
        """
        邮件画面 点击全部领取
        就算时灰色的也能识别到
        :return:
        """
        if getattr(self.ctx.controller, 'background_mode', False):
            # The mail page ignores window-message clicks; X is 全部领取 (also when greyed out: nothing happens).
            result = self.round_by_find_area(self.last_screenshot, '邮件', '全部领取')
            if not result.is_success:
                return self.round_retry(result.status, wait=1)
            pad(self.ctx, 'x')
            return self.round_success(result.status, wait=1)
        return self.round_by_find_and_click_area(self.last_screenshot, '邮件', '全部领取', success_wait=1, retry_wait=1)

    @node_from(from_name='全部领取')
    @operation_node(name='确认')
    def click_confirm(self) -> OperationRoundResult:
        """
        邮件画面 领取后点击确认
        :return:
        """
        target_word_list = [
            '确认',  # 正常领取的情况
            '确定',  # 某种物品爆满了
        ]
        if getattr(self.ctx.controller, 'background_mode', False):
            # Only the reward popup has these words; it sits in the middle of the screen.
            rows = self.ctx.ocr_service.get_ocr_result_list(image=self.last_screenshot, rect=Rect(560, 300, 1360, 860))
            words = [str(r.data).strip() for r in rows] if isinstance(rows, (list, tuple)) else []
            if not any(word in target_word_list for word in words):
                return self.round_retry('未匹配到目标文本', wait=1)
            pad(self.ctx, 'a')
            return self.round_success('手柄确认领取', wait=1)
        return self.round_by_ocr_and_click_by_priority(
            target_cn_list=target_word_list,
            success_wait=1,
            retry_wait=1,
        )

    @node_from(from_name='确认')  # 确认之后返回
    @node_from(from_name='确认', success=False)  # 没有确认 其实就是没有东西能领取 也返回
    @node_from(from_name='全部领取', success=False)  # 没找到全部领取的话 也返回
    @operation_node(name='返回菜单')
    def back_to_menu(self) -> OperationRoundResult:
        """
        返回菜单
        领取后的确认按钮可以不按 直接点击外层也可以返回
        :return:
        """
        if getattr(self.ctx.controller, 'background_mode', False):
            pad(self.ctx, 'b')
            return self.round_success('手柄返回菜单', wait=1)
        return self.round_by_find_and_click_area(self.last_screenshot, '菜单', '返回', success_wait=1, retry_wait=1)

    @node_from(from_name='返回菜单')
    @node_from(from_name='返回菜单', success=False)
    @operation_node(name='返回大世界')
    def back_to_world(self) -> OperationRoundResult:
        op = BackToNormalWorld(self.ctx)
        return self.round_by_op_result(op.execute())
