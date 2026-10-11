# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/operation/compendium/notorious_hunt.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
import re

import numpy as np
import time
from typing import ClassVar

from onedragon.base.geometry.point import Point
from onedragon.base.geometry.rectangle import Rect
from onedragon.base.operation.application import application_const
from onedragon.base.operation.operation import Operation
from onedragon.base.operation.operation_edge import node_from
from onedragon.base.operation.operation_node import operation_node
from onedragon.base.operation.operation_notify import NotifyTiming, node_notify
from onedragon.base.operation.operation_round_result import OperationRoundResult
from onedragon.utils import cv2_utils, str_utils
from onedragon.utils.i18_utils import gt
from onedragon.utils.log_utils import log
from zzz_od.application.charge_plan import charge_plan_const
from zzz_od.application.charge_plan.charge_plan_config import (
    ChargePlanConfig,
    ChargePlanItem,
)
from zzz_od.application.notorious_hunt import notorious_hunt_const
from zzz_od.application.notorious_hunt.notorious_hunt_config import (
    NotoriousHuntConfig,
    NotoriousHuntLevelEnum,
)
from zzz_od.application.notorious_hunt.notorious_hunt_run_record import (
    NotoriousHuntRunRecord,
)
from src.controls.gamepad import press as pad
from zzz_od.context.zzz_context import ZContext
from zzz_od.operation.challenge_mission.check_next_after_battle import (
    ChooseNextOrFinishAfterBattle,
)
from zzz_od.operation.challenge_mission.exit_in_battle import ExitInBattle
from zzz_od.operation.choose_predefined_team import ChoosePredefinedTeam
from zzz_od.operation.compendium.notorious_hunt_move import NotoriousHuntMove
from zzz_od.operation.restore_charge import RestoreCharge
from zzz_od.operation.zzz_operation import ZOperation
from zzz_od.screen_area.screen_normal_world import ScreenNormalWorldEnum


