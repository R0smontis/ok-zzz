# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/application/coffee/coffee_app.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
import difflib
import time
from typing import ClassVar

import cv2
import numpy as np

from onedragon.base.config.config_item import get_config_item_from_enum
from onedragon.base.geometry.point import Point
from onedragon.base.geometry.rectangle import Rect
from src.navigation.menus import menu_words, pad_press
from onedragon.base.matcher.match_result import MatchResultList
from onedragon.base.operation.application import application_const
from onedragon.base.operation.operation_edge import node_from
from onedragon.base.operation.operation_node import operation_node
from onedragon.base.operation.operation_notify import NotifyTiming, node_notify
from onedragon.base.operation.operation_round_result import OperationRoundResult
from onedragon.utils import cv2_utils, str_utils
from onedragon.utils.i18_utils import gt
from zzz_od.application.charge_plan import charge_plan_const
from zzz_od.application.coffee import coffee_app_const
from zzz_od.application.coffee.coffee_config import (
    CoffeeConfig,
    CoffeeTransportPoint,
)
from zzz_od.application.zzz_application import ZApplication
from zzz_od.context.zzz_context import ZContext
from zzz_od.game_data.compendium import Coffee
from zzz_od.operation.back_to_normal_world import BackToNormalWorld
from zzz_od.operation.transport import Transport
from zzz_od.operation.turning.turn_compensation import AngleTurnCompensator
from zzz_od.operation.turning.turn_to_angle import turn_to_angle
from zzz_od.operation.wait_normal_world import WaitNormalWorld


