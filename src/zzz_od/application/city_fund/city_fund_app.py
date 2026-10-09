# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/application/city_fund/city_fund_app.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from onedragon.base.operation.operation_edge import node_from
from onedragon.base.operation.operation_node import operation_node
from onedragon.base.operation.operation_notify import node_notify, NotifyTiming
from onedragon.base.operation.operation_round_result import OperationRoundResult
from zzz_od.application.city_fund import city_fund_const
from zzz_od.application.zzz_application import ZApplication
from zzz_od.context.zzz_context import ZContext
from zzz_od.operation.back_to_normal_world import BackToNormalWorld
from zzz_od.operation.goto.goto_menu import GotoMenu
from onedragon.base.geometry.rectangle import Rect
from src.navigation.menus import menu_words, main_menu_target, selected_tab, pad_press


class CityFundApp(ZApplication):

    """丽都城募:领取成长任务/等级回馈奖励(随版本周期开放,含每日刷新任务)。无消耗。"""

    def __init__(self, ctx: ZContext):
        """
        领取大月卡
        """
        ZApplication.__init__(
            self,
            ctx=ctx,
            app_id=city_fund_const.APP_ID,
            op_name=city_fund_const.APP_NAME,
        )

    def handle_init(self):
        self._pad_menu_steps=0
        self._pad_menu_confirms=0
        self._pad_task_claims=0
        self._pad_level_claims=0

    @operation_node(name='打开菜单', is_start_node=True)
    def open_menu(self) -> OperationRoundResult:
        op = GotoMenu(self.ctx)
        return self.round_by_op_result(op.execute())

    @node_from(from_name='打开菜单')
    @operation_node(name='点击丽都城募')
    def click_fund(self) -> OperationRoundResult:
        if getattr(self.ctx.controller,'background_mode',False):
            words=menu_words(self,Rect(1100,15,1850,90))
            if '等级回馈' in words and '成长任务' in words:
                return self.round_success('已核验丽都城募界面')
            return main_menu_target(self,'丽都城募')
        area = self.ctx.screen_loader.get_area('菜单', '底部列表')
        return self.round_by_ocr_and_click(self.last_screenshot, '丽都城募', area=area,
                                           success_wait=1, retry_wait=1)

    @node_from(from_name='点击丽都城募')
    @node_from(from_name='点击成长任务', status='按钮-确认')
    @operation_node(name='点击成长任务')
    def click_task(self) -> OperationRoundResult:
        if getattr(self.ctx.controller,'background_mode',False):
            current=selected_tab(self,Rect(1100,15,1850,90),('等级回馈','成长任务','城募赠礼'))
            if current=='成长任务':
                return self.round_success('已核验成长任务页签')
            if current in ('等级回馈','城募赠礼'):
                pad_press(self,'rb' if current=='等级回馈' else 'lb')
                return self.round_retry('手柄切换成长任务，等待实际页签',wait=1)
            return self.round_retry('未核验城募页签，未操作',wait=1)
        result = self.round_by_find_and_click_area(self.last_screenshot, '丽都城募', '开启丽都城募')
        if result.is_success:
            return self.round_wait(status=result.status, wait=1)

        result = self.round_by_find_and_click_area(self.last_screenshot, '丽都城募', '按钮-确认')
        if result.is_success:
            return self.round_success(status=result.status, wait=1)

        return self.round_by_find_and_click_area(self.last_screenshot, '丽都城募', '成长任务',
                                                 success_wait=1, retry_wait=1)

    @node_from(from_name='点击成长任务')
    @operation_node(name='任务全部领取')
    def click_task_claim(self) -> OperationRoundResult:
        if getattr(self.ctx.controller,'background_mode',False):
            words=menu_words(self,Rect(500,200,1850,965))
            if '确认' in words and any('获得' in word for word in words):
                pad_press(self,'a')
                return self.round_retry('确认城募任务奖励，等待实际任务页',wait=1)
            if selected_tab(self,Rect(1100,15,1850,90),('等级回馈','成长任务','城募赠礼'))!='成长任务':
                return self.round_retry('未核验成长任务页，未操作',wait=1)
            if '领取' not in words:
                return self.round_success('已核验当前任务无可领取奖励')
            if '全部领取' not in menu_words(self,Rect(1550,980,1900,1060)):
                return self.round_retry('未核验全部领取提示，未操作',wait=1)
            if self._pad_task_claims>=3:
                return self.round_fail('城募任务领取后状态未改变')
            pad_press(self,'x');self._pad_task_claims+=1
            return self.round_retry('手柄领取城募任务，等待可领取状态消失',wait=1)
        return self.round_by_find_and_click_area(self.last_screenshot, '丽都城募', '任务-全部领取',
                                                 success_wait=1, retry_wait=1)

    @node_from(from_name='任务全部领取')
    @operation_node(name='点击等级回馈')
    def click_level(self) -> OperationRoundResult:
        if getattr(self.ctx.controller,'background_mode',False):
            current=selected_tab(self,Rect(1100,15,1850,90),('等级回馈','成长任务','城募赠礼'))
            if current=='等级回馈':
                return self.round_success('已核验等级回馈页签')
            if current in ('成长任务','城募赠礼'):
                pad_press(self,'lb')
                return self.round_retry('手柄切换等级回馈，等待实际页签',wait=1)
            return self.round_retry('未核验城募页签，未操作',wait=1)
        return self.round_by_find_and_click_area(self.last_screenshot, '丽都城募', '等级回馈',
                                                 success_wait=1, retry_wait=1)

    @node_from(from_name='点击等级回馈')
    @node_notify(when=NotifyTiming.CURRENT_SUCCESS)
    @operation_node(name='等级全部领取')
    def click_level_claim(self) -> OperationRoundResult:
        if getattr(self.ctx.controller,'background_mode',False):
            words=menu_words(self,Rect(500,200,1850,965))
            if '确认' in words and any('获得' in word for word in words):
                pad_press(self,'a')
                return self.round_retry('确认城募等级奖励，等待实际等级页',wait=1)
            if selected_tab(self,Rect(1100,15,1850,90),('等级回馈','成长任务','城募赠礼'))!='等级回馈':
                return self.round_retry('未核验等级回馈页，未操作',wait=1)
            if '全部领取' not in menu_words(self,Rect(1100,980,1900,1060)):
                return self.round_success('已核验等级回馈页无可领取奖励')
            if self._pad_level_claims>=3:
                return self.round_fail('城募等级领取后状态未改变')
            pad_press(self,'x');self._pad_level_claims+=1
            return self.round_retry('手柄领取城募等级奖励，等待实际结果',wait=1)
        # 2.6版本更新，等级回馈领取，已领取过全部领取按钮是会消失的
        for screen_name, area_name in [
            ('丽都城募', '等级-全部领取'),
            ('丽都城募', '按钮-确认'),
        ]:
            result = self.round_by_find_and_click_area(self.last_screenshot, screen_name, area_name, success_wait=1)
            if result.is_success:
                return self.round_retry(status=result.status, wait=1)

        return self.round_success()  # 两个按钮都未找到，说明已领取完毕

    @node_from(from_name='等级全部领取')
    @node_from(from_name='等级全部领取', success=False)
    @operation_node(name='返回大世界')
    def back_to_world(self) -> OperationRoundResult:
        op = BackToNormalWorld(self.ctx)
        return self.round_by_op_result(op.execute())


def __debug():
    ctx = ZContext()
    ctx.init()
    app = CityFundApp(ctx)
    app.execute()


if __name__ == '__main__':
    __debug()