class NotoriousHunt(ZOperation):

    STATUS_WITH_LEFT_TIMES: ClassVar[str] = '周期挑战有剩余次数'
    STATUS_NO_LEFT_TIMES: ClassVar[str] = '周期挑战无剩余次数'
    STATUS_BLOCKED_BY_LEFT_TIMES: ClassVar[str] = '周期挑战有剩余次数，本次跳过深度追猎'
    STATUS_CHARGE_NOT_ENOUGH: ClassVar[str] = '电量不足'
    STATUS_FIGHT_TIMEOUT: ClassVar[str] = '战斗超时'

    def __init__(self, ctx: ZContext, plan: ChargePlanItem,
                 use_charge_power: bool = False):
        """
        使用快捷手册传送后
        用这个进行挑战
        :param ctx:
        """
        ZOperation.__init__(
            self, ctx,
            op_name='{} {}'.format(
                gt('恶名狩猎', 'game'),
                gt(plan.mission_type_name, 'game')
            )
        )
        self.charge_plan_config: ChargePlanConfig = self.ctx.run_context.get_config(
            app_id=charge_plan_const.APP_ID,
            instance_idx=self.ctx.current_instance_idx,
            group_id=application_const.DEFAULT_GROUP_ID,
        )

        self.config: NotoriousHuntConfig = self.ctx.run_context.get_config(
            app_id=notorious_hunt_const.APP_ID,
            instance_idx=self.ctx.current_instance_idx,
            group_id=application_const.DEFAULT_GROUP_ID,
        )

        self.run_record: NotoriousHuntRunRecord = self.ctx.run_context.get_run_record(
            app_id=notorious_hunt_const.APP_ID,
            instance_idx=self.ctx.current_instance_idx,
        )

        self.plan: ChargePlanItem = plan
        self.use_charge_power: bool = use_charge_power  # 是否使用电量 深度追猎
        self.can_run_times: int = -1

    @operation_node(name='初始化加载', is_start_node=True)
    def init_for_notorious_hunt(self) -> OperationRoundResult:
        try:
            self.ctx.lost_void.init_lost_void_det_model()
        except Exception:
            return self.round_fail('初始化失败')
        return self.round_success()

    def _match_mission_type(self, target_name: str, ocr_result: str) -> bool:
        """
        匹配任务类型名称（支持别名双向查找）
        """
        names = [target_name]
        hunt_category = self.ctx.compendium_service.get_category_data('训练', '恶名狩猎')
        if hunt_category:
            for mt in hunt_category.mission_type_list:
                if mt.mission_type_name == target_name or target_name in mt.alias_list:
                    names.append(mt.mission_type_name)
                    names.extend(mt.alias_list)
                    names = list(set(names))
                    break
        return any(str_utils.find_by_lcs(gt(n, 'game'), ocr_result, percent=0.5) for n in names)

    @node_from(from_name='初始化加载')
    @operation_node(name='等待入口加载', node_max_retry_times=60)
    def wait_entry_load(self) -> OperationRoundResult:
        r1 = self.round_by_find_area(self.last_screenshot, '恶名狩猎', '当期剩余奖励次数')
        if r1.is_success:
            return self.round_success(r1.status, wait=1)  # 画面加载有延时 稍微等待

        r2 = self.round_by_find_area(self.last_screenshot, '恶名狩猎', '按钮-街区')
        if r2.is_success:
            return self.round_success(r2.status, wait=1)  # 画面加载有延时 稍微等待

        if self._on_target_page():
            # Current UI: the compendium's 前往 opens the target's own page directly.
            return self.round_success('按钮-街区', wait=1)

        return self.round_retry(r1.status, wait=1)

    def _on_target_page(self) -> bool:
        """The target page shows 周期剩余时间 at the bottom left (it replaced 当期剩余奖励次数)."""
        rows = self.ctx.ocr_service.get_ocr_result_list(image=self.last_screenshot, rect=Rect(150, 990, 620, 1060))
        return isinstance(rows, (list, tuple)) and any('剩余时间' in str(r.data) for r in rows)

    def _entry_panel(self) -> dict | None:
        """Read the current target page: 深度追猎 toggle, free rewards left and the "free runs used up" prompt.

        Returns None on the old layout (no ON/OFF text next to 深度追猎).
        """
        rows = self.ctx.ocr_service.get_ocr_result_list(image=self.last_screenshot, rect=Rect(300, 480, 1910, 1060))
        rows = rows if isinstance(rows, (list, tuple)) else []
        texts = [(str(r.data).replace(' ', ''), r.center) for r in rows]
        if any('免费挑战次数已用尽' in t for t, _ in texts):
            return {'toggle': None, 'left': None, 'popup': True}
        toggle = next((t for t, c in texts if t in ('ON', 'OFF') and 1640 < c.x < 1790 and 660 < c.y < 730), None)
        if toggle is None:
            return None
        left = None
        label = next((c for t, c in texts if '剩余奖励次数' in t), None)
        if label is not None:
            for t, c in texts:
                match = re.search(r'(\d+)/\d+', t)
                if match and abs(c.y - label.y) < 25 and c.x >= label.x - 80:
                    left = int(match.group(1))
                    break
        return {'toggle': toggle, 'left': left, 'popup': False}

    def _choose_level_by_gamepad(self) -> OperationRoundResult:
        """LS opens the 挑战等级 list; d-pad moves the filled focus and A applies it. Every step is re-read."""
        from src.navigation.menus import focus_mask
        norm = lambda text: str(text).replace(' ', '').upper()
        target = norm(self.plan.level)
        rows = self.ctx.ocr_service.get_ocr_result_list(image=self.last_screenshot, rect=Rect(1550, 20, 1820, 430))
        rows = [r for r in rows if norm(r.data).startswith('等级LV')] if isinstance(rows, (list, tuple)) else []
        header = [r for r in rows if r.center.y < 80]
        items = [r for r in rows if r.center.y >= 90]
        steps = getattr(self, '_pad_level_steps', 0)
        if steps >= 12:
            return self.round_fail(f'手柄选择挑战等级未生效：{self.plan.level}')
        self._pad_level_steps = steps + 1
        if len(items) < 2:
            if header and norm(header[0].data) == target:
                return self.round_success(f'已核验挑战等级：{self.plan.level}')
            pad(self.ctx, 'l_thumb')
            return self.round_wait('手柄打开挑战等级列表', wait=1)
        focused = [r for r in items if np.mean(focus_mask(
            self.last_screenshot[r.center.y-14:r.center.y+14, r.center.x-110:r.center.x+110])) > .3]
        wanted = next((r for r in items if norm(r.data) == target), None)
        if wanted is None:
            return self.round_fail(f'挑战等级列表中没有 {self.plan.level}')
        if len(focused) != 1:
            return self.round_retry('未核验唯一挑战等级焦点，未操作', wait=.6)
        if abs(focused[0].center.y - wanted.center.y) < 15:
            pad(self.ctx, 'a')
            return self.round_wait(f'手柄选择挑战等级：{self.plan.level}', wait=1)
        pad(self.ctx, 'dpad_up' if wanted.center.y < focused[0].center.y else 'dpad_down')
        return self.round_wait('手柄移动挑战等级焦点', wait=.6)

    def _toggle_pursuit(self) -> OperationRoundResult:
        presses = getattr(self, '_pursuit_toggles', 0)
        if presses >= 4:
            return self.round_fail('深度追猎开关切换未生效')
        self._pursuit_toggles = presses + 1
        if getattr(self.ctx.controller, 'background_mode', False):
            pad(self.ctx, 'r_thumb')  # The toggle shows the RS hint and ignores window-message clicks.
        else:
            self.round_by_click_area('恶名狩猎', '按钮-深度追猎-ON')
        return self.round_wait('切换深度追猎，等待实际状态', wait=1)

    def _confirm_pursuit_popup(self) -> OperationRoundResult:
        if getattr(self.ctx.controller, 'background_mode', False):
            pad(self.ctx, 'a')  # Focus starts on 确认.
        else:
            self.round_by_click_area('恶名狩猎', '按钮-深度追猎-确认')
        return self.round_wait('确认开启深度追猎', wait=1)

    @node_from(from_name='等待入口加载', status='按钮-街区')
    @operation_node(name='判断副本名称')
    def check_mission(self) -> OperationRoundResult:
        if self.plan.is_agent_plan:
        # 通过代理人进入则跳过重新选择副本
            return self.round_success()
        area = self.ctx.screen_loader.get_area('恶名狩猎', '标题-副本名称')
        ocr_result_map = self.ctx.ocr.crop_and_run_ocr(self.last_screenshot, area.rect)
        is_target_mission: bool = False  # 当前是否目标副本

        for ocr_result in ocr_result_map:
            if self._match_mission_type(self.plan.mission_type_name, ocr_result):
                is_target_mission = True
                break

        if is_target_mission:
            return self.round_success()
        else:
            return self.round_by_click_area('菜单', '返回', success_wait=1)

    @node_from(from_name='等待入口加载', status='当期剩余奖励次数')  # 最开始在外面的副本列表
    @node_from(from_name='判断副本名称', status='返回')  # 当前副本不符合 返回列表重新选择
    @operation_node(name='选择副本')
    def choose_mission(self) -> OperationRoundResult:
        area = self.ctx.screen_loader.get_area('恶名狩猎', '副本名称列表')

        ocr_result_map = self.ctx.ocr.crop_and_run_ocr(self.last_screenshot, area.rect)

        for ocr_result, mrl in ocr_result_map.items():
            if self._match_mission_type(self.plan.mission_type_name, ocr_result):
                to_click = mrl.max.center + area.left_top + Point(0, 100)
                if self.ctx.controller.click(to_click):
                    return self.round_success(wait=2)

        # 未匹配时 判断该往哪边滑动
        hunt_category = self.ctx.compendium_service.get_category_data('训练', '恶名狩猎')
        with_left: bool = False  # 当前识别有在目标左边的副本
        for mission_type in reversed(hunt_category.mission_type_list):
            if self._match_mission_type(self.plan.mission_type_name, mission_type.mission_type_name):
                break

            find: bool = False  # 当前画面有没有识别到 mission_type
            for ocr_result, _ in ocr_result_map.items():
                if str_utils.find_by_lcs(gt(mission_type.mission_type_name, 'game'), ocr_result, percent=0.5):
                    find = True
                    break

            if find:
                with_left = True

        drag_from = area.center
        if with_left:
            drag_to = Point(drag_from.x - 500, drag_from.y)
        else:
            drag_to = Point(drag_from.x + 500, drag_from.y)
        self.ctx.controller.drag_to(start=drag_from, end=drag_to)

        return self.round_retry(f'未能识别{self.plan.mission_type_name}', wait_round_time=2)

    @node_from(from_name='判断副本名称')  # 当前副本符合 继续选择
    @node_from(from_name='选择副本')
    @operation_node(name='抉择恶名狩猎', node_max_retry_times=10)
    def decide_notorious_hunt(self) -> OperationRoundResult:
        """
        恶名狩猎周期挑战

        出现'深度追猎-信息'，说明周期挑战'剩余次数'已经用完，直接标记完成
        通过识别剩余奖励次数决定本次可运行次数，周期挑战不用消耗体力
        """

        if self.use_charge_power:
            return self.round_success('深度追猎')

        panel = self._entry_panel()
        if panel is not None:
            if panel['popup']:
                if getattr(self.ctx.controller, 'background_mode', False):
                    pad(self.ctx, 'b')  # Cancel: free runs never switch 深度追猎 on.
                return self.round_wait('免费挑战不开启深度追猎', wait=1)
            if panel['toggle'] == 'ON':
                return self._toggle_pursuit()  # Free runs need 深度追猎 off.
            if panel['left'] is None:
                return self.round_retry('未识别到剩余奖励次数', wait=0.5)
            self.run_record.left_times = panel['left']
            if panel['left'] == 0:
                return self.round_success(NotoriousHunt.STATUS_NO_LEFT_TIMES)
            self.can_run_times = min(panel['left'], self.plan.plan_times - self.plan.run_times)
            log.info('恶名狩猎剩余奖励次数 %s', panel['left'])
            return self.round_success(NotoriousHunt.STATUS_WITH_LEFT_TIMES)

        result = self.round_by_find_area(self.last_screenshot, '恶名狩猎', '深度追猎-信息')
        if result.is_success:
            self.run_record.left_times = 0
            return self.round_success(NotoriousHunt.STATUS_NO_LEFT_TIMES)
        else:
            area = self.ctx.screen_loader.get_area('恶名狩猎', '剩余次数')
            part = cv2_utils.crop_image_only(self.last_screenshot, area.rect)

            ocr_result = self.ctx.ocr.run_ocr_single_line(part)
            left_times = str_utils.get_positive_digits(ocr_result, None)
            if left_times is None:  # 识别不到时 使用记录中的数量
                if self.node_retry_times < self.node_max_retry_times:
                    return self.round_retry('未识别到剩余次数', wait=0.5)
                self.can_run_times = self.run_record.left_times
            else:
                self.run_record.left_times = left_times
                self.can_run_times = left_times

            log.info('恶名狩猎剩余奖励次数 %s', self.can_run_times)

            # 运行次数上限是计划剩余次数
            need_run_times = self.plan.plan_times - self.plan.run_times
            if self.can_run_times > need_run_times:
                self.can_run_times = need_run_times

            return self.round_success(NotoriousHunt.STATUS_WITH_LEFT_TIMES)

    @node_from(from_name='抉择恶名狩猎', status='深度追猎')
    @operation_node(name='抉择深度追猎')
    def decide_by_use_power(self) -> OperationRoundResult:
        """
        恶名狩猎深度追猎

        出现'深度追猎-信息'，且点亮'深度追猎-ON'后，才可正式开始
        区域对应文本"剩余奖励次数"会变成"电量消耗"，深度追猎需要消耗体力
        """

        panel = self._entry_panel()
        if panel is not None:
            if panel['popup']:
                return self._confirm_pursuit_popup()
            if panel['toggle'] == 'OFF':
                return self._toggle_pursuit()
            return self.round_success(NotoriousHunt.STATUS_NO_LEFT_TIMES)  # ON: proceed with energy.

        # 尝试点亮"深度追猎-ON"之后的对话框
        result = self.round_by_find_and_click_area(self.last_screenshot, '恶名狩猎', '按钮-深度追猎-确认')
        if result.is_success:
            return self.round_wait(result.status, wait=1)
        result = self.round_by_find_area(self.last_screenshot, '恶名狩猎', '深度追猎-信息')
        if result.is_success:
            result = self.round_by_find_area(self.last_screenshot, '恶名狩猎', '按钮-深度追猎-ON')
            if result.is_success:
                return self.round_success(NotoriousHunt.STATUS_NO_LEFT_TIMES)
            result = self.round_by_find_area(self.last_screenshot, '恶名狩猎', '按钮-无报酬模式')
            if result.is_success:
                self.round_by_click_area('恶名狩猎', '按钮-深度追猎-ON')
                return self.round_wait(wait=1)
            return self.round_retry(wait=1)

        return self.round_success(NotoriousHunt.STATUS_BLOCKED_BY_LEFT_TIMES)

    @node_from(from_name='抉择恶名狩猎', status=STATUS_WITH_LEFT_TIMES)
    @node_from(from_name='抉择深度追猎', status=STATUS_NO_LEFT_TIMES)
    @operation_node(name='选择难度')
    def choose_level(self) -> OperationRoundResult:
        if self.plan.level == NotoriousHuntLevelEnum.DEFAULT.value.value:
            return self.round_success()
        if getattr(self.ctx.controller, 'background_mode', False):
            return self._choose_level_by_gamepad()

        self.round_by_click_area('恶名狩猎', '难度选择入口')
        time.sleep(1)

        screen = self.screenshot()
        area = self.ctx.screen_loader.get_area('恶名狩猎', '难度选择区域')
        result = self.round_by_ocr_and_click(screen, self.plan.level, area=area,
                                           success_wait=1)

        # 如果选择的是最高难度 那第一下有可能选中不到 多选一下兜底
        screen = self.screenshot()
        self.round_by_ocr_and_click(screen, self.plan.level, area=area,
                                    success_wait=1)

        if result.is_success:
            return result
        else:
            return self.round_retry(result.status, wait=1)

    @node_from(from_name='选择难度')
    @node_from(from_name='恢复电量', status=RestoreCharge.STATUS_RESTORE_SUCCESS)
    @operation_node(name='下一步', node_max_retry_times=10)  # 部分机器加载较慢 延长出战的识别时间
    def click_next(self) -> OperationRoundResult:
        # 防止前面电量识别错误
        result = self.round_by_find_area(self.last_screenshot, '恢复电量', '标题-恢复电量')
        if result.is_success:
            return self.round_success(status=NotoriousHunt.STATUS_CHARGE_NOT_ENOUGH)

        # 点击直到出战按钮出现
        result = self.round_by_find_area(self.last_screenshot, '实战模拟室', '出战')
        if result.is_success:
            return self.round_success(result.status)

        if getattr(self.ctx.controller, 'background_mode', False):
            from src.navigation.menus import pad_next_step
            return pad_next_step(self)

        result = self.round_by_find_and_click_area(self.last_screenshot, '实战模拟室', '下一步')
        if result.is_success:
            time.sleep(0.5)
            self.ctx.controller.mouse_move(ScreenNormalWorldEnum.UID.value.center)  # 点击后 移开鼠标 防止识别不到出战
            return self.round_wait(result.status, wait=0.5)

        return self.round_retry(result.status, wait=1)

    @node_from(from_name='下一步', status=STATUS_CHARGE_NOT_ENOUGH)
    @operation_node(name='恢复电量')
    def restore_charge(self) -> OperationRoundResult:
        if not self.charge_plan_config.is_restore_charge_enabled:
            return self.round_success(NotoriousHunt.STATUS_CHARGE_NOT_ENOUGH)
        op = RestoreCharge(self.ctx)
        return self.round_by_op_result(op.execute())

    @node_from(from_name='下一步', status='出战')
    @operation_node(name='选择预备编队')
    def choose_predefined_team(self) -> OperationRoundResult:
        if self.plan.predefined_team_idx == -1:
            return self.round_success('无需选择预备编队')
        else:
            op = ChoosePredefinedTeam(self.ctx, [self.plan.predefined_team_idx])
            return self.round_by_op_result(op.execute())

    @node_from(from_name='选择预备编队')
    @operation_node(name='出战')
    def click_start(self) -> OperationRoundResult:
        if getattr(self.ctx.controller, 'background_mode', False):
            from zzz_od.operation.deploy import Deploy
            return self.round_by_op_result(Deploy(self.ctx).execute())
        return self.round_by_find_and_click_area(
            self.last_screenshot, '实战模拟室', '出战',
            success_wait=1, retry_wait_round=1
        )

    @node_from(from_name='出战')
    @node_from(from_name='重新开始-确认')
    @operation_node(name='加载自动战斗指令')
    def init_auto_battle(self) -> OperationRoundResult:
        if self.plan.predefined_team_idx == -1:
            auto_battle = self.plan.auto_battle_config
        else:
            team_list = self.ctx.team_config.team_list
            auto_battle = team_list[self.plan.predefined_team_idx].auto_battle

        self.ctx.auto_battle_context.init_auto_op(
            sub_dir='auto_battle',
            op_name=auto_battle,
        )
        return self.round_success()

    @node_from(from_name='加载自动战斗指令')
    @operation_node(name='等待战斗画面加载', node_max_retry_times=60, is_start_node=False)
    def wait_battle_screen(self) -> OperationRoundResult:
        result = self.round_by_find_area(self.last_screenshot, '战斗画面', '按键-普通攻击')
        if result.is_success:
            return self.round_success(self.plan.mission_type_name)

        result = self.round_by_find_area(self.last_screenshot, '战斗画面', '按键-交互')
        if result.is_success:
            return self.round_success(self.plan.mission_type_name)

        return self.round_retry(result.status, wait=1)

    @node_from(from_name='等待战斗画面加载')
    @operation_node(name='战斗前移动')
    def run_battle(self) -> OperationRoundResult:
        op = NotoriousHuntMove(self.ctx, self.plan.notorious_hunt_buff_num)
        return self.round_by_op_result(op.execute())

    @node_from(from_name='战斗前移动')
    @node_from(from_name='战斗失败', status='战斗结果-倒带')
    @operation_node(name='开始自动战斗')
    def start_auto_op(self) -> OperationRoundResult:
        self.ctx.auto_battle_context.start_auto_battle()
        return self.round_success()

    @node_from(from_name='开始自动战斗')
    @operation_node(name='自动战斗', mute=True, timeout_seconds=600)
    def auto_battle(self) -> OperationRoundResult:
        if self.ctx.auto_battle_context.last_check_end_result is not None:
            self.ctx.auto_battle_context.stop_auto_battle()
            return self.round_success(status=self.ctx.auto_battle_context.last_check_end_result)

        self.ctx.auto_battle_context.check_battle_state(
            self.last_screenshot, self.last_screenshot_time,
            check_battle_end_normal_result=True,
        )

        return self.round_wait(wait=self.ctx.battle_assistant_config.screenshot_interval)

    @node_from(from_name='自动战斗', status='普通战斗-撤退')
    @operation_node(name='战斗失败')
    def battle_fail(self) -> OperationRoundResult:
        if getattr(self.ctx.controller, 'background_mode', False):
            # Retreat instead of rewinding a lost fight: 倒带 restarts the same losing battle.
            from onedragon.base.geometry.rectangle import Rect
            from src.navigation.menus import press_labelled
            if press_labelled(self, self.last_screenshot, '撤退', Rect(400, 800, 1500, 960)):
                return self.round_success('战斗结果-撤退', wait=2)
            return self.round_retry('未核验撤退按钮，未操作', wait=1)
        result = self.round_by_find_and_click_area(self.last_screenshot, '战斗画面', '战斗结果-倒带')

        if result.is_success:
            self.ctx.auto_battle_context.last_check_end_result = None
            return self.round_success(result.status, wait=1)

        result = self.round_by_find_and_click_area(self.last_screenshot, '战斗画面', '战斗结果-撤退')
        if result.is_success:
            return self.round_success(result.status, wait=1)

        return self.round_retry(result.status, wait=1)

    @node_from(from_name='战斗失败', status='战斗结果-撤退')
    @operation_node(name='战斗失败退出')
    def battle_fail_exit(self) -> OperationRoundResult:
        if getattr(self.ctx.controller, 'background_mode', False):
            from onedragon.base.geometry.rectangle import Rect
            from src.navigation.menus import press_labelled
            if press_labelled(self, self.last_screenshot, '退出', Rect(1400, 980, 1900, 1070)):
                return self.round_fail('战斗结果-退出', wait=2)  # Same outcome as the mouse path.
            return self.round_retry('未核验退出按钮，未操作', wait=1)
        result = self.round_by_find_and_click_area(self.last_screenshot, '战斗画面', '战斗结果-退出')

        if result.is_success:  # 战斗失败 返回失败到外层 中断后续挑战
            return self.round_fail(result.status, wait=10)
        else:
            return self.round_retry(result.status, wait=1)

    @node_from(from_name='战斗前移动', success=False)
    @node_from(from_name='自动战斗', success=False, status=Operation.STATUS_TIMEOUT)
    @operation_node(name='退出战斗')
    def exit_battle(self) -> OperationRoundResult:
        self.ctx.auto_battle_context.stop_auto_battle()
        op = ExitInBattle(self.ctx, '战斗-挑战结果-失败', '按钮-退出')
        return self.round_by_op_result(op.execute())

    @node_from(from_name='退出战斗')
    @operation_node(name='点击挑战结果退出')
    def click_result_exit(self) -> OperationRoundResult:
        if getattr(self.ctx.controller, 'background_mode', False):
            from onedragon.base.geometry.rectangle import Rect
            from src.navigation.menus import press_labelled
            if press_labelled(self, self.last_screenshot, '退出', Rect(1400, 980, 1900, 1070)):
                return self.round_fail(NotoriousHunt.STATUS_FIGHT_TIMEOUT, wait=2)  # Same outcome as the mouse path.
            return self.round_retry('未核验退出按钮，未操作', wait=1)
        result = self.round_by_find_and_click_area(screen_name='战斗-挑战结果-失败', area_name='按钮-退出',
                                                   until_not_find_all=[('战斗-挑战结果-失败', '按钮-退出')],
                                                   success_wait=1, retry_wait=1)
        if result.is_success:
            return self.round_fail(status=NotoriousHunt.STATUS_FIGHT_TIMEOUT)
        else:
            return self.round_retry(status=result.status, wait=1)

    @node_from(from_name='自动战斗')
    @node_notify(when=NotifyTiming.CURRENT_SUCCESS, detail=True)
    @operation_node(name='战斗结束')
    def after_battle(self) -> OperationRoundResult:
        self.can_run_times -= 1
        if self.use_charge_power:
            self.charge_plan_config.add_plan_run_times(self.plan)
        else:
            self.run_record.left_times = self.run_record.left_times - 1
            self.config.add_plan_run_times(self.plan)
        return self.round_success()

    @node_from(from_name='战斗结束')
    @operation_node(name='判断下一次')
    def check_next(self) -> OperationRoundResult:
        if self.use_charge_power:
            try_next = self.plan.plan_times > self.plan.run_times
        else:
            try_next = self.can_run_times > 0
        op = ChooseNextOrFinishAfterBattle(self.ctx, try_next, is_agent_plan=self.plan.is_agent_plan)
        result = op.execute()
        if result.status == '战斗结果-完成' and self.can_run_times > 0:
            # 可能是其他设备挑战了 没有剩余次数了
            self.run_record.left_times = 0
        return self.round_by_op_result(result)

    @node_from(from_name='判断下一次', status='战斗结果-再来一次')
    @operation_node(name='重新开始-确认')
    def restart_confirm(self) -> OperationRoundResult:
        if self.use_charge_power:  # 使用体力的时候不需要重新确认
            return self.round_success()
        return self.round_by_find_and_click_area(self.last_screenshot, '恶名狩猎', '重新开始-确认',
                                                 success_wait=1, retry_wait_round=1)

    @node_from(from_name='判断下一次', status='战斗结果-完成')
    @operation_node(name='等待返回入口', node_max_retry_times=60)
    def wait_back_to_entry(self) -> OperationRoundResult:
        result = self.round_by_find_area(self.last_screenshot, '恶名狩猎', '剩余奖励次数')
        if result.is_success:  # 普通模式
            return self.round_success(wait=1)

        result = self.round_by_find_area(self.last_screenshot, '恶名狩猎', '按钮-街区')
        if result.is_success:  # 深度追猎
            return self.round_success(wait=1)

        if self._on_target_page():
            return self.round_success(wait=1)

        return self.round_retry(result.status, wait=1)

    def handle_pause(self, e=None):
        self.ctx.auto_battle_context.stop_auto_battle()

    def handle_resume(self, e=None):
        if self.current_node.node is not None and self.current_node.node.cn == '自动战斗':
            self.ctx.auto_battle_context.resume_auto_battle()


def __debug_charge():
    """测试剩余次数识别。"""
    ctx = ZContext()
    ctx.init()
    from onedragon.utils import debug_utils
    screen = debug_utils.get_debug_image('_1774444468708')
    area = ctx.screen_loader.get_area('恶名狩猎', '剩余次数')
    part = cv2_utils.crop_image_only(screen, area.rect)
    ocr_result = ctx.ocr.run_ocr_single_line(part)
    left_times = str_utils.get_positive_digits(ocr_result, None)
    print(left_times)


def __debug():
    ctx = ZContext()
    ctx.init()
    ctx.run_context.start_running()
    op = NotoriousHunt(
        ctx,
        ChargePlanItem(
            category_name='恶名狩猎',
            mission_type_name='猎血清道夫',
            level=NotoriousHuntLevelEnum.DEFAULT.value.value,
            auto_battle_config='全配队通用',
            predefined_team_idx=-1,
        ),
        use_charge_power=False,
    )
    op.execute()


if __name__ == '__main__':
    __debug()
