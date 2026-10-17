# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/application/charge_plan/charge_plan_app.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from typing import ClassVar

from onedragon.base.operation.application import application_const
from onedragon.base.operation.operation_edge import node_from
from onedragon.base.operation.operation_node import operation_node
from onedragon.base.operation.operation_notify import NotifyTiming, node_notify
from onedragon.base.operation.operation_round_result import OperationRoundResult
from onedragon.utils import cv2_utils, str_utils
from onedragon.utils.log_utils import log
from zzz_od.application.charge_plan import charge_plan_const
from zzz_od.application.charge_plan.charge_plan_config import (
    ChargePlanConfig,
    ChargePlanItem,
    RestoreChargeEnum,
)
from zzz_od.application.charge_plan.charge_plan_run_record import ChargePlanRunRecord
from zzz_od.application.zzz_application import ZApplication
from zzz_od.context.zzz_context import ZContext
from zzz_od.operation.back_to_normal_world import BackToNormalWorld
from zzz_od.operation.challenge_mission.check_next_after_battle import (
    ChooseNextOrFinishAfterBattle,
)
from zzz_od.operation.compendium.area_patrol import AreaPatrol
from zzz_od.operation.compendium.combat_simulation import CombatSimulation
from zzz_od.operation.compendium.compendium_choose_mission_type import CompendiumChooseMissionType
from zzz_od.operation.compendium.expert_challenge import ExpertChallenge
from zzz_od.operation.compendium.notorious_hunt import NotoriousHunt
from zzz_od.operation.compendium.tp_by_compendium import TransportByCompendium
from zzz_od.operation.exchange_ether_battery import ExchangeEtherBattery


