# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/operation/challenge_mission/check_next_after_battle.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from typing import ClassVar

from onedragon.base.operation.application import application_const
from onedragon.base.operation.operation_edge import node_from
from onedragon.base.operation.operation_node import operation_node
from onedragon.base.operation.operation_round_result import OperationRoundResult
from onedragon.utils.i18_utils import gt
from src.controls.gamepad import press as pad
from zzz_od.application.charge_plan import charge_plan_const
from zzz_od.application.charge_plan.charge_plan_config import ChargePlanConfig
from zzz_od.context.zzz_context import ZContext
from zzz_od.operation.restore_charge import RestoreCharge
from zzz_od.operation.zzz_operation import ZOperation


class ChooseNextOrFinishAfterBattle(ZOperation):

    STATUS_AGENT_PLAN_FINISHED: ClassVar[str] = '特训目标已达成'

    def __init__(self, ctx: ZContext, try_next: bool, is_agent_plan: bool = False) -> None:
        """
        在战斗结束画面 尝试点击 【再来一次】 或者 【完成】
        :param ctx: 上下文
        :param try_next: 是否尝试点击下一次
        :param is_agent_plan: 当前是否特训目标(代理人方案培养) 用于判断是否已达成
        """
        ZOperation.__init__(self, ctx, op_name=gt('战斗后选择'))
        self.try_next: bool = try_next
        self.is_agent_plan: bool = is_agent_plan

    @node_from(from_name='恢复电量', status='战斗结果-完成')
    @operation_node(name='判断再来一次', is_start_node=True)
    def check_next(self) -> OperationRoundResult:
        if getattr(self.ctx.controller, 'background_mode', False):
            return self._check_next_by_gamepad()
        # 特训目标(代理人方案培养)结算画面左下角显示“已达成”时 说明本条计划无需再打 直接点完成结束
        if self.try_next and self.is_agent_plan:
            result = self.round_by_find_area(self.last_screenshot, '战斗画面', '战斗结果-已达成')
            if result.is_success:
                result = self.round_by_find_and_click_area(self.last_screenshot, '战斗画面', '战斗结果-完成',
                                                           success_wait=5, retry_wait=1)
                if result.is_success:
                    return self.round_success(status=ChooseNextOrFinishAfterBattle.STATUS_AGENT_PLAN_FINISHED)
                return result

        if self.try_next:
            result = self.round_by_find_and_click_area(self.last_screenshot, '战斗画面', '战斗结果-再来一次',
                                                       success_wait=1, retry_wait=1)
            if result.is_success:
                return result

        return self.round_by_find_and_click_area(self.last_screenshot, '战斗画面', '战斗结果-完成',
                                                 success_wait=5, retry_wait=1)

    def _check_next_by_gamepad(self) -> OperationRoundResult:
        """The result screen ignores window-message clicks: X is 再来一次 and B is 完成.

        Press once, then wait for the result buttons to disappear before reporting the choice.
        """
        finish = self.round_by_find_area(self.last_screenshot, '战斗画面', '战斗结果-完成')
        again = self.round_by_find_area(self.last_screenshot, '战斗画面', '战斗结果-再来一次')
        sent = getattr(self, '_pad_result_choice', None)
        if not finish.is_success and not again.is_success:
            if sent is not None:
                return self.round_success(status=sent)
            return self.round_retry('未识别战斗结果按钮，未操作', wait=1)
        if self.try_next and self.is_agent_plan and self.round_by_find_area(
                self.last_screenshot, '战斗画面', '战斗结果-已达成').is_success:
            choice, button = ChooseNextOrFinishAfterBattle.STATUS_AGENT_PLAN_FINISHED, 'b'
        elif self.try_next and again.is_success:
            choice, button = '战斗结果-再来一次', 'x'
        else:
            choice, button = '战斗结果-完成', 'b'
        requests = getattr(self, '_pad_result_requests', 0)
        if requests >= 4:
            return self.round_fail(f'手柄选择{choice}未生效')
        self._pad_result_requests = requests + 1
        self._pad_result_choice = choice
        pad(self.ctx, button)
        return self.round_wait(f'手柄选择{choice}，等待画面变化', wait=1.5)

    @node_from(from_name='判断再来一次', status='战斗结果-再来一次')
    @operation_node(name='恢复电量')
    def restore_charge(self) -> OperationRoundResult:
        # 检查是否在恢复电量界面
        result = self.round_by_find_area(self.last_screenshot, '恢复电量', '标题-恢复电量')
        if not result.is_success:
            # 没有恢复弹窗，说明这次“再来一次”已直接生效
            return self.round_success(status='战斗结果-再来一次' if self.try_next else '战斗结果-完成')

        config: ChargePlanConfig = self.ctx.run_context.get_config(
            app_id=charge_plan_const.APP_ID,
            instance_idx=self.ctx.current_instance_idx,
            group_id=application_const.DEFAULT_GROUP_ID,
        )

        if config.is_restore_charge_enabled:
            op = RestoreCharge(self.ctx)
            op.is_after_battle_retry = True
            op_result = op.execute()
            if not op_result.success:
                return self.round_by_op_result(op_result)
            self.try_next = op_result.status == RestoreCharge.STATUS_RESTORE_SUCCESS
        else:
            self.try_next = False
            if getattr(self.ctx.controller, 'background_mode', False):
                pad(self.ctx, 'b')
                return self.round_wait('未启用恢复电量，关闭弹窗后重新核验结算画面', wait=.5)
            result = self.round_by_find_and_click_area(self.last_screenshot, '恢复电量', '取消',
                                                       success_wait=1, retry_wait=1)
            if not result.is_success:
                return result

        # 恢复流程结束后回到“判断再来一次”；是否继续由 try_next 决定，这里不直接点“完成”
        return self.round_success(status='战斗结果-完成', wait=0.5)