class CoffeeApp(ZApplication):

    """咖啡店:每日免费点单 1 杯咖啡,恢复电量(体力)并获增益 buff。每日 1 次、04:00 重置。"""

    STATUS_EXTRA_COFFEE: ClassVar[str] = '不占用上限的咖啡'
    STATUS_WITHOUT_BENEFIT: ClassVar[str] = '没有增益的咖啡'

    def __init__(self, ctx: ZContext):
        """
        喝咖啡
        """
        ZApplication.__init__(
            self,
            ctx=ctx,
            app_id=coffee_app_const.APP_ID,
            op_name=coffee_app_const.APP_NAME,
        )

        self.config: CoffeeConfig = self.ctx.run_context.get_config(
            app_id=coffee_app_const.APP_ID,
            instance_idx=self.ctx.current_instance_idx,
            group_id=application_const.DEFAULT_GROUP_ID,
        )
        self.chosen_coffee: Coffee | None = None  # 选择的咖啡
        self.had_coffee_list: set[str] = set()  # 已经喝过的咖啡
        self.turn_compensator: AngleTurnCompensator = AngleTurnCompensator(self.ctx.controller)

    def handle_init(self) -> None:
        """
        执行前的初始化 由子类实现
        注意初始化要全面 方便一个指令重复使用
        """
        self.turn_compensator.reset()
        self.retried_transport: bool = False
        self.chosen_coffee = None
        self.had_coffee_list = set()
        self._pad_coffee_ordered = False
        self._pad_charge_confirmed = 0

    @node_from(from_name='等待咖啡店加载', success=False)
    @operation_node(name='传送', is_start_node=True)
    def transport(self) -> OperationRoundResult:
        if self.previous_node.name == '等待咖啡店加载':
            if self.retried_transport:
                return self.round_fail(status='等待咖啡店加载失败，重传送超限')
            self.retried_transport = True

        self.turn_compensator.clear_pending_sample()
        item = get_config_item_from_enum(CoffeeTransportPoint, self.config.transport_point)
        op = Transport(self.ctx, item.area_name, item.tp_name, wait_at_last=False)
        return self.round_by_op_result(op.execute())

    @node_from(from_name='传送')
    @operation_node(name='等待大世界加载', node_max_retry_times=60)
    def wait_world(self) -> OperationRoundResult:
        result = self.round_by_find_area(self.last_screenshot, '咖啡店', '点单')
        if result.is_success:
            return self.round_success(result.status)

        op = WaitNormalWorld(self.ctx, check_once=True)
        result = self.round_by_op_result(op.execute())
        if result.is_success:
            return self.round_success(result.status)

        return self.round_retry(status=result.status, wait=1)

    @node_from(from_name='等待大世界加载')
    @operation_node(name='移动交互', node_max_retry_times=10)
    def move_and_interact(self) -> OperationRoundResult:
        """
        六分街-咖啡店：转向正西后前移再交互
        澄辉坪-汀曼咖啡 / 布亚斯特城区-片刻闲：传送落点已正对入口，直接交互
        :return:
        """
        if self.config.transport_point == CoffeeTransportPoint.POINT_1.value.value:
            result = turn_to_angle(self, target_angle=180, turn_status='转向正西')
            if not result.is_success:
                return result
            self.ctx.controller.move_w(press=True, press_time=1, release=True)

        time.sleep(1) # 防止交互无效 issue #2405 #2395 #2328
        self.ctx.controller.interact(press=True, press_time=0.2, release=True)
        return self.round_success()

    @node_from(from_name='移动交互')
    @operation_node(name='等待咖啡店加载', node_max_retry_times=10)
    def wait_coffee_shop(self) -> OperationRoundResult:
        # 画面加载的时候，是滑动出现的，点单出现的时候，还未必能点击选中咖啡，因此要success_wait
        if self.config.transport_point == CoffeeTransportPoint.POINT_1.value.value:  #六分街-咖啡店
            return self.round_by_find_area(self.last_screenshot, '咖啡店', '点单',
                                           success_wait=1, retry_wait=1)

        result = self.round_by_find_area(self.last_screenshot, '咖啡店', '对话框标题-汀曼大师')
        if result.is_success:
            return self.round_success(status='对话点单', wait=3)  # 新版咖啡店
        return self.round_retry(status='等待对话框加载', wait=1)  # issue #2301

    @node_from(from_name='等待咖啡店加载', status='对话点单')
    @operation_node(name='对话选咖啡', node_max_retry_times=10)
    def dialog_choose_coffee(self) -> OperationRoundResult:
        """推进对话点单分支，直到出现咖啡选项或回到大世界"""
        # 标题会持续到对话结束，消失后按已喝过收尾
        result = self.round_by_find_area(self.last_screenshot, '咖啡店', '对话框标题-汀曼大师')
        if not result.is_success:
            return self.round_success(status='已喝过', wait=1)

        to_choose_list = self._get_coffee_to_choose()

        # 背景文字会干扰 OCR，不能根据区域内是否有文字判断状态，只尝试当天候选咖啡名
        area = self.ctx.screen_loader.get_area('咖啡店', '右侧选项区域')
        result = self.round_by_ocr_and_click_by_priority(to_choose_list, area=area)
        if result.is_success:
            self.chosen_coffee = self.ctx.compendium_service.name_2_coffee[result.status]
            self.had_coffee_list.add(result.status)
            if self.config.transport_point == CoffeeTransportPoint.POINT_3.value.value:
                return self.round_success(status='点单后跳过', wait=1)
            return self.round_success(status='已点单', wait=1)

        # 没有命中候选咖啡时说明当前是纯对话框，识别并点击标题推进，不依赖具体台词
        result = self.round_by_find_and_click_area(self.last_screenshot, '咖啡店', '对话框标题-汀曼大师')
        if result.is_success:
            return self.round_wait(status='继续对话', wait=1)
        return result

    @node_from(from_name='等待大世界加载', status='点单')
    @node_from(from_name='等待咖啡店加载')
    @node_from(from_name='电量确认', status=STATUS_EXTRA_COFFEE)
    @operation_node(name='选择咖啡')
    def choose_coffee(self) -> OperationRoundResult:
        to_choose_list = self._get_coffee_to_choose()
        if getattr(self.ctx.controller,'background_mode',False):
            footer=menu_words(self,Rect(1400,870,1910,970))
            titles=menu_words(self,Rect(1350,490,1740,630))
            if '点单' not in footer:
                return self.round_retry('未核验咖啡点单界面，未操作',wait=1)
            available=menu_words(self,Rect(180,830,1140,950))+titles
            target=next((name for name in to_choose_list if name in available),None)
            if target and target in titles:
                self.chosen_coffee=self.ctx.compendium_service.name_2_coffee[target]
                return self.round_success(f'已核验选中咖啡：{target}')
            if target is None:
                return self.round_fail('当前咖啡菜单没有可识别的候选咖啡')
            pad_press(self,'dpad_left')
            return self.round_retry(f'手柄查找咖啡：{target}，当前详情：{" / ".join(titles)}',wait=.8)

        # from onedragon.utils import debug_utils
        # screen = debug_utils.get_debug_image('424905412-5c9df2d3-186d-4be5-a610-865553fd6adb')
        area = self.ctx.screen_loader.get_area('咖啡店', '咖啡列表')
        part = cv2_utils.crop_image_only(self.last_screenshot, area.rect)
        mask = cv2.inRange(part,
                           np.array([220, 220, 220], dtype=np.uint8),
                           np.array([255, 255, 255], dtype=np.uint8))
        to_ocr = cv2.bitwise_and(part, part, mask=cv2_utils.dilate(mask, 5))

        ocr_result_map = self.ctx.ocr.run_ocr(to_ocr)
        ocr_result_list: list[str] = []
        mrl_list: list[MatchResultList] = []
        for ocr_result, mrl in ocr_result_map.items():
            ocr_result_list.append(ocr_result)
            mrl_list.append(mrl)

        for lcs_percent in [0.8, 0.6, 0.4]:
            for coffee_name in to_choose_list:
                results = difflib.get_close_matches(gt(coffee_name, 'game'), ocr_result_list, n=1)
                if results is None or len(results) == 0:
                    continue

                if not str_utils.find_by_lcs(gt(coffee_name, 'game'), results[0], percent=lcs_percent):
                    continue

                # 对于浓淡二字特殊判断
                if coffee_name.find('浓') > -1 and results[0].find('浓') == -1:
                    continue
                if results[0].find('浓') > -1 and coffee_name.find('浓') == -1:
                    continue

                if coffee_name.find('淡') > -1 and results[0].find('淡') == -1:
                    continue
                if results[0].find('淡') > -1 and coffee_name.find('淡') == -1:
                    continue

                mrl = mrl_list[ocr_result_list.index(results[0])]
                self.chosen_coffee = self.ctx.compendium_service.name_2_coffee[coffee_name]
                time.sleep(0.5)  # 暂停半秒以防点不到咖啡
                self.ctx.controller.click(mrl.max.center + area.left_top + Point(0, -50))
                return self.round_success(self.chosen_coffee.coffee_name, wait=0.5)

        return self.round_retry(status='没找到目标咖啡', wait=1)

    def _get_coffee_to_choose(self) -> list[str]:
        """获取候选咖啡，额外咖啡喝完后固定选择汀曼特调"""
        to_choose_list: list[str] = []
        for coffee in self.ctx.compendium_service.get_extra_coffee_list():
            if coffee.coffee_name in self.had_coffee_list:
                continue
            to_choose_list.append(coffee.coffee_name)

        tinman_coffee = '汀曼特调'
        if tinman_coffee not in self.had_coffee_list:
            to_choose_list.append(tinman_coffee)
        return to_choose_list

    @node_from(from_name='选择咖啡')
    @operation_node(name='点单')
    def order_coffee(self) -> OperationRoundResult:
        if getattr(self.ctx.controller,'background_mode',False):
            footer=menu_words(self,Rect(1400,870,1910,970))
            titles=menu_words(self,Rect(1350,490,1740,630))
            if (not self.chosen_coffee or self.chosen_coffee.coffee_name not in titles
                    or '点单' not in footer or not any('每日免费' in w for w in footer)):
                return self.round_retry('咖啡名称或每日免费点单提示未核验，未操作',wait=1)
            if self._pad_coffee_ordered:
                return self.round_fail('咖啡点单已发送，未重复点单')
            pad_press(self,'a');self._pad_coffee_ordered=True
            return self.round_success(wait=1)
        result = self.round_by_find_and_click_area(self.last_screenshot, '咖啡店', '点单')
        if result.is_success:
            self.had_coffee_list.add(self.chosen_coffee.coffee_name)
            if self.chosen_coffee.extra:
                return self.round_success(status=CoffeeApp.STATUS_EXTRA_COFFEE, wait=0.5)
            elif self.chosen_coffee.without_benefit:
                return self.round_success(status=CoffeeApp.STATUS_WITHOUT_BENEFIT, wait=0.5)
            else:
                return self.round_success(wait=3)
        return self.round_retry(wait=1)

    @node_from(from_name='点单', status=STATUS_EXTRA_COFFEE)
    @operation_node(name='不占用点单确认')
    def extra_order_confirm(self) -> OperationRoundResult:
        result = self.round_by_find_and_click_area(self.last_screenshot, '咖啡店', '对话框确认')
        if result.is_success:
            return self.round_success(result.status, wait=1)

        result = self.round_by_find_and_click_area(self.last_screenshot, '咖啡店', '不可贪杯确认')
        if result.is_success:
            return self.round_success(result.status, wait=1)

        return self.round_retry(wait=1)

    @node_from(from_name='点单')
    @node_from(from_name='不占用点单确认')
    @node_from(from_name='对话选咖啡', status='点单后跳过')  # 片刻闲首次点单后的动画可在此跳过
    @operation_node(name='点单后跳过',node_max_retry_times=60,timeout_seconds=90)
    def skip_after_order(self) -> OperationRoundResult:
        result = self.round_by_find_area(self.last_screenshot, '咖啡店', '电量确认')
        if result.is_success:
            return self.round_success(result.status)

        if getattr(self.ctx.controller,'background_mode',False):
            result=self.round_by_find_area(self.last_screenshot,'咖啡店','不可贪杯确认')
            if result.is_success:
                pad_press(self,'a')
                return self.round_success(result.status,wait=1)
            return self.round_retry('等待咖啡制作和实际电量确认，未重复点单',wait=1)

        # 这个点击很怪 需要多点几次
        # 原因是绝区零逆天按钮, 需要先拖鼠标, 让鼠标显形才能点击
        result = self.round_by_find_area(self.last_screenshot, '咖啡店', '点单后跳过')
        if result.is_success:
            area = self.ctx.screen_loader.get_area('咖啡店', '点单后跳过')
            self.ctx.controller.drag_to(start=area.left_top, end=area.center, duration=0.2)
            self.ctx.controller.click()
            return self.round_success(result.status, wait=1)

        result = self.round_by_find_and_click_area(self.last_screenshot, '咖啡店', '不可贪杯确认')
        if result.is_success:
            return self.round_success(result.status, wait=1)

        return self.round_retry(result.status, wait=1)

    @node_from(from_name='点单后跳过')
    @node_from(from_name='对话选咖啡', status='已点单')
    @node_notify(when=NotifyTiming.CURRENT_SUCCESS)
    @operation_node(name='电量确认')
    def charge_confirm(self) -> OperationRoundResult:
        if getattr(self.ctx.controller,'background_mode',False):
            popup=self.round_by_find_area(self.last_screenshot,'咖啡店','电量确认')
            if popup.is_success:
                if self._pad_charge_confirmed>=3:
                    return self.round_fail('电量确认未生效')
                pad_press(self,'a');self._pad_charge_confirmed+=1
                return self.round_retry('已核验电量奖励，等待确认关闭',wait=1)
            if self._pad_charge_confirmed and (self.round_by_find_area(self.last_screenshot,'咖啡店','点单').is_success
                    or self.check_and_update_current_screen()=='大世界-普通'):
                self.had_coffee_list.add(self.chosen_coffee.coffee_name)
                return self.round_success(CoffeeApp.STATUS_EXTRA_COFFEE if self.chosen_coffee.extra else None)
            return self.round_retry('未核验电量奖励确认结果',wait=1)
        result = self.round_by_find_and_click_area(self.last_screenshot, '咖啡店', '电量确认')

        if result.is_success:
            if self.chosen_coffee.extra:
                return self.round_success(CoffeeApp.STATUS_EXTRA_COFFEE, wait=1)
            else:
                return self.round_success(wait=1)

        return self.round_retry(wait=1)

    @node_from(from_name='不占用点单确认', status='不可贪杯确认')  # 已经喝过了
    @node_from(from_name='点单后跳过', status='不可贪杯确认')  # 已经喝过了
    @node_from(from_name='对话选咖啡', status='已喝过')  # 已经喝过了
    @node_from(from_name='电量确认')
    @operation_node(name='返回大世界')
    def back_to_world(self) -> OperationRoundResult:
        op = BackToNormalWorld(self.ctx)
        return self.round_by_op_result(op.execute())

    @node_from(from_name='返回大世界')
    @operation_node(name='结束后运行体力计划')
    def charge_plan_afterwards(self) -> OperationRoundResult:
        if self.config.run_charge_plan_afterwards:
            op = self.ctx.run_context.get_application(
                app_id=charge_plan_const.APP_ID,
                instance_idx=self.ctx.current_instance_idx,
                group_id=application_const.DEFAULT_GROUP_ID,
            )
            return self.round_by_op_result(op.execute())
        return self.round_success('无需运行')


def __debug():
    ctx = ZContext()
    ctx.init()
    ctx.run_context.start_running()
    app = CoffeeApp(ctx)
    app.chosen_coffee = ctx.compendium_service.name_2_coffee['汀曼特调']
    # app.had_coffee_list.add('沙罗特调（浓）')
    # app.choose_coffee()
    app.execute()


if __name__ == '__main__':
    __debug()