class ChargePlanApp(ZApplication):
    """体力计划:按计划消耗电量刷训练副本(实战模拟室/区域巡防/专业挑战室/恶名狩猎-深度追猎)及电量合成(合成电池),支持循环与电量不足时用储蓄电量/以太电池补体。各分类按电量消耗,无日/周次数限。"""

    STATUS_NO_PLAN: ClassVar[str] = '没有可运行的计划'
    STATUS_ROUND_FINISHED: ClassVar[str] = '已完成一轮计划'
    STATUS_FIND_NEXT_PLAN: ClassVar[str] = '继续查找下一个计划'
    STATUS_EMPTY_PLAN: ClassVar[str] = '未配置体力计划，请先在体力刷本中添加刷本计划'

    def __init__(self, ctx: ZContext):
        ZApplication.__init__(
            self,
            ctx=ctx,
            app_id=charge_plan_const.APP_ID,
            op_name=charge_plan_const.APP_NAME,
        )
        self.config: ChargePlanConfig = self.ctx.run_context.get_config(
            app_id=charge_plan_const.APP_ID,
            instance_idx=self.ctx.current_instance_idx,
            group_id=application_const.DEFAULT_GROUP_ID,
        )
        self.run_record: ChargePlanRunRecord = self.ctx.run_context.get_run_record(
            app_id=charge_plan_const.APP_ID,
            instance_idx=self.ctx.current_instance_idx,
        )

        self.battery_charge: int = 0  # 电量
        self.backup_battery_charge: int = 0  # 储蓄电量
        self.ether_battery: int = 0  # 以太电池数量
        self.last_tried_plan: ChargePlanItem | None = None
        self.current_plan: ChargePlanItem | None = None
        self.challenge_failure: str | None = None
        self.challenge_count: int = 0  # 本次实际完成的挑战（含合成电池）
        self.idle_reason: str | None = None  # 本次没有挑战时的原因

    @operation_node(name='开始体力计划', is_start_node=True)
    def start_charge_plan(self) -> OperationRoundResult:
        self.last_tried_plan = None
        self.challenge_failure = None
        self.challenge_count = 0
        self.idle_reason = None
        for plan in self.config.plan_list:
            plan.skipped = False
        current_dt = self.run_record.get_current_dt()
        if self.config.reset_plan_times_each_run:
            # ok-zzz: 每次执行都从头走完整个计划；中途失败的计划下次执行也会重新计数。
            if self.config.reset_plan_times_for_run():
                log.info('每次执行重置计划次数：本次从头执行全部计划')
        elif self.config.try_reset_plan_times_by_dt(current_dt):
            log.info('已按游戏刷新日重置体力计划已运行次数 %s', current_dt)
        return self.round_success()

    @node_from(from_name='挑战完成')
    @node_from(from_name='开始体力计划')
    @node_from(from_name='跳过或结束计划', status=STATUS_FIND_NEXT_PLAN)
    @operation_node(name='前往大世界')
    def back_before_open_compendium(self) -> OperationRoundResult:
        op = BackToNormalWorld(self.ctx, ensure_normal_world=True)
        return self.round_by_op_result(op.execute())

    @node_from(from_name='前往大世界')
    @operation_node(name='打开快捷手册')
    def open_compendium(self) -> OperationRoundResult:
        return self.round_by_goto_screen(screen_name='快捷手册-训练')

    @staticmethod
    def _parse_battery_charge_ocr(ocr_result: dict) -> tuple[int, int, int]:
        """从「电量检测」流水线的 OCR 结果中解析三个电量字段 (电量, 储蓄电量, 以太电池)。

        以非数值字符（/）为分界线取左段数字（如 129/240 -> 129），纯数字直接用，无数字跳过；
        每个识别项的检测框中心与三个字段的固定中心锚点比较，归入最近的一个，
        同一字段多个候选时保留离锚点更近的；某字段无候选时该字段补 0。
        即使全部识别失败也返回 (0, 0, 0)，不抛异常。
        """
        # 三个字段的检测框中心锚点(相对裁剪区域), 来自测试样例统计
        field_centers = (173, 348, 485)

        # 解析文本项: 以 / 分界取左段数字, 纯数字直接用, 无数字跳过
        items: list[tuple[float, int]] = []  # (框中心x, value)
        for text, match_list in (ocr_result or {}).items():
            if match_list is None:
                continue
            for match in match_list:
                value = str_utils.get_positive_digits(text.split('/')[0], None)
                if value is None:
                    continue
                items.append((match.x + match.w / 2, value))

        # 每个识别项归入最近的字段锚点; 同一字段多个候选时保留离锚点更近的
        slot_values: list[tuple[float, int] | None] = [None, None, None]
        for x_center, value in items:
            field_idx = min(range(3), key=lambda i: abs(x_center - field_centers[i]))
            current = slot_values[field_idx]
            if current is None or abs(x_center - field_centers[field_idx]) < abs(current[0] - field_centers[field_idx]):
                slot_values[field_idx] = (x_center, value)

        return (
            slot_values[0][1] if slot_values[0] is not None else 0,
            slot_values[1][1] if slot_values[1] is not None else 0,
            slot_values[2][1] if slot_values[2] is not None else 0,
        )

    @node_from(from_name='打开快捷手册')
    @node_notify(when=NotifyTiming.CURRENT_FAIL)
    @operation_node(name='识别电量')
    def check_battery_charge(self) -> OperationRoundResult:
        """识别快捷手册资源栏中的电量、储蓄电量和以太电池。

        使用「电量检测」流水线：按「快捷手册->以太电池」区域裁剪，再做 HSV 颜色过滤，最后整栏 OCR，
        取数逻辑见 _parse_battery_charge_ocr。
        """
        pipeline_ctx = self.ctx.cv_service.run_pipeline('电量检测', self.last_screenshot)
        battery_charge, backup_battery_charge, ether_battery = self._parse_battery_charge_ocr(pipeline_ctx.ocr_result)

        self.battery_charge = battery_charge
        self.backup_battery_charge = backup_battery_charge
        self.ether_battery = ether_battery
        self.run_record.record_current_charge_power(self.battery_charge)
        log.info('剩余电量 %s 储蓄电量 %s 以太电池 %s', self.battery_charge, self.backup_battery_charge, self.ether_battery)
        return self.round_success('查找候选计划')

    @node_from(from_name='识别电量', status='查找候选计划')
    @node_from(from_name='判断是否执行', status=STATUS_FIND_NEXT_PLAN)
    @operation_node(name='查找候选计划')
    def find_next_plan(self) -> OperationRoundResult:
        """
        查找计划列表中的下一个候选计划

        找到后更新 self.current_plan；是否执行交给后续节点判断。
        """

        if not self.config.plan_list:
            # ok-zzz: 没有计划时什么都没做，不能报告成功。
            return self.round_fail(ChargePlanApp.STATUS_EMPTY_PLAN)

        # 检查是否所有计划都已完成
        if self.config.all_plan_finished():
            # 如果开启了循环模式且所有计划已完成，重置计划并继续
            if self.config.loop:
                self.last_tried_plan = None
                self.config.reset_plans()
            else:
                self.idle_reason = '计划已全部完成（未开启每次执行重置、每日重置和循环）'
                return self.round_success(ChargePlanApp.STATUS_ROUND_FINISHED)

        candidate_plan = self.config.get_next_plan(self.last_tried_plan)
        if candidate_plan is None:
            if self.config.all_plan_finished():
                return self.round_success(ChargePlanApp.STATUS_ROUND_FINISHED)
            return self.round_fail(ChargePlanApp.STATUS_NO_PLAN)

        self.current_plan = candidate_plan
        return self.round_success()

    @node_from(from_name='查找候选计划')
    @operation_node(name='判断是否执行')
    def check_before_transport(self) -> OperationRoundResult:

        # 未知类型会返回 0，交给副本内流程继续判断真实消耗
        need_battery_charge = self.current_plan.estimated_charge_power
        if need_battery_charge <= 0 or self.battery_charge >= need_battery_charge:
            return self.round_success()

        if self._can_restore_charge(need_battery_charge - self.battery_charge):
            return self.round_success()

        if not self.config.skip_plan:
            self.idle_reason = (f'电量不足：{self.current_plan.category_name} {self.current_plan.mission_type_name}'
                                f'需要 {need_battery_charge}')
            return self.round_success(ChargePlanApp.STATUS_ROUND_FINISHED)

        self.current_plan.skipped = True
        self.last_tried_plan = self.current_plan
        return self.round_success(ChargePlanApp.STATUS_FIND_NEXT_PLAN)

    def _can_restore_charge(self, required_charge: int) -> bool:
        if not self.config.is_restore_charge_enabled:
            return False

        restore_charge = self.config.restore_charge
        return (
            restore_charge in (
                RestoreChargeEnum.BACKUP_ONLY.value.value,
                RestoreChargeEnum.BOTH.value.value,
            )
            and self.backup_battery_charge >= required_charge
        ) or (
            restore_charge in (
                RestoreChargeEnum.ETHER_ONLY.value.value,
                RestoreChargeEnum.BOTH.value.value,
            )
            and self.ether_battery * 60 >= required_charge
        )

    @node_from(from_name='判断是否执行')
    @operation_node(name='传送')
    def transport(self) -> OperationRoundResult:
        # 使用已经在查找候选计划节点中设置好的 self.current_plan
        if self.current_plan.category_name == '合成电池':
            return self.round_success('合成电池')

        op = TransportByCompendium(self.ctx,
                                   self.current_plan.tab_name,
                                   self.current_plan.category_name,
                                   self.current_plan.mission_type_name)
        return self.round_by_op_result(op.execute())

    @node_from(from_name='传送', status='合成电池')
    @operation_node(name='合成电池')
    def exchange_ether_battery(self) -> OperationRoundResult:
        op = ExchangeEtherBattery(self.ctx, self.current_plan)
        return self.round_by_op_result(op.execute())

    @node_from(from_name='传送')
    @operation_node(name='识别副本分类')
    def check_mission_type(self) -> OperationRoundResult:
        return self.round_success(self.current_plan.category_name)

    @node_from(from_name='识别副本分类', status='实战模拟室')
    @operation_node(name='实战模拟室')
    def combat_simulation(self) -> OperationRoundResult:
        op = CombatSimulation(self.ctx, self.current_plan)
        return self.round_by_op_result(op.execute())

    @node_from(from_name='识别副本分类', status='区域巡防')
    @operation_node(name='区域巡防')
    def area_patrol(self) -> OperationRoundResult:
        op = AreaPatrol(self.ctx, self.current_plan)
        return self.round_by_op_result(op.execute())

    @node_from(from_name='识别副本分类', status='专业挑战室')
    @operation_node(name='专业挑战室')
    def expert_challenge(self) -> OperationRoundResult:
        op = ExpertChallenge(self.ctx, self.current_plan)
        return self.round_by_op_result(op.execute())

    @node_from(from_name='识别副本分类', status='恶名狩猎')
    @operation_node(name='恶名狩猎')
    def notorious_hunt(self) -> OperationRoundResult:
        op = NotoriousHunt(self.ctx, self.current_plan, use_charge_power=True)
        return self.round_by_op_result(op.execute())

    @node_from(from_name='实战模拟室', success=True)
    @node_from(from_name='实战模拟室', success=False)
    @node_from(from_name='区域巡防', success=True)
    @node_from(from_name='区域巡防', success=False)
    @node_from(from_name='专业挑战室', success=True)
    @node_from(from_name='专业挑战室', success=False)
    @node_from(from_name='恶名狩猎', success=True)
    @node_from(from_name='恶名狩猎', success=False)
    @node_from(from_name='合成电池', success=True)
    @node_from(from_name='合成电池', success=False)
    @operation_node(name='挑战完成')
    def challenge_complete(self) -> OperationRoundResult:
        if not self.previous_node.is_success:
            self.challenge_failure = (
                f'{self.current_plan.category_name} {self.current_plan.mission_type_name}失败：'
                f'{self.previous_node.status or "未知原因"}'
            )
            log.error(self.challenge_failure)
            return self.round_fail(self.challenge_failure)
        self.challenge_count = getattr(self, 'challenge_count', 0) + 1
        self.last_tried_plan = None
        return self.round_success()

    @node_from(from_name='实战模拟室', status=CombatSimulation.STATUS_CHARGE_NOT_ENOUGH)
    @node_from(from_name='区域巡防', status=AreaPatrol.STATUS_CHARGE_NOT_ENOUGH)
    @node_from(from_name='专业挑战室', status=ExpertChallenge.STATUS_CHARGE_NOT_ENOUGH)
    @node_from(from_name='恶名狩猎', status=NotoriousHunt.STATUS_CHARGE_NOT_ENOUGH)
    @node_from(from_name='恶名狩猎', status=NotoriousHunt.STATUS_BLOCKED_BY_LEFT_TIMES)
    @node_from(from_name='实战模拟室', status=ChooseNextOrFinishAfterBattle.STATUS_AGENT_PLAN_FINISHED)
    @node_from(from_name='区域巡防', status=ChooseNextOrFinishAfterBattle.STATUS_AGENT_PLAN_FINISHED)
    @node_from(from_name='专业挑战室', status=ChooseNextOrFinishAfterBattle.STATUS_AGENT_PLAN_FINISHED)
    @node_from(from_name='恶名狩猎', status=ChooseNextOrFinishAfterBattle.STATUS_AGENT_PLAN_FINISHED)
    @node_from(from_name='传送', status=CompendiumChooseMissionType.STATUS_NO_AGENT_TARGETS)
    @node_from(from_name='实战模拟室', status=CompendiumChooseMissionType.STATUS_NO_AGENT_TARGETS)
    @operation_node(name='跳过或结束计划')
    def skip_plan_or_finish(self) -> OperationRoundResult:
        is_agent_plan = self.current_plan.is_agent_plan
        is_blocked_by_left_times = (
            self.previous_node.status == NotoriousHunt.STATUS_BLOCKED_BY_LEFT_TIMES
        )
        if self.config.skip_plan or is_agent_plan or is_blocked_by_left_times:
            # 标记当前计划为跳过，继续尝试下一个
            self.current_plan.skipped = True
            self.last_tried_plan = self.current_plan
            return self.round_success(ChargePlanApp.STATUS_FIND_NEXT_PLAN)
        else:
            # 不跳过，直接结束本轮计划
            # ok-zzz: 副本内才发现的原因（如实际消耗高于预估的电量不足）也要写进结果。
            self.idle_reason = (f'{self.current_plan.category_name} {self.current_plan.mission_type_name}：'
                                f'{self.previous_node.status or "未知原因"}')
            self.last_tried_plan = None
            return self.round_success(ChargePlanApp.STATUS_ROUND_FINISHED)

    @node_from(from_name='挑战完成', success=False)
    @node_from(from_name='跳过或结束计划', status=STATUS_ROUND_FINISHED)
    @node_from(from_name='查找候选计划', status=STATUS_ROUND_FINISHED)
    @node_from(from_name='查找候选计划', status=STATUS_NO_PLAN)
    @node_from(from_name='查找候选计划', success=False)
    @node_from(from_name='判断是否执行', status=STATUS_ROUND_FINISHED)
    @node_notify(when=NotifyTiming.CURRENT_DONE, detail=True)
    @operation_node(name='返回大世界')
    def back_to_world(self) -> OperationRoundResult:
        op = BackToNormalWorld(self.ctx)
        op_result = op.execute()
        failure = getattr(self, 'challenge_failure', None)
        if failure is None and not self.previous_node.is_success:
            failure = self.previous_node.status or '体力计划失败'
        if failure is not None:
            if not op_result.success:
                failure += f'；返回大世界失败：{op_result.status or "未知原因"}'
            return self.round_fail(failure)
        status = f'剩余电量 {self.battery_charge}'
        if getattr(self, 'challenge_count', 0) == 0:
            reason = getattr(self, 'idle_reason', None) or '没有符合条件的计划'
            status = f'{reason}，本次未刷本；{status}'
        return self.round_by_op_result(op_result, status=status)


def __debug():
    ctx = ZContext()
    ctx.init()
    ctx.run_context.start_running()
    app = ChargePlanApp(ctx)
    app.config.plan_list = [
        ChargePlanItem(
            tab_name='训练',
            category_name='恶名狩猎',
            mission_type_name='猎血清道夫',
            level='默认等级',
            auto_battle_config='全配队通用',
            plan_times=1,
            predefined_team_idx=-1,
        )
    ]
    app.config.data['loop'] = False
    app.execute()


if __name__ == '__main__':
    __debug()
