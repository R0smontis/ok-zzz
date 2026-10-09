# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/application/hollow_zero/lost_void/operation/interact/lost_void_bangboo_store.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
import time
import re

import cv2
from cv2.typing import MatLike

from onedragon.base.geometry.point import Point
from onedragon.base.geometry.rectangle import Rect
from onedragon.base.operation.operation_edge import node_from
from onedragon.base.operation.operation_node import operation_node
from onedragon.base.operation.operation_round_result import OperationRoundResult
from onedragon.utils import cv2_utils, str_utils
from onedragon.utils.i18_utils import gt
from onedragon.utils.log_utils import log
from zzz_od.application.hollow_zero.lost_void.context.lost_void_artifact import (
    LostVoidArtifact,
)
from zzz_od.application.hollow_zero.lost_void.operation.interact.lost_void_artifact_pos import (
    LostVoidArtifactPos,
)
from zzz_od.application.hollow_zero.lost_void.operation.interact.lost_void_choose_common import (
    LostVoidChooseCommon,
)
from zzz_od.context.zzz_context import ZContext
from zzz_od.application.hollow_zero.lost_void.mission_screen import common_choice
from zzz_od.operation.zzz_operation import ZOperation
from src.controls.gamepad import press as pad


class LostVoidBangbooStore(ZOperation):

    def __init__(self, ctx: ZContext):
        ZOperation.__init__(self, ctx, op_name='迷失之地-邦布商店')

        self.refresh_times: int = 0  # 刷新次数
        self.store_type: str = '标识-金币'  # 商店类型
        self.slide_to_right: bool = False  # 滑动到右侧看更多的商品

    @operation_node(name='识别商店类型', is_start_node=True)
    def check_store_type(self) -> OperationRoundResult:
        result = self.round_by_find_area(self.last_screenshot, '迷失之地-邦布商店', '标识-金币')
        if result.is_success:
            self.store_type = result.status
            return self.round_success(result.status)

        result = self.round_by_find_area(self.last_screenshot, '迷失之地-邦布商店', '标识-血量')
        if result.is_success:
            self.store_type = result.status
            return self.round_success(result.status)

        return self.round_retry(status='未识别商店类型', wait=1)

    @node_from(from_name='识别商店类型')
    @node_from(from_name='识别商店类型', success=False)
    @node_from(from_name='确认后处理')
    @operation_node(name='购买藏品', timeout_seconds=120)
    def buy_artifact_gold(self) -> OperationRoundResult:
        if getattr(self.ctx.controller, 'background_mode', False):
            return self._buy_with_pad()
        # 移动鼠标到空的区域 防止阻碍识别
        area = self.ctx.screen_loader.get_area('迷失之地-邦布商店', '文本-详情')
        self.ctx.controller.mouse_move(area.center + Point(0, 100))
        time.sleep(0.1)

        if self.store_type == '标识-血量':
            if not self.ctx.lost_void.challenge_config.store_blood:
                return self.round_fail('不使用血量购买')

            if not self.check_min_blood_valid(self.last_screenshot):
                return self.round_fail('血量低于设定最小值')
        elif self.store_type == '标识-金币':
            if not self.ctx.lost_void.challenge_config.store_gold:
                return self.round_fail('不使用金币购买')

        # 按刷新之后的确认
        result = self.round_by_find_and_click_area(self.last_screenshot, '迷失之地-邦布商店', '按钮-刷新-确认')
        if result.is_success:
            self.refresh_times += 1
            return self.round_wait(result.status, wait=1)

        screen_name = self.check_and_update_current_screen()
        if screen_name != '迷失之地-邦布商店':
            # 进入本指令之前 有可能识别错画面
            # 处理小概率可能会漏掉的武备升级环节
            if screen_name == '迷失之地-通用选择':
                op = LostVoidChooseCommon(self.ctx)
                op_result = op.execute()
                if op_result.success:
                    return self.round_wait(status='武备升级', wait=1)
                else:
                    return self.round_retry(status='武备升级失败', wait=1)
            return self.round_retry(status=f'当前画面 {screen_name}', wait=1)

        all_artifact_list, art_list = self.get_artifact_pos(self.last_screenshot)
        if len(art_list) == 0:
            if len(all_artifact_list) >= 4:
                return self.round_fail('已识别藏品但无可购买项')
            if not self.slide_to_right:
                start = Point(self.ctx.controller.standard_width // 2, self.ctx.controller.standard_height // 2)
                end = start + Point(-400, 0)
                self.ctx.controller.drag_to(start=start, end=end)
                self.slide_to_right = True
                return self.round_wait(status='向右滑动')
            return self.round_retry(status='未识别可购买藏品', wait=1)

        priority_list: list[LostVoidArtifactPos] = self.ctx.lost_void.get_artifact_by_priority(
            art_list, 1,
            consider_priority_1=True, consider_priority_2=self.refresh_times > self.ctx.lost_void.challenge_config.buy_only_priority_1,
            consider_not_in_priority=self.refresh_times > self.ctx.lost_void.challenge_config.buy_only_priority_2,
            consider_priority_new=self.ctx.lost_void.challenge_config.artifact_priority_new
        )

        if len(priority_list) == 0:
            if not self.slide_to_right:
                start = Point(self.ctx.controller.standard_width // 2, self.ctx.controller.standard_height // 2)
                end = start + Point(-400, 0)
                self.ctx.controller.drag_to(start=start, end=end)
                self.slide_to_right = True
                return self.round_wait(status='向右滑动')

            result = self.round_by_find_and_click_area(self.last_screenshot, '迷失之地-邦布商店', '按钮-刷新-可用')
            if result.is_success:
                self.slide_to_right = False  # 刷新后 重置滑动
                return self.round_wait(result.status, wait=1)

            # 不可以刷新了 就不管优先级都买了
            priority_list = self.ctx.lost_void.get_artifact_by_priority(art_list, len(art_list))

        if len(priority_list) == 0:
            return self.round_retry(status='按优先级选择藏品失败', wait=1)

        target: LostVoidArtifactPos = priority_list[0]
        target_item: LostVoidArtifact = target.artifact

        self.ctx.controller.click(target.store_buy_rect.center)
        return self.round_success(target_item.name, wait=1)

    def _pad(self, action):
        pad(self.ctx, {'confirm': 'a', 'back': 'b'}.get(action, 'dpad_'+action))

    def _gold_balance(self):
        matches = self.ctx.ocr_service.get_ocr_result_list(image=self.last_screenshot, rect=Rect(1620,20,1790,85))
        numbers = [re.sub(r'\s+', '', str(m.data)) for m in matches]
        values = [int(s) for s in numbers if re.fullmatch(r'\d+', s)]
        return values[0] if len(values) == 1 else None

    def _buy_with_pad(self):
        cfg = self.ctx.lost_void.challenge_config
        if self.store_type != '标识-金币':
            return self.round_fail('后台血量商店暂不扣除血量，返回继续挑战')
        if not cfg.store_gold:
            return self.round_fail('不使用金币购买')
        pending = getattr(self, '_pad_purchase', None)
        screen_name = self.check_and_update_current_screen(self.last_screenshot)
        if screen_name == '迷失之地-通用选择' or common_choice(self.ctx, self.last_screenshot):
            op = LostVoidChooseCommon(self.ctx)
            op.return_screen_name = '迷失之地-邦布商店'
            result = op.execute()
            return self.round_wait('商店奖励已处理', wait=.5) if result.success else self.round_fail(result.status)
        if pending is not None:
            confirm = self.round_by_find_area(self.last_screenshot, '迷失之地-邦布商店', '按钮-购买-确认')
            if confirm.is_success:
                if pending['confirms'] >= 3:
                    return self.round_fail('商店购买确认未生效')
                self._pad('confirm')
                pending['confirms'] += 1
                return self.round_wait('确认购买，等待实际金币变化', wait=.8)
            balance = self._gold_balance() if screen_name == '迷失之地-邦布商店' else None
            if balance is not None and balance < pending['balance']:
                self._pad_purchase = None
                self._pad_target_name = None
                self._pad_scan_steps = 0
                self.ctx.lost_void.priority_updated = False
                return self.round_wait('已核验购买扣款：'+pending['name'], wait=.5)
            pending['waits'] += 1
            if pending['waits'] >= 5:
                return self.round_fail('购买后未核验到扣款，不重复购买')
            return self.round_wait('等待购买结果，未重复操作', wait=.5)
        if screen_name != '迷失之地-邦布商店':
            return self.round_retry('等待实际商店画面，未操作', wait=.5)
        balance = self._gold_balance()
        if balance is None:
            return self.round_retry('商店金币未识别，未购买', wait=.5)
        # 当前焦点的购买按钮为绿底黑字，不能依赖白字 OCR 的购买列表。
        hsv = cv2.cvtColor(self.last_screenshot[760:860], cv2.COLOR_RGB2HSV)
        mask = cv2.inRange(hsv, (20,145,100), (75,255,255))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        focus = [(x+w/2) for c in contours for x,y,w,h in [cv2.boundingRect(c)] if 140<w<340 and h>25]
        if len(focus) != 1:
            # The focused button can be disabled (too expensive/sold out).
            # Browse a bounded number of real shop slots instead of waiting 120s.
            steps = getattr(self, '_pad_scan_steps', 0)
            if steps >= 8:
                return self.round_fail('商店未找到可用购买焦点，结束购买')
            self._pad('right')
            self._pad_scan_steps = steps + 1
            return self.round_wait('跳过不可用购买按钮，浏览下一商品', wait=.5)
        all_items, buyable = self.get_artifact_pos(self.last_screenshot)
        available = [i for i in all_items if i.store_price is not None and 0 < i.store_price <= balance
            and (i in buyable or abs(i.rect.center.x-focus[0]) < 100)]
        priority = self.ctx.lost_void.get_artifact_by_priority(available, 1,
            consider_priority_1=True,
            consider_priority_2=self.refresh_times > cfg.buy_only_priority_1,
            consider_not_in_priority=self.refresh_times > cfg.buy_only_priority_2,
            consider_priority_new=cfg.artifact_priority_new) if available else []
        target_name = getattr(self, '_pad_target_name', None)
        target = next((i for i in available if i.artifact.display_name == target_name), None)
        if target is None and priority:
            target = priority[0]
            self._pad_target_name = target.artifact.display_name
        steps = getattr(self, '_pad_scan_steps', 0)
        if steps >= 8:
            return self.round_fail('后台商店未找到可核验的优先商品，结束购买')
        if target is None or abs(target.rect.center.x-focus[0]) >= 100:
            self._pad('left' if target is not None and target.rect.center.x < focus[0] else 'right')
            self._pad_scan_steps = steps + 1
            return self.round_wait('手柄浏览商店商品', wait=.5)
        self._pad('confirm')
        self._pad_purchase = {'name':target.artifact.display_name, 'balance':balance, 'confirms':0, 'waits':0}
        return self.round_wait('请求购买，等待实际确认及扣款', wait=.8)

    def get_artifact_pos(self, screen: MatLike) -> tuple[list[LostVoidArtifactPos], list[LostVoidArtifactPos]]:
        """
        获取藏品的位置
        @param screen: 游戏画面
        @return: 全部识别到的藏品、可购买的藏品
        """
        artifact_pos_list: list[LostVoidArtifactPos] = self.ctx.lost_void.get_artifact_pos(
            screen,
            screen_name='迷失之地-邦布商店'
        )

        # 识别价格
        area = self.ctx.screen_loader.get_area('迷失之地-邦布商店', '区域-价格')
        part = cv2_utils.crop_image_only(screen, area.rect)
        mask = cv2.inRange(part, (200, 200, 200), (255, 255, 255))
        mask = cv2_utils.dilate(mask, 2)
        to_ocr = cv2.bitwise_and(part, part, mask=mask)
        ocr_result_map = self.ctx.ocr.run_ocr(to_ocr)
        for ocr_result, mrl in ocr_result_map.items():
            price = str_utils.get_positive_digits(ocr_result)
            if price is None:
                continue

            for mr in mrl:
                mr.add_offset(area.left_top)
                for artifact_pos in artifact_pos_list:
                    artifact_pos.add_price(price, mr.rect)

        # 识别购买按钮
        area = self.ctx.screen_loader.get_area('迷失之地-邦布商店', '区域-购买按钮')
        part = cv2_utils.crop_image_only(screen, area.rect)
        mask = cv2.inRange(part, (200, 200, 200), (255, 255, 255))
        mask = cv2_utils.dilate(mask, 2)
        to_ocr = cv2.bitwise_and(part, part, mask=mask)
        ocr_result_map = self.ctx.ocr.run_ocr(to_ocr)
        for ocr_result, mrl in ocr_result_map.items():
            if not str_utils.find_by_lcs(gt('购买', 'game'), ocr_result):
                continue

            for mr in mrl:
                mr.add_offset(area.left_top)
                for artifact_pos in artifact_pos_list:
                    artifact_pos.add_buy(mr.rect)

        can_buy_list = [i for i in artifact_pos_list if i.store_buy_rect is not None]
        display_text = ', '.join([i.artifact.display_name for i in can_buy_list]) if len(can_buy_list) > 0 else '无'
        log.info(f'当前可购买藏品 {display_text}')

        return artifact_pos_list, can_buy_list

    def check_min_blood_valid(self, screen: MatLike) -> bool:
        """
        识别当前血量是否满足购买
        @param screen: 游戏画面
        @return:
        """
        min_blood = self.ctx.lost_void.challenge_config.store_blood_min

        area = self.ctx.screen_loader.get_area('迷失之地-邦布商店', '区域-角色头像')
        ocr_result_map = self.ctx.ocr.crop_and_run_ocr(screen, area.rect)
        for ocr_result, _mrl in ocr_result_map.items():
            blood = str_utils.get_positive_digits(ocr_result)
            if blood is None:
                continue
            if blood < min_blood:
                return False

        return True

    @node_from(from_name='购买藏品')
    @operation_node(name='点击确认')
    def click_confirm(self) -> OperationRoundResult:
        return self.round_by_find_and_click_area(screen_name='迷失之地-邦布商店', area_name='按钮-购买-确认',
                                                 success_wait=1, retry_wait=1,
                                                 until_not_find_all=[('迷失之地-邦布商店', '按钮-购买-确认')])

    @node_from(from_name='点击确认')
    @operation_node(name='确认后处理')
    def after_confirm(self) -> OperationRoundResult:
        """
        处理可能出现的武备升级环节
        @return:
        """
        screen_name = self.check_and_update_current_screen(self.last_screenshot)

        if screen_name == '迷失之地-通用选择':
            op = LostVoidChooseCommon(self.ctx)
            op_result = op.execute()
            if op_result.success:
                return self.round_wait(status='武备升级', wait=1)
            else:
                return self.round_retry(status='武备升级失败', wait=1)
        elif screen_name == '迷失之地-邦布商店':
            return self.round_success(status=self.store_type, wait=1)
        else:
            return self.round_retry(status=f'未知画面 {screen_name}', wait=1)

    @node_from(from_name='购买藏品', success=False)
    @operation_node(name='购买结束', timeout_seconds=20)
    def finish(self) -> OperationRoundResult:
        if getattr(self.ctx.controller, 'background_mode', False):
            name = self.check_and_update_current_screen(self.last_screenshot)
            if name != '迷失之地-邦布商店':
                if getattr(self, '_pad_back_requested', False):
                    return self.round_success('已核验商店关闭')
                return self.round_retry('未核验商店画面，未操作', wait=.5)
            if not getattr(self, '_pad_back_requested', False):
                self._pad('back')
                self._pad_back_requested = True
            return self.round_wait('关闭商店，等待画面确认', wait=.5)
        return self.round_by_find_and_click_area(screen_name='迷失之地-邦布商店', area_name='按钮-返回',
                                                 success_wait=1, retry_wait=1,
                                                 until_not_find_all=[('迷失之地-邦布商店', '按钮-返回')])


def __debug():
    ctx = ZContext()
    ctx.init()
    ctx.init_ocr()
    ctx.lost_void.init_before_run()
    ctx.run_context.start_running()

    op = LostVoidBangbooStore(ctx)
    op.execute()


if __name__ == '__main__':
    __debug()
