# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/application/life_on_line/life_on_line_app.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
import time
from typing import ClassVar

from onedragon.base.operation.application import application_const
from onedragon.base.operation.operation_edge import node_from
from onedragon.base.operation.operation_node import operation_node
from onedragon.base.operation.operation_notify import NotifyTiming, node_notify
from onedragon.base.operation.operation_round_result import OperationRoundResult
from onedragon.utils import cv2_utils
from zzz_od.application.life_on_line import life_on_line_const
from zzz_od.application.life_on_line.life_on_line_config import LifeOnLineConfig
from zzz_od.application.life_on_line.life_on_line_run_record import LifeOnLineRunRecord
from zzz_od.application.zzz_application import ZApplication
from zzz_od.context.zzz_context import ZContext
from zzz_od.operation.back_to_normal_world import BackToNormalWorld
from zzz_od.operation.hdd.enter_hdd_mission import EnterHddMission
from zzz_od.operation.key_sim_runner import KeySimRunner
from zzz_od.operation.transport import Transport
from zzz_od.operation.wait_normal_world import WaitNormalWorld


class LifeOnLineApp(ZApplication):

    """真·拿命验收:第二章间章的 HDD 战斗委托,可重复挑战;主要用于推进/跳过游戏时间(过夜)。进入战斗、单次很快(默认按次数重复)。"""

    STATUS_TIMES_FINISHED: ClassVar[str] = '完成指定次数'
    STATUS_CONTINUE: ClassVar[str] = '继续'
    STATUS_CONTINUE_OVER_NIGHT: ClassVar[str] = '过夜后继续'


    def __init__(self, ctx: ZContext):
        ZApplication.__init__(
            self,
            ctx=ctx,
            app_id=life_on_line_const.APP_ID,
            op_name=life_on_line_const.APP_NAME,
        )
        self.config: LifeOnLineConfig = self.ctx.run_context.get_config(
            app_id=life_on_line_const.APP_ID,
            instance_idx=self.ctx.current_instance_idx,
            group_id=application_const.DEFAULT_GROUP_ID,
        )
        self.run_record: LifeOnLineRunRecord = self.ctx.run_context.get_run_record(
            instance_idx=self.ctx.current_instance_idx,
            app_id=life_on_line_const.APP_ID,
        )
        self.is_over_night: bool = False  # 本次结束是否过夜了
        self.chosen_team: bool = False  # 是否已经选择过配队了

    @operation_node(name='传送', is_start_node=True)
    def tp(self) -> OperationRoundResult:
        op = Transport(self.ctx, '录像店', 'HDD')
        return self.round_by_op_result(op.execute())

    @node_from(from_name='传送')
    @operation_node(name='等待加载')
    def wait_world(self) -> OperationRoundResult:
        op = WaitNormalWorld(self.ctx)
        return self.round_by_op_result(op.execute())

    @node_from(from_name='等待加载')
    @node_from(from_name='检查运行次数', status=STATUS_CONTINUE_OVER_NIGHT)
    @operation_node(name='交互')
    def interact(self) -> OperationRoundResult:
        if getattr(self.ctx.controller, 'background_mode', False):
            from src.navigation.hdd import enter_hdd
            result = enter_hdd(self, self.last_screenshot)
            if result is not None:
                self._hdd_interact_requests = 0  # allow a fresh interaction after a later overnight return
                return result
            # A is also agent selection / mission-next on later pages. Never keep
            # sending it merely because the old 「街区」 label is absent.
            world = self.check_and_update_current_screen(self.last_screenshot,
                                                        screen_name_list=['大世界-普通'])
            if world != '大世界-普通':
                return self.round_retry('未核验大世界或HDD页面，未发送交互', wait=1)
            requests = getattr(self, '_hdd_interact_requests', 0)
            if requests >= 3:
                return self.round_fail('手柄HDD交互未生效')
            self._hdd_interact_requests = requests + 1
            self.ctx.controller.interact(press=True, press_time=.2, release=True)
            return self.round_wait('手柄交互HDD，等待实际界面', wait=2)
        result = self.round_by_find_area(self.last_screenshot, 'HDD', '街区')
        if result.is_success:
            return self.round_success()

        self.ctx.controller.interact(press=True, press_time=0.2, release=True)
        time.sleep(1)

        return self.round_wait()

    @node_from(from_name='交互')
    @node_from(from_name='检查运行次数', status=STATUS_CONTINUE)
    @operation_node(name='进入副本')
    def enter_mission(self) -> OperationRoundResult:
        target_team_idx: int = self.config.predefined_team_idx
        if self.chosen_team:  # 只需要选1次
            target_team_idx = -1
        op = EnterHddMission(self.ctx, '第二章间章', '战斗委托', '作战真拿命验收',
                             target_team_idx)
        return self.round_by_op_result(op.execute())

    @node_from(from_name='进入副本')
    @operation_node(name='等待战斗画面加载', node_max_retry_times=60)
    def wait_battle_screen(self) -> OperationRoundResult:
        self.chosen_team = True
        return self.round_by_find_area(self.last_screenshot, '战斗画面', '按键-普通攻击',
                                       retry_wait=0.5)

    @node_from(from_name='等待战斗画面加载')
    @operation_node(name='模拟按键')
    def run_key_sim(self) -> OperationRoundResult:
        op = KeySimRunner(self.ctx, '真拿命验收')
        return self.round_by_op_result(op.execute())

    @node_from(from_name='模拟按键')
    @operation_node(name='通关交互', node_max_retry_times=10)
    def interact_after_mission(self) -> OperationRoundResult:
        result = self.round_by_find_area(self.last_screenshot, '真拿命验收', '对话人')
        if result.is_success:
            return self.round_success()

        self.ctx.controller.interact(press=True, press_time=0.2, release=True)

        return self.round_retry(wait=1)

    @node_from(from_name='通关交互')
    @operation_node(name='对话', node_max_retry_times=30)
    def talk_after_mission(self) -> OperationRoundResult:
        result = self.round_by_find_area(self.last_screenshot, '战斗画面', '战斗结果-完成')
        if result.is_success:
            return self.round_success(wait=1)

        # 有选项就点选项
        area = self.ctx.screen_loader.get_area('真拿命验收', '对话选项')
        ocr_result_map = self.ctx.ocr.crop_and_run_ocr(self.last_screenshot, area.rect)
        for ocr_result, mrl in ocr_result_map.items():
            to_click = mrl.max.center + area.left_top
            self.ctx.controller.click(to_click)
            return self.round_wait(status=ocr_result, wait=1)

        # 一直点击到出现完成按钮
        self.round_by_click_area('菜单', '返回')

        return self.round_retry(wait=1)

    @node_from(from_name='对话')
    @operation_node(name='完成', node_max_retry_times=60)
    def click_finished(self) -> OperationRoundResult:
        result = self.round_by_find_area(self.last_screenshot, 'HDD', '街区')
        if result.is_success:
            self.is_over_night = False
            self.run_record.add_times()
            return self.round_success(result.status)

        # 一直点击直到出现街区
        result = self.round_by_find_and_click_area(self.last_screenshot, '战斗画面', '战斗结果-完成')
        if result.is_success:
            return self.round_wait(result.status, wait=0.5)

        # 过夜提醒的对话比较多 不进行识别 不断点击空白直到返回大世界
        op = WaitNormalWorld(self.ctx, check_once=True)
        result = self.round_by_op_result(op.execute())
        if result.is_success:
            self.is_over_night = True
            self.run_record.add_times()
            return self.round_success(result.status)

        self.round_by_click_area('HDD', '空白')

        return self.round_retry(result.status, wait=1)

    @node_from(from_name='完成')
    @node_from(from_name='点击退出战斗确认')
    @operation_node(name='检查运行次数')
    def check_times(self) -> OperationRoundResult:
        self.run_record.check_and_update_status()
        if self.run_record.is_finished_by_times():
            return self.round_success(LifeOnLineApp.STATUS_TIMES_FINISHED)
        else:
            if self.is_over_night:
                return self.round_success(LifeOnLineApp.STATUS_CONTINUE_OVER_NIGHT)
            else:
                return self.round_success(LifeOnLineApp.STATUS_CONTINUE)

    @node_from(from_name='检查运行次数', status=STATUS_TIMES_FINISHED)
    @node_notify(when=NotifyTiming.PREVIOUS_DONE)
    @operation_node(name='返回大世界')
    def back_to_world(self) -> OperationRoundResult:
        op = BackToNormalWorld(self.ctx)
        return self.round_by_op_result(op.execute())

    @node_from(from_name='通关交互', success=False)
    @operation_node(name='交互失败')
    def fail_to_interact(self) -> OperationRoundResult:
        result = self.round_by_find_area(self.last_screenshot, '恶名狩猎', '退出战斗')
        if result.is_success:
            return self.round_success(wait=1)  # 稍微等一下让按钮可按

        result = self.round_by_click_area('战斗画面', '菜单')
        if result.is_success:
            return self.round_wait(result.status, wait=2)
        else:
            return self.round_fail(result.status)

    @node_from(from_name='交互失败')
    @operation_node(name='点击退出战斗')
    def click_exit_battle(self) -> OperationRoundResult:
        return self.round_by_find_and_click_area(self.last_screenshot, '恶名狩猎', '退出战斗',
                                                 success_wait=1, retry_wait=1)

    @node_from(from_name='点击退出战斗')
    @operation_node(name='点击退出战斗确认')
    def click_exit_battle_confirm(self) -> OperationRoundResult:
        return self.round_by_find_and_click_area(self.last_screenshot, '恶名狩猎', '退出战斗-确认',
                                                 success_wait=5, retry_wait=1)


def __debug():
    ctx = ZContext()
    ctx.init()
    ctx.run_context.start_running()
    app = LifeOnLineApp(ctx)
    app.execute()

if __name__ == '__main__':
    __debug()
