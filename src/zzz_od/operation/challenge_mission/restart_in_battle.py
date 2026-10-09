# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/operation/challenge_mission/restart_in_battle.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
import cv2
from onedragon.base.operation.operation_edge import node_from
from onedragon.base.operation.operation_node import operation_node
from onedragon.base.operation.operation_round_result import OperationRoundResult
from onedragon.base.geometry.rectangle import Rect
from onedragon.utils.i18_utils import gt
from zzz_od.context.zzz_context import ZContext
from zzz_od.operation.zzz_operation import ZOperation
from src.controls.gamepad import press as pad


class RestartInBattle(ZOperation):

    def __init__(self, ctx: ZContext):
        """
        在战斗画面 尝试退出
        :param ctx: 上下文
        """
        ZOperation.__init__(self, ctx, op_name=gt('战斗中-重新开始'))

    @operation_node(name='画面识别', is_start_node=True, node_max_retry_times=10)
    def check_screen(self) -> OperationRoundResult:
        if getattr(self.ctx.controller, 'background_mode', False):
            texts = self._menu_texts()
            if {'重新开始', '退出战斗'} <= texts:
                return self.round_success('已核验手柄战斗菜单')
            if not getattr(self, '_menu_requested', False) and self.ctx.auto_battle_context.is_normal_attack_btn_available(self.last_screenshot):
                self._pad('start')
                self._menu_requested = True
            return self.round_retry('等待手柄战斗菜单', wait=.8)
        # 点击直到出现 [退出战斗] 按钮
        result = self.round_by_find_area(self.last_screenshot, '战斗-菜单', '按钮-退出战斗')
        if result.is_success:
            return self.round_success(wait=1)  # 稍微等一下让按钮可按
        result = self.round_by_click_area('战斗画面', '菜单')
        return self.round_retry(result.status, wait=1)

    @node_from(from_name='画面识别')
    @operation_node(name='点击退出战斗')
    def click_exit_battle(self) -> OperationRoundResult:
        if getattr(self.ctx.controller, 'background_mode', False):
            if self.round_by_find_area(self.last_screenshot, '战斗-菜单', '按钮-退出战斗-确认').is_success:
                return self.round_success('已核验重新开始确认框')
            requests = getattr(self, '_restart_requests', 0)
            if requests >= 3:
                return self.round_fail('手柄重新开始未出现确认框')
            if '重新开始' not in self._menu_texts():
                return self.round_retry('未识别重新开始按钮，未操作', wait=.5)
            self._pad('x')
            self._restart_requests = requests + 1
            return self.round_wait('手柄重新开始，等待确认框', wait=.8)
        return self.round_by_find_and_click_area(self.last_screenshot, '战斗-菜单', '按钮-重新开始',
                                                 until_find_all=[('战斗-菜单', '按钮-退出战斗-确认')],
                                                 success_wait=1, retry_wait=1)

    @node_from(from_name='点击退出战斗')
    @operation_node(name='点击确认')
    def click_confirm(self) -> OperationRoundResult:
        if getattr(self.ctx.controller, 'background_mode', False):
            visible = self.round_by_find_area(self.last_screenshot, '战斗-菜单', '按钮-退出战斗-确认').is_success
            if not visible:
                if getattr(self, '_confirm_requested', False):
                    return self.round_success('已核验重新开始确认框关闭')
                return self.round_retry('未识别重新开始确认框，未操作', wait=.5)
            if getattr(self, '_confirm_requested', False):
                return self.round_retry('等待重新开始确认生效，未重复按键', wait=.5)
            focus = self._confirm_focus()
            if focus is None:
                return self.round_retry('未识别确认框焦点，未操作', wait=.5)
            if focus == 'cancel':
                self._pad('dpad_right')
                return self.round_wait('定位重新开始确认按钮，等待焦点核验', wait=.3)
            self._pad('a')
            self._confirm_requested = True
            return self.round_wait('手柄确认重新开始，等待确认框关闭', wait=.8)
        return self.round_by_find_and_click_area(screen_name='战斗-菜单', area_name='按钮-退出战斗-确认',
                                                 until_not_find_all=[('战斗-菜单', '按钮-退出战斗-确认')],
                                                 success_wait=1, retry_wait=1)

    def _menu_texts(self):
        matches = self.ctx.ocr_service.get_ocr_result_list(image=self.last_screenshot,
            rect=Rect(1200,990,1890,1065))
        return {str(m.data).replace(' ', '') for m in matches}

    def _pad(self, button):
        pad(self.ctx, button)

    def _confirm_focus(self):
        hsv = cv2.cvtColor(self.last_screenshot, cv2.COLOR_RGB2HSV)
        focused = []
        for name, x1, x2 in (('cancel',700,900),('confirm',1038,1224)):
            region = hsv[607:650,x1:x2]
            if (cv2.inRange(region,(20,145,155),(75,255,255)) > 0).mean() > .55:
                focused.append(name)
        return focused[0] if len(focused) == 1 else None

def __debug():
    """
    调试用
    """
    ctx = ZContext()
    ctx.init()
    ctx.init_ocr()
    ctx.run_context.start_running()

    op = RestartInBattle(ctx)
    op.execute()


if __name__ == "__main__":
    __debug()
