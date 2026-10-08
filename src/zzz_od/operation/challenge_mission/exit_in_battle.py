# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/operation/challenge_mission/exit_in_battle.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from onedragon.base.operation.operation_edge import node_from
from onedragon.base.operation.operation_node import operation_node
from onedragon.base.operation.operation_round_result import OperationRoundResult
from onedragon.utils.i18_utils import gt
from zzz_od.context.zzz_context import ZContext
from zzz_od.operation.zzz_operation import ZOperation
from zzz_od.operation.challenge_mission.restart_in_battle import RestartInBattle
from zzz_od.application.hollow_zero.lost_void.mission_screen import battle_result, collection_tab


class ExitInBattle(ZOperation):

    def __init__(self, ctx: ZContext, wait_screen_name: str = None, wait_area_name: str = None):
        """
        在战斗画面 尝试退出
        :param ctx: 上下文
        """
        ZOperation.__init__(self, ctx, op_name=gt('战斗中退出'))

        self.wait_screen_name: str = wait_screen_name  # 退出后等待的画面名称
        self.wait_area_name: str = wait_area_name  # 退出后等待的画面名称

    @operation_node(name='画面识别', is_start_node=True, node_max_retry_times=10)
    def check_screen(self) -> OperationRoundResult:
        if getattr(self.ctx.controller, 'background_mode', False):
            if self.wait_screen_name == '迷失之地-挑战结果' and battle_result(self.ctx, self.last_screenshot) == '完成':
                return self.round_success('已到达退出结算')
            if {'重新开始', '退出战斗'} <= self._menu_texts():
                return self.round_success('已核验手柄战斗菜单')
            if collection_tab(self.last_screenshot) is not None:
                requests = getattr(self, '_panel_close_requests', 0)
                if requests >= 3:
                    return self.round_fail('地图或藏品面板未关闭')
                self._pad('b')
                self._panel_close_requests = requests + 1
                return self.round_retry('关闭地图或藏品面板，等待新画面', wait=.8)
            if not getattr(self, '_menu_requested', False) and self.ctx.auto_battle_context.is_normal_attack_btn_available(self.last_screenshot):
                self._pad('start')
                self._menu_requested = True
            return self.round_retry('等待手柄退出菜单', wait=.8)
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
                return self.round_success('已核验退出确认框')
            requests = getattr(self, '_exit_requests', 0)
            if requests >= 3:
                return self.round_fail('手柄退出未出现确认框')
            if '退出战斗' not in self._menu_texts():
                return self.round_retry('未识别退出按钮，未操作', wait=.5)
            self._pad('y')  # 实机手柄菜单页脚：Y退出战斗，X重新开始。
            self._exit_requests = requests + 1
            return self.round_wait('手柄退出战斗，等待确认框', wait=.8)
        return self.round_by_find_and_click_area(self.last_screenshot, '战斗-菜单', '按钮-退出战斗',
                                                 until_find_all=[('战斗-菜单', '按钮-退出战斗-确认')],
                                                 success_wait=1, retry_wait=1)

    @node_from(from_name='点击退出战斗')
    @operation_node(name='点击确认')
    def click_confirm(self) -> OperationRoundResult:
        if getattr(self.ctx.controller, 'background_mode', False):
            visible = self.round_by_find_area(self.last_screenshot, '战斗-菜单', '按钮-退出战斗-确认').is_success
            if not visible:
                if getattr(self, '_confirm_requested', False):
                    return self.round_success('已核验退出确认框关闭')
                return self.round_retry('未识别退出确认框，未操作', wait=.5)
            if getattr(self, '_confirm_requested', False):
                return self.round_retry('等待退出确认生效，未重复按键', wait=.5)
            focus = self._confirm_focus()
            if focus is None:
                return self.round_retry('未识别退出确认框焦点，未操作', wait=.5)
            if focus == 'cancel':
                self._pad('dpad_right')
                return self.round_wait('定位退出确认按钮，等待焦点核验', wait=.3)
            self._pad('a')
            self._confirm_requested = True
            return self.round_wait('手柄确认退出，等待确认框关闭', wait=.8)
        return self.round_by_find_and_click_area(screen_name='战斗-菜单', area_name='按钮-退出战斗-确认',
                                                 until_not_find_all=[('战斗-菜单', '按钮-退出战斗-确认')],
                                                 success_wait=1, retry_wait=1)

    @node_from(from_name='点击确认')
    @node_from(from_name='画面识别', status='已到达退出结算')
    @operation_node(name='退出后等待', node_max_retry_times=60)
    def wait_at_last(self) -> OperationRoundResult:
        if self.wait_screen_name is None or self.wait_area_name is None:
            return self.round_success()
        if getattr(self.ctx.controller, 'background_mode', False) and self.wait_screen_name == '迷失之地-挑战结果':
            if battle_result(self.ctx, self.last_screenshot) == '完成':
                return self.round_success('已核验失败退出结算')
            return self.round_retry('等待实际退出结算画面', wait=1)
        return self.round_by_find_area(self.last_screenshot, self.wait_screen_name, self.wait_area_name,
                                       retry_wait=1)

    # 重试和退出使用同一套手柄映射与确认焦点判定。
    _pad = RestartInBattle._pad
    _menu_texts = RestartInBattle._menu_texts
    _confirm_focus = RestartInBattle._confirm_focus
