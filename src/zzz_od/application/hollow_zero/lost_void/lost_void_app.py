# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/application/hollow_zero/lost_void/lost_void_app.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
import time
from typing import ClassVar
from onedragon.base.geometry.rectangle import Rect

import cv2

from onedragon.base.geometry.point import Point
from onedragon.base.matcher.match_result import MatchResult, MatchResultList
from onedragon.base.operation.application import application_const
from onedragon.base.operation.operation import Operation
from onedragon.base.operation.operation_edge import node_from
from onedragon.base.operation.operation_node import operation_node
from onedragon.base.operation.operation_notify import NotifyTiming, node_notify
from onedragon.base.operation.operation_round_result import OperationRoundResult
from onedragon.base.screen import screen_utils
from onedragon.utils import cv2_utils, log_utils, str_utils
from onedragon.utils.i18_utils import gt
from onedragon.utils.log_utils import log
from zzz_od.application.hollow_zero.lost_void import lost_void_const
from zzz_od.application.hollow_zero.lost_void.bounty_progress import read_progress
from zzz_od.application.hollow_zero.lost_void.mission_screen import common_choice, recover_connection, menu_matches, detail_mission, focused_card, MISSION_NAMES, battle_result, dialogue_visible, single_event_choice, black_story_caption, entry_header, failed_grade, lottery_counts, period_buff_state
from zzz_od.application.hollow_zero.lost_void.lost_void_challenge_config import (
    LostVoidRegionType,
)
from zzz_od.application.hollow_zero.lost_void.lost_void_config import LostVoidConfig
from zzz_od.application.hollow_zero.lost_void.matrix_team import custom_matrix_agents, resolve_agent_ids
from zzz_od.application.hollow_zero.lost_void.lost_void_run_record import (
    LostVoidRunRecord,
)
from zzz_od.application.hollow_zero.lost_void.operation.lost_void_run_level import (
    LostVoidRunLevel,
)
from zzz_od.application.zzz_application import ZApplication
from zzz_od.context.zzz_context import ZContext
from zzz_od.game_data.agent import Agent, AgentEnum
from zzz_od.operation.agent_template_matcher import match_team_agent_template
from zzz_od.operation.back_to_normal_world import BackToNormalWorld
from zzz_od.operation.choose_predefined_team import ChoosePredefinedTeam
from zzz_od.operation.compendium.tp_by_compendium import TransportByCompendium
from zzz_od.operation.deploy import Deploy


class LostVoidApp(ZApplication):

    """零号空洞-迷失之地:周限肉鸽玩法(与枯萎之都共享每周奖励次数)。周限、进入战斗、耗时较长。"""
    STATUS_ENOUGH_TIMES: ClassVar[str] = '完成通关次数'
    STATUS_AGAIN: ClassVar[str] = '继续挑战'
    STATUS_AGAIN_MATRIX: ClassVar[str] = '继续挑战-矩阵行动'

    def __init__(self, ctx: ZContext,
                 lost_void_debug: bool = False,
                 next_region_type: LostVoidRegionType = LostVoidRegionType.ENTRY):
        ZApplication.__init__(
            self,
            ctx=ctx,
            app_id=lost_void_const.APP_ID,
            op_name=lost_void_const.APP_NAME,
        )
        self.config: LostVoidConfig = self.ctx.run_context.get_config(
            app_id=lost_void_const.APP_ID,
            instance_idx=self.ctx.current_instance_idx,
            group_id=application_const.DEFAULT_GROUP_ID,
        )
        self.run_record: LostVoidRunRecord = self.ctx.run_context.get_run_record(
            instance_idx=self.ctx.current_instance_idx,
            app_id=lost_void_const.APP_ID,
        )

        self.next_region_type = next_region_type  # 下一个区域的类型
        self.priority_agent_list: list[Agent] = []  # 优先选择的代理人列表

        self.use_priority_agent: bool = False  # 本次挑战是否使用了UP代理人
        self._matrix_selection = None
        self._mission_returned_from = None
        self._mission_recoveries = 0
        self._regular_switch_requests = 0

        # debug
        self.lost_void_debug = lost_void_debug

    @operation_node(name='初始化加载', is_start_node=True)
    def init_for_lost_void(self) -> OperationRoundResult:
        # 检查分配给今天的任务是否完成
        if self.run_record.is_finished_by_day:
            return self.round_success(LostVoidApp.STATUS_ENOUGH_TIMES)

        try:
            custom = custom_matrix_agents(self.config)
        except ValueError as exc:
            return self.round_fail(str(exc))
        self._matrix_selection = None
        self._mission_returned_from = None
        self._mission_recoveries = 0
        self._regular_switch_requests = 0
        self._buff_requests = 0
        self._reward_list_requests = 0
        if custom is not None:
            self.ctx.lost_void.predefined_team_idx = -1
        try:
            # 这里会加载迷失之洞的数据 识别模型 和自动战斗配置
            log.info('迷失之地初始化：任务=%s，挑战配置=%s，正在加载寻路模型与藏品数据',
                     self.config.mission_name, self.config.challenge_config)
            self.ctx.lost_void.init_before_run()
        except Exception as exc:
            log.error('迷失之地初始化失败：%s', exc, exc_info=True)
            return self.round_fail(f'迷失之地初始化失败：{exc}')
        log.info('迷失之地初始化完成，开始识别当前游戏画面')
        return self.round_success(LostVoidApp.STATUS_AGAIN)

    @node_from(from_name='初始化加载', status=STATUS_AGAIN)
    @operation_node(name='识别初始画面')
    def check_initial_screen(self) -> OperationRoundResult:
        recovery = recover_connection(self)
        if recovery is not None:
            return recovery
        if self.lost_void_debug:
            return self.round_success('迷失之地-大世界')
        background = getattr(self.ctx.controller, 'background_mode', False)
        if background:
            from src.background_navigation import lost_void_gateway_visible
            if lost_void_gateway_visible(self,self.last_screenshot):
                return self.round_success('可前往副本画面')
            matches = self.ctx.ocr_service.get_ocr_result_list(image=self.last_screenshot,
                rect=Rect(1200,990,1890,1065))
            menu_actions = {str(m.data).replace(' ', '') for m in matches}
            if {'重新开始', '退出战斗'} <= menu_actions:
                requests = getattr(self, '_resume_menu_requests', 0)
                if requests >= 3:
                    return self.round_fail('战斗暂停菜单关闭未生效')
                ds4 = self.ctx.game_config.background_gamepad_type == 'ds4'
                self.ctx.controller.btn_press('ds4_circle' if ds4 else 'xbox_b',press_time=.12)
                self._resume_menu_requests = requests + 1
                return self.round_wait('手柄关闭战斗暂停菜单，等待恢复',wait=.8)
        result = self.round_by_find_area(self.last_screenshot, '迷失之地-大世界', '按钮-挑战-确认') if background else self.round_by_find_and_click_area(self.last_screenshot, '迷失之地-大世界', '按钮-挑战-确认')
        # 特殊兼容：在挑战区域开始，接力运行
        if result.is_success:
            self.next_region_type = LostVoidRegionType.CHANLLENGE_TIME_TRAIL
            if background:
                # 交给层间移动处理实际确认及弹窗离开，启动阶段只识别画面。
                return self.round_success('迷失之地-大世界')
            return self.round_wait(result.status, wait=1)

        if self._entry_header() is not None:
            return self.round_success('已在迷失之地入口')
        mission_name = self.config.mission_name
        if detail_mission(self.ctx, self.last_screenshot) == mission_name:
            return self.round_success('已在目标副本详情')
        if len(menu_matches(self.ctx, self.last_screenshot)) >= 2:
            return self.round_success('已在常规入口')
        if (battle_result(self.ctx, self.last_screenshot) or dialogue_visible(self.ctx, self.last_screenshot)
                or (single_event_choice(self.ctx, self.last_screenshot) or common_choice(self.ctx, self.last_screenshot))
                or lottery_counts(self.ctx, self.last_screenshot) is not None
                or black_story_caption(self.ctx, self.last_screenshot) is not None):
            return self.round_success('迷失之地-大世界')
        if self.check_and_update_current_screen(self.last_screenshot, screen_name_list=[
            '迷失之地-武备选择', '迷失之地-通用选择', '迷失之地-路径迭换',
            '迷失之地-邦布商店', '迷失之地-抽奖机',
        ]) is not None:
            return self.round_success('迷失之地-大世界')
        screen_name, can_go = self.check_screen_with_can_go(self.last_screenshot, f'迷失之地-{mission_name}')
        if screen_name == '迷失之地-大世界':
            return self.round_success('迷失之地-大世界')

        if can_go or screen_name == f'迷失之地-{mission_name}':
            return self.round_success('可前往副本画面')

        if time.time() < getattr(self, '_connection_wait_until', 0):
            return self.round_wait('连接已恢复，等待当前入口画面重新加载', wait=1)

        # 未识别到画面；走快捷手册传送流程
        can_go = self.check_current_can_go('快捷手册-作战')
        if can_go:
            return self.round_success('可前往快捷手册')

        return self.round_success('未识别初始画面', wait=1)

    @node_from(from_name='识别初始画面', status='可前往快捷手册')
    @node_from(from_name='识别初始画面', status=Operation.STATUS_SCREEN_UNKNOWN)
    @node_from(from_name='识别初始画面', status='未识别初始画面')
    @operation_node(name='前往零号空洞-入口')
    def tp_to_lost_void(self) -> OperationRoundResult:
        op = TransportByCompendium(self.ctx,
                                   '作战',
                                   '周期征讨',
                                   '迷失之地')
        return self.round_by_op_result(op.execute())

    @node_from(from_name='识别初始画面', status='可前往副本画面')
    @node_from(from_name='前往零号空洞-入口')
    @operation_node(name='前往迷失之地-入口', node_max_retry_times=20)
    def choose_lost_void_entry(self) -> OperationRoundResult:
        """前往迷失之地入口"""
        if getattr(self.ctx.controller,'background_mode',False):
            if self._entry_header() is not None or len(menu_matches(self.ctx,self.last_screenshot))>=2:
                return self._wait_for_lost_void_entry()
            from src.background_navigation import lost_void_gateway
            result=lost_void_gateway(self,self.last_screenshot)
            return result if result is not None else self._wait_for_lost_void_entry()
        result = self.round_by_ocr_and_click(self.last_screenshot, '迷失之地')
        if result.is_success:
            return self.round_retry('尝试进入迷失之地-入口', wait=1)

        if result.status == '找不到 迷失之地':
            return self._wait_for_lost_void_entry()

        return self.round_retry(result.status, wait=1)

    def _wait_for_lost_void_entry(self) -> OperationRoundResult:
        """等待迷失之地入口加载完成。"""
        recovery = recover_connection(self)
        if recovery is not None:
            return recovery
        entry = self._entry_header()
        if entry is not None:
            return self.round_success(entry)
        if len(menu_matches(self.ctx, self.last_screenshot)) >= 2:
            return self.round_success('迷失之地-入口-常规')
        result = self.round_by_find_and_click_area(self.last_screenshot, '迷失之地-入口', '按钮-更新弹窗-关闭')
        if result.is_success:
            return self.round_retry(result.status, wait=0.5)

        screen_name_list = ['迷失之地-入口-周期', '迷失之地-入口-常规']
        screen_name = self.check_and_update_current_screen(self.last_screenshot, screen_name_list=screen_name_list)
        if screen_name not in screen_name_list:
            return self.round_wait(status='等待画面加载', wait=1)
        return self.round_success(status=screen_name)

    def _entry_header(self):
        return entry_header(self.ctx, self.last_screenshot)

    @node_from(from_name='前往迷失之地-入口')
    @node_from(from_name='识别初始画面',status='已在迷失之地入口')
    @node_from(from_name='通关后处理')
    @node_notify(when=NotifyTiming.CURRENT_DONE, send_image=False, detail=True)
    @operation_node(name='识别悬赏委托完成进度', node_max_retry_times=5)
    def check_bounty_commission_before(self) -> OperationRoundResult:
        """
        识别悬赏委托完成进度
        读取画面显示的 当前值/目标值，兼容不同周期的悬赏上限。

        :return: 操作结果
        """
        if not self.config.is_bounty_commission_mode:
            if self.run_record.is_finished_by_day:
                return self.round_success(LostVoidApp.STATUS_ENOUGH_TIMES)
            if self.config.mission_name == '矩阵行动':
                return self.round_success(LostVoidApp.STATUS_AGAIN_MATRIX)
            return self.round_success(LostVoidApp.STATUS_AGAIN)

        result = self.round_by_find_area(self.last_screenshot, '迷失之地-入口', '按钮-悬赏委托')
        if not result.is_success:
            return self.round_retry('未识别到悬赏委托', wait=0.5)

        # 裁剪悬赏委托进度区域
        area = self.ctx.screen_loader.get_area('迷失之地-入口', '区域-悬赏委托-进度')
        if area is None:
            return self.round_fail('缺少悬赏委托进度识别区域，请检查程序资源')
        part = cv2_utils.crop_image_only(self.last_screenshot, area.rect)
        if part is None or part.size == 0:
            return self.round_retry('悬赏进度截图为空，等待入口画面', wait=0.5)
        ocr_result_list = self.ctx.ocr.ocr(part)
        progress = read_progress(ocr_result_list)
        texts = [str(item.data) for item in ocr_result_list]
        if progress is None:
            # 小字号、窗口缩放时额外放大识别，仍要求完整的进度分数。
            enlarged = cv2.resize(part, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            enlarged_results = self.ctx.ocr.ocr(enlarged)
            progress = read_progress(enlarged_results)
            texts.extend(str(item.data) for item in enlarged_results)
        if progress is None:
            detail = ' | '.join(texts)[:160] or '无文字'
            if self.node_retry_times >= self.node_max_retry_times:
                path = self.save_screenshot(prefix='lost_void_bounty_unreadable')
                log.error('悬赏进度无法识别，OCR=%s，截图=%s', detail, path)
            return self.round_retry(f'悬赏进度未识别到当前值/目标值（OCR：{detail}）', wait=0.5)

        current, target = progress
        log.info('迷失之地悬赏进度：%d/%d，%s', current, target,
                 '已完成，准备领取奖励' if current == target else '未完成，继续挑战')
        if current == target:
            if not self.run_record.bounty_commission_complete:
                self.run_record.bounty_commission_complete = True
            return self.round_success(LostVoidApp.STATUS_ENOUGH_TIMES)
        if self.config.mission_name == '矩阵行动':
            return self.round_success(LostVoidApp.STATUS_AGAIN_MATRIX)
        return self.round_success(LostVoidApp.STATUS_AGAIN)

    # ========== 矩阵行动入口流程节点 ==========

    @node_from(from_name='识别悬赏委托完成进度', status=STATUS_AGAIN_MATRIX)
    @operation_node(name='矩阵行动-前往入口')
    def matrix_goto_entry(self) -> OperationRoundResult:
        # 排除因为ocr太慢导致的错误信息
        error = self.round_by_find_and_click_area(self.last_screenshot, '迷失之地-矩阵行动-编队选择', '确认', success_wait=1)
        if error.is_success:
            log_utils.log('已点击意外出现的确认按钮')

        return self.round_by_goto_screen(
            screen_name='迷失之地-矩阵行动-编队选择',
            screen_switch_debounce=3,
        )

    @node_from(from_name='矩阵行动-前往入口')
    @operation_node(name='矩阵行动-点击预备编队')
    def matrix_click_preset_team(self) -> OperationRoundResult:
        try:
            custom = custom_matrix_agents(self.config)
        except ValueError as exc:
            return self.round_fail(str(exc))
        self._matrix_selection = None
        if custom is not None or self.ctx.lost_void.challenge_config.manually_choose_agent:
            # 自定义队伍不能继承上轮的预备编队战斗配置。
            self.ctx.lost_void.predefined_team_idx = -1
            return self.round_success('手动选取角色')
        area = self.ctx.screen_loader.get_area('迷失之地-矩阵行动-编队选择', '预备编队')
        if area is not None:
            part = cv2_utils.crop_image_only(self.last_screenshot, area.rect)
            if cv2_utils.is_colorful(part):
                # 按钮已变成彩色，说明加载完成
                return self.round_success(status='预备编队已加载', wait=1)

        # 按钮还是灰度，需要点击
        result = self.round_by_find_and_click_area(
            self.last_screenshot,
            '迷失之地-矩阵行动-编队选择',
            '预备编队',
            success_wait=1,
        )
        if result.is_success:
            return self.round_wait(status='预备编队加载中', wait=0.5)

        return self.round_retry(status='点击预备编队失败', wait=0.5)

    @node_from(from_name='矩阵行动-点击预备编队')
    @operation_node(name='矩阵行动-选择预备编队', node_max_retry_times=7)
    def matrix_select_team(self) -> OperationRoundResult:
        # 初始为较高的匹配阈值，如果超过5次匹配失败则改用0.5的阈值兜底
        lcs_percent = 0.7 if self.node_retry_times < 5 else 0.5

        main_team_area = self.ctx.screen_loader.get_area('迷失之地-矩阵行动-编队选择', '主战编队槽')

        # 获取目标编队名称
        predefined_idx = self.ctx.lost_void.challenge_config.predefined_team_idx
        if predefined_idx == -1:
            predefined_idx = 0
        if not 0 <= predefined_idx < len(self.ctx.team_config.team_list):
            return self.round_fail('预备编队编号超出范围')
        self.ctx.lost_void.predefined_team_idx = predefined_idx
        team_name = self.ctx.team_config.team_list[predefined_idx].name

        # 查找并点击目标配队
        team_match_result = self.round_by_ocr_and_click(
            screen=self.last_screenshot,
            target_cn=team_name,
            lcs_percent=lcs_percent,
            remove_whitespace=True, # 去除空白字符提高匹配兼容性
        )

        if team_match_result.is_success:
            # 等待画面更新
            time.sleep(0.5)
            self.screenshot()
            # 在主战编队槽区域检测是否出现"主战"
            ocr_result_list = self.ctx.ocr_service.get_ocr_result_list(
                image=self.last_screenshot,
                rect=main_team_area.rect,
            )
            success_msg = '已选择配队'
            if self.node_retry_times >= 5:
                success_msg += '(随机)'
            for ocr_text in ocr_result_list:
                if '主战' in ocr_text.data:
                    return self.round_success(success_msg, wait=1)
            return self.round_retry('未找到主战', wait=0.5)

        self.scroll_area(screen_name='迷失之地-矩阵行动-编队选择', area_name='编队列表', direction='down')
        return self.round_retry(f'未找到{team_name}, 尝试向下滚动', wait=0.3)

    @node_from(from_name='矩阵行动-点击预备编队', status='手动选取角色')
    @operation_node(name='矩阵行动-选择代理人')
    def matrix_select_agent(self) -> OperationRoundResult:
        # 每轮只执行一次点击或翻页；下轮由 Operation 获取新截图。
        if self.ctx.run_context.is_context_stop:
            return self.round_fail('任务已停止')
        if not self.ctx.run_context.is_context_running:
            return self.round_wait('任务已暂停', wait=0.2)
        if self.last_screenshot is None:
            return self.round_fail('未获得编队画面，停止选人')
        try:
            target = custom_matrix_agents(self.config)
            if target is None:
                target = resolve_agent_ids(self.ctx.lost_void.challenge_config.team_info)
        except ValueError as exc:
            return self.round_fail(str(exc))
        agent_area = self.ctx.screen_loader.get_area('迷失之地-矩阵行动-编队选择', '代理人列表')
        main_area = self.ctx.screen_loader.get_area('迷失之地-矩阵行动-编队选择', '主战编队槽')
        if self._matrix_selection is None:
            # 模板缺失时先报错，避免清空用户的现有队伍后才发现不能识别。
            agents = {item.value.agent_id: item.value for item in AgentEnum}
            for agent_id in target:
                agent = agents[agent_id]
                if not any(self.ctx.template_loader.get_template('predefined_team', f'avatar_{tid}')
                           is not None for tid in agent.template_id_list):
                    return self.round_fail(f'缺少角色识别模板：{agent.agent_name}')
            self._matrix_selection = {'target': target, 'phase': 'open', 'index': 0,
                                      'clear_times': 0, 'rewind': 8, 'page': 0, 'verify_times': 0}
        state = self._matrix_selection
        if state['target'] != target:
            return self.round_fail('编队配置在选人期间发生变化，请重新运行')
        if state['phase'] == 'open':
            if not self.ctx.controller.click(main_area.rect.center):
                return self.round_retry('主战编队点击失败', wait=0.5)
            state['phase'] = 'clear'
            return self.round_wait('展开主战编队', wait=0.5)
        if state['phase'] == 'clear':
            labels = self.ctx.ocr_service.get_ocr_result_list(image=self.last_screenshot, rect=main_area.rect)
            labels = [item for item in labels if '主战' in item.data]
            if labels:
                if state['clear_times'] >= 6:
                    return self.round_fail('无法清空主战编队，请检查编队选择画面')
                if not self.ctx.controller.click(min(labels, key=lambda item: item.center.x).center):
                    return self.round_retry('取消主战角色点击失败', wait=0.5)
                state['clear_times'] += 1
                return self.round_wait('取消原主战角色', wait=0.5)
            if self._matrix_roster(main_area):
                return self.round_fail('原主战编队未清空，停止选人')
            state['phase'] = 'rewind'
        if state['phase'] == 'rewind':
            if state['rewind'] > 0:
                self.scroll_area('迷失之地-矩阵行动-编队选择', '代理人列表', direction='up')
                state['rewind'] -= 1
                return self.round_wait('返回代理人列表顶部', wait=0.3)
            state['page'] = 0
            state['phase'] = 'select'
        if state['phase'] == 'verify':
            expected = target[:state['index'] + 1]
            if self._matrix_roster(main_area) != expected:
                state['verify_times'] += 1
                if state['verify_times'] >= 4:
                    return self.round_fail('主战编队角色或顺序校验失败，停止选人')
                return self.round_wait('等待主战编队更新', wait=0.5)
            state['index'] += 1
            if state['index'] == len(target):
                return self.round_success('已按指定顺序组成主战编队')
            state['rewind'] = state['page']
            state['phase'] = 'rewind'
            return self.round_wait('准备选择下一个角色', wait=0.2)
        agent_id = target[state['index']]
        matches = match_team_agent_template(self.ctx, self.last_screenshot, agent_area.rect, [agent_id])
        if matches:
            match = max(matches, key=lambda item: item.confidence)
            if not self.ctx.controller.click(match.center):
                return self.round_retry('角色点击失败', wait=0.5)
            state['phase'] = 'verify'
            state['verify_times'] = 0
            return self.round_wait('等待所选角色加入主战编队', wait=0.5)
        if state['page'] >= 8:
            name = next(item.value.agent_name for item in AgentEnum if item.value.agent_id == agent_id)
            return self.round_fail(f'未找到指定角色：{name}；请确认已解锁该角色')
        self.scroll_area('迷失之地-矩阵行动-编队选择', '代理人列表', direction='down')
        state['page'] += 1
        return self.round_wait('翻页寻找指定角色', wait=0.3)

    def _matrix_roster(self, area):
        matches = match_team_agent_template(self.ctx, self.last_screenshot, area.rect)
        best = {}
        for match in matches:
            agent_id = match.data.agent_id
            if agent_id not in best or match.confidence > best[agent_id].confidence:
                best[agent_id] = match
        return [item.data.agent_id for item in sorted(best.values(), key=lambda item: item.center.x)]

    # 滑动x次 (滑慢点以免帧率低时可能出现的滑不到位)
    def swipe_multiple_times(self, area, swipe_num, wait, direction) -> None:
        for _ in range(swipe_num):
            screen_utils.scroll_area(self.ctx, area, direction, 0.75, 0.25, duration=1)
            time.sleep(wait)

    @node_from(from_name='矩阵行动-选择预备编队')
    @node_from(from_name='矩阵行动-选择代理人')
    @operation_node(name='矩阵行动-点击协战代理人')
    def matrix_click_support_agent(self) -> OperationRoundResult:
        """在矩阵行动页面点击协战代理人。"""
        return self.round_by_find_and_click_area(
            self.last_screenshot,
            '迷失之地-矩阵行动-编队选择',
            '协战代理人',
            success_wait=1,
            retry_wait=1,
        )

    @node_from(from_name='矩阵行动-点击协战代理人')
    @operation_node(name='矩阵行动-等待代理人列表', node_max_retry_times=300)
    def matrix_wait_support_panel(self) -> OperationRoundResult:
        ocr_result_map = self.ctx.ocr.run_ocr(self.last_screenshot)
        if self._find_ocr_text_mr(ocr_result_map, '代理人') is not None:
            return self.round_success('已出现代理人列表')
        return self.round_retry('等待代理人列表', wait=0.1)

    @node_from(from_name='矩阵行动-等待代理人列表')
    @operation_node(name='矩阵行动-选择协战代理人')
    def matrix_select_support_agent(self) -> OperationRoundResult:
        area = self.ctx.screen_loader.get_area('迷失之地-矩阵行动-编队选择', '代理人列表')
        support_team_area = self.ctx.screen_loader.get_area('迷失之地-矩阵行动-编队选择', '协战编队槽')
        support_team_property = self.ctx.screen_loader.get_area('迷失之地-矩阵行动-编队选择', '协战代理人属性')
        ocr_result_list = self.ctx.ocr_service.get_ocr_result_list(
            image=self.last_screenshot,
            rect=area.rect,
        )

        # 找UP代理人, 或者第一个60 (有时候up识别会不成功, up代理人会在第一个位置所以也可以点击第一个60)
        center: Point | None = None
        for ocr_text in ocr_result_list:
            if ocr_text.data.lower() == 'up':
                # up
                center = ocr_text.center
                break
            elif center is None and ocr_text.data.lower() == '60':
                # 第一个60
                center = ocr_text.center

        if center is None:
            return self.round_retry('未找到协战代理人', wait=0.5)
        self.ctx.controller.click(center)

        # 等待画面更新，重新截图OCR
        time.sleep(0.5)
        self.screenshot()
        # 在协战编队槽区域检测是否出现"协战"
        ocr_result_list = self.ctx.ocr_service.get_ocr_result_list(
            image=self.last_screenshot,
            rect=support_team_area.rect,
        )

        for ocr_text in ocr_result_list:
            if '协战' in ocr_text.data:
                self.ctx.lost_void.challenge_config.clear_artifact_priority_in_battle()
                # 检查协战代理人属性, 并添加到鸣徽选择的第一优先级中
                ocr_result_list_1 = self.ctx.ocr_service.get_ocr_result_list(
                    image=self.last_screenshot,
                    rect=support_team_property.rect,
                )
                for ocr_text_1 in ocr_result_list_1:
                    text = ocr_text_1.data.replace('【', '[')
                    if text[0] == '[':
                        text = text[1:3]
                    self.ctx.lost_void.challenge_config.artifact_priority_in_battle.append(text)
                    log.info('添加协战代理人属性武备至第一优先级: [' + text + ']')
                return self.round_success('已选择协战代理人')

        return self.round_retry('未找到协战', wait=0.5)

    @node_from(from_name='矩阵行动-选择协战代理人')
    @operation_node(name='矩阵行动-开始挑战')
    def matrix_start_challenge(self) -> OperationRoundResult:
        """在矩阵行动页面点击开始挑战。"""
        try:
            target = custom_matrix_agents(self.config)
            if target is None and self.ctx.lost_void.challenge_config.manually_choose_agent:
                target = resolve_agent_ids(self.ctx.lost_void.challenge_config.team_info)
        except ValueError as exc:
            return self.round_fail(str(exc))
        if target is not None:
            area = self.ctx.screen_loader.get_area('迷失之地-矩阵行动-编队选择', '主战编队槽')
            if self._matrix_roster(area) != target:
                return self.round_fail('挑战前主战编队校验失败，未开始挑战')
        return self.round_by_find_and_click_area(
            self.last_screenshot,
            '迷失之地-矩阵行动-编队选择',
            '按钮-开始挑战',
            success_wait=1,
            retry_wait=1,
        )

    # ========== 常规副本入口流程节点 ==========

    @node_from(from_name='识别悬赏委托完成进度', status=STATUS_AGAIN)
    @node_from(from_name='副本画面识别', status='副本模式不一致')
    @node_from(from_name='识别初始画面', status='已在常规入口')
    @operation_node(name='前往副本画面', node_max_retry_times=20, timeout_seconds=60)
    def goto_mission_screen(self) -> OperationRoundResult:
        wanted = self.config.mission_name
        if wanted not in MISSION_NAMES:
            return self.round_fail(f'常规入口不支持任务：{wanted}')
        actual = detail_mission(self.ctx, self.last_screenshot)
        if actual == wanted:
            self._mission_returned_from = None
            self.ctx.screen_loader.update_current_screen_name(f'迷失之地-{actual}')
            log.info('副本模式核验通过：设定=%s，实际=%s', wanted, actual)
            return self.round_success(f'迷失之地-{actual}')

        controller = self.ctx.controller
        if actual in MISSION_NAMES:
            if self._mission_returned_from == actual:
                return self.round_retry('等待返回常规入口', wait=1)
            if self._mission_recoveries >= 3:
                path = self.save_screenshot(prefix='lost_void_wrong_mission')
                return self.round_fail(f'副本模式不一致：设定{wanted}，实际{actual}；截图{path}')
            self._mission_recoveries += 1
            log.warning('副本模式不一致：设定=%s，实际=%s；返回入口重新选择（%d/3）',
                        wanted, actual, self._mission_recoveries)
            if getattr(controller, 'background_mode', False):
                self._mission_pad('back')
            else:
                result = self.round_by_click_area(f'迷失之地-{actual}', '菜单-返回')
                if not result.is_success:
                    return self.round_retry('返回常规入口失败', wait=1)
            self._mission_returned_from = actual
            return self.round_wait('返回常规入口重新选择', wait=1)

        if (getattr(controller, 'background_mode', False)
                and wanted in MISSION_NAMES and self._entry_header() == '迷失之地-入口-周期'):
            requests = getattr(self, '_regular_switch_requests', 0)
            if requests >= 3:
                return self.round_fail('手柄切换常规入口未生效')
            self._mission_pad('regular')
            self._regular_switch_requests = requests + 1
            return self.round_wait('手柄切换常规入口，等待新画面核验', wait=.8)
        titles = menu_matches(self.ctx, self.last_screenshot)
        if len(titles) >= 2 and wanted in titles:
            if getattr(controller, 'background_mode', False):
                focus = focused_card(self.last_screenshot)
                point = titles[wanted].center
                if focus is None:
                    self._mission_pad('right')
                    return self.round_wait('等待手柄焦点出现，不确认未选中的入口', wait=.5)
                if focus.x1 <= point.x <= focus.x2 and focus.y1 <= point.y <= focus.y2:
                    self._mission_pad('confirm')
                    log.info('手柄焦点已核验：%s，确认进入详情', wanted)
                else:
                    direction = ('up' if focus.y1 > point.y else
                                 'right' if focus.center.x < point.x else 'left')
                    self._mission_pad(direction)
                    return self.round_wait(f'移动手柄焦点至{wanted}，等待新帧核验', wait=.5)
            else:
                point = titles[wanted].center
                if not controller.click(point):
                    return self.round_retry(f'点击{wanted}入口失败', wait=1)
                log.info('按当前帧标题选择入口：任务=%s，标准坐标=(%d,%d)', wanted, point.x, point.y)
            self._mission_returned_from = None
            # 不将投递成功视为进入成功，也不预写目标画面名称。
            return self.round_wait(f'等待核验{wanted}详情', wait=1)

        result = self.round_by_goto_screen(screen_name=f'迷失之地-{wanted}', screen_switch_debounce=1)
        if result.is_success:
            return self.round_retry(f'尚未识别到{wanted}详情标题', wait=1)
        return result

    def _mission_pad(self, action):
        ds4 = self.ctx.game_config.background_gamepad_type == 'ds4'
        key = {'back': 'ds4_circle' if ds4 else 'xbox_b',
               'regular': 'ds4_r1' if ds4 else 'xbox_rb',
               'confirm': 'ds4_cross' if ds4 else 'xbox_a',
               'left': 'ds4_dpad_left' if ds4 else 'xbox_dpad_left',
               'right': 'ds4_dpad_right' if ds4 else 'xbox_dpad_right',
               'up': 'ds4_dpad_up' if ds4 else 'xbox_dpad_up',
               'down': 'ds4_dpad_down' if ds4 else 'xbox_dpad_down',
               'strategy': 'ds4_triangle' if ds4 else 'xbox_y',
               'claim_all': 'ds4_square' if ds4 else 'xbox_x',
               'next': 'ds4_options' if ds4 else 'xbox_start'}[action]
        self.ctx.controller.btn_press(key, press_time=.12)

    @node_from(from_name='前往副本画面')
    @node_from(from_name='识别初始画面', status='已在目标副本详情')
    @operation_node(name='副本画面识别')
    def check_for_mission(self) -> OperationRoundResult:
        """
        针对不同的副本类型 进行对应的所需识别
        :return:
        """
        mission_name = self.config.mission_name

        actual = detail_mission(self.ctx, self.last_screenshot)
        if actual != mission_name:
            log.warning('副本画面复核未通过：设定=%s，实际=%s', mission_name, actual or '未识别')
            return self.round_success('副本模式不一致')

        # 如果是特遣调查 则额外识别当期UP角色
        if mission_name == '特遣调查':
            if (not self.ctx.lost_void.challenge_config.choose_team_by_priority
                    or self.run_record.complete_task_force_with_up):
                self.priority_agent_list = []
                log.info('未要求按 UP 角色选择编队，沿用设定编队')
                return self.round_success()
            area = self.ctx.screen_loader.get_area('迷失之地-特遣调查', '区域-代理人头像')
            match_agent_list: list[MatchResult] = match_team_agent_template(self.ctx, self.last_screenshot, area.rect, None)

            # 从左往右排序
            match_agent_list.sort(key=lambda x: x.left_top.x)
            self.priority_agent_list = [x.data for x in match_agent_list]

            display_name: str = ', '.join([i.agent_name for i in self.priority_agent_list])
            log.info(f'当前识别UP代理人列表: [{display_name}]')

            if len(self.priority_agent_list) > 0:
                return self.round_success()
            else:
                return self.round_retry(status='未识别UP代理人', wait=1)
        else:
            return self.round_success()

    @node_from(from_name='副本画面识别')
    @operation_node(name='打开调查战略列表')
    def open_strategy_list(self) -> OperationRoundResult:
        if getattr(self.ctx.controller, 'background_mode', False):
            if detail_mission(self.ctx, self.last_screenshot) != self.config.mission_name:
                return self.round_retry('等待目标副本详情，未打开战略', wait=.5)
            self._mission_pad('strategy')
            return self.round_success('手柄打开调查战略', wait=1)
        return self.round_by_click_area(f'迷失之地-{self.config.mission_name}', '按钮-调查战略',
                                        success_wait=1, retry_wait=1)

    @node_from(from_name='打开调查战略列表')
    @operation_node(name='选择调查战略', timeout_seconds=90)
    def choose_strategy(self) -> OperationRoundResult:
        if (getattr(self.ctx.controller, 'background_mode', False)
                and detail_mission(self.ctx, self.last_screenshot) == self.config.mission_name):
            return self.round_success(f'迷失之地-{self.config.mission_name}')
        current_screen_name = self.check_and_update_current_screen(
            self.last_screenshot, screen_name_list=['迷失之地-战线肃清', '迷失之地-特遣调查']
        )
        if current_screen_name is not None:
            return self.round_success(current_screen_name)

        # [DEBUG] 打印关键决策参数
        config = self.ctx.lost_void.challenge_config
        log.debug(f"【决策检查】 追新模式: {config.chase_new_mode}, "
                  f"当前挑战配置: {config.module_name}, "
                  f"预设调查战略: {config.investigation_strategy}")

        # 追新模式逻辑
        if config.chase_new_mode:
            return self._choose_strategy_by_chase_new_mode()
        # 原有逻辑
        else:
            return self._choose_strategy_by_ocr()

    def _choose_strategy_by_chase_new_mode(self) -> OperationRoundResult:
        """
        追新模式下的选择逻辑
        """
        # 优先寻找无等级战略
        log.debug("【追新模式】 开始执行无等级圈圈流水线分析...")
        no_level_context = self.ctx.cv_service.run_pipeline('调查战略无等级圈圈', self.last_screenshot)
        if no_level_context.is_success and no_level_context.contours:
            target_contour = no_level_context.contours[0]
            M = cv2.moments(target_contour)
            if M["m00"] == 0:
                log.debug("【追新模式】 轮廓面积为零，跳过无等级战略检测")
            else:
                center_x = int(M["m10"] / M["m00"])
                center_y = int(M["m01"] / M["m00"])
                offset_x, offset_y = no_level_context.crop_offset
                click_pos = Point(center_x + offset_x, center_y + offset_y)
                log.debug(
                    f"【追新模式】 找到无等级战略，点击坐标: {click_pos} (相对: ({center_x}, {center_y}), 偏移: {no_level_context.crop_offset})"
                )
                if getattr(self.ctx.controller, 'background_mode', False):
                    return self._select_strategy_with_pad(click_pos)
                self.ctx.controller.click(click_pos)
                time.sleep(1)
                return self._click_confirm_after_strategy_chosen()

        log.debug("【追新模式】 未找到无等级战略，使用原有逻辑...")

        swipe_attempts = 0
        MAX_SWIPES = 3

        while swipe_attempts < MAX_SWIPES:
            log.debug("【追新模式】 开始执行CV流水线分析...")
            frame_context = self.ctx.cv_service.run_pipeline('调查战略等级圈圈', self.last_screenshot)
            digit_context = self.ctx.cv_service.run_pipeline('调查战略等级分析', self.last_screenshot)

            if not frame_context.is_success or not frame_context.contours:
                log.debug("【追新模式】 未找到任何战略外框，执行滑动...")
                self._swipe_strategy_list()
                swipe_attempts += 1
                continue

            target_contour_to_click = None
            log.debug(f"【追新模式】 找到 {len(frame_context.contours)} 个战略外框，"
                      f"{len(digit_context.contours) if digit_context.is_success and digit_context.contours else 0} 个等级数字。开始匹配...")
            for frame_contour in frame_context.contours:
                frame_rect = cv2.boundingRect(frame_contour)
                found_digit_contour = None

                if digit_context.is_success and digit_context.contours:
                    for digit_contour in digit_context.contours:
                        M = cv2.moments(digit_contour)
                        if M["m00"] == 0:
                            continue
                        center_x = int(M["m10"] / M["m00"])
                        center_y = int(M["m01"] / M["m00"])

                        if (frame_rect[0] < center_x < frame_rect[0] + frame_rect[2] and
                                frame_rect[1] < center_y < frame_rect[1] + frame_rect[3]):
                            found_digit_contour = digit_contour
                            break

                if found_digit_contour is None:
                    log.debug("【追新模式】 找到一个未满级/无等级目标，准备点击。")
                    target_contour_to_click = frame_contour
                    break

            if target_contour_to_click is not None:
                M = cv2.moments(target_contour_to_click)
                center_x = int(M["m10"] / M["m00"])
                center_y = int(M["m01"] / M["m00"])
                offset_x, offset_y = frame_context.crop_offset
                click_pos = Point(center_x + offset_x, center_y + offset_y)
                log.debug(
                    f"【追新模式】 点击目标坐标: {click_pos} (相对: ({center_x}, {center_y}), 偏移: {frame_context.crop_offset})"
                )
                if getattr(self.ctx.controller, 'background_mode', False):
                    return self._select_strategy_with_pad(click_pos)
                self.ctx.controller.click(click_pos)
                time.sleep(1)
                return self._click_confirm_after_strategy_chosen()

            log.debug("【追新模式】 当前屏幕无可选择目标，执行滑动...")
            self._swipe_strategy_list()
            self.screenshot()
            swipe_attempts += 1

        # 回退逻辑: 选择第一个
        frame_context = self.ctx.cv_service.run_pipeline('调查战略等级圈圈', self.last_screenshot)
        if frame_context.is_success and frame_context.contours:
            target_contour = frame_context.contours[0]
            M = cv2.moments(target_contour)
            center_x = int(M["m10"] / M["m00"])
            center_y = int(M["m01"] / M["m00"])
            offset_x, offset_y = frame_context.crop_offset
            click_pos = Point(center_x + offset_x, center_y + offset_y)
            log.debug(f"【追新模式-回退】 点击目标坐标: {click_pos} (相对: ({center_x}, {center_y}), 偏移: {frame_context.crop_offset})")
            if getattr(self.ctx.controller, 'background_mode', False):
                return self._select_strategy_with_pad(click_pos)
            self.ctx.controller.click(click_pos)
            time.sleep(1)
            return self._click_confirm_after_strategy_chosen()

        return self.round_fail("追新模式失败：未找到任何可选择的调查战略")

    def _swipe_strategy_list(self) -> None:
        """
        滑动调查战略列表
        """
        # 调查战略的详情打开之后鼠标不能在详情处滑, 会滑不动
        if getattr(self.ctx.controller, 'background_mode', False):
            self._mission_pad('right')
            time.sleep(.5)
            return
        start = Point(self.ctx.controller.standard_width // 2, self.ctx.controller.standard_height // 2.5)
        end = start + Point(-800, 0)
        self.ctx.controller.drag_to(start=start, end=end)
        time.sleep(1)

    def _click_confirm_after_strategy_chosen(self) -> OperationRoundResult:
        """
        选择战略后，点击确定按钮
        """
        ocr_result_map = self.ctx.ocr.run_ocr(self.last_screenshot)
        ocr_word_list = list(ocr_result_map.keys())
        idx = str_utils.find_best_match_by_difflib(gt('确定', 'game'), ocr_word_list)
        if idx is None or idx < 0:
            return self.round_retry(status='未识别到确定按钮', wait=1)

        target_pos = ocr_result_map[ocr_word_list[idx]].max.center
        if getattr(self.ctx.controller, 'background_mode', False):
            self._mission_pad('confirm')
            return self.round_wait('手柄确认调查战略', wait=1)
        self.ctx.controller.click(target_pos)
        time.sleep(1)

        return self.round_wait(status='确定')

    def _choose_strategy_by_ocr(self) -> OperationRoundResult:
        """
        通过OCR识别选择调查战略
        """
        ocr_result_map = self.ctx.ocr.run_ocr(self.last_screenshot)
        ocr_word_list = list(ocr_result_map.keys())
        target = gt(self.ctx.lost_void.challenge_config.investigation_strategy, 'game')
        idx = str_utils.find_best_match_by_difflib(target, ocr_word_list)

        if idx is None or idx < 0:
            is_after = str_utils.is_target_after_ocr_list(
                target_cn=self.ctx.lost_void.challenge_config.investigation_strategy,
                order_cn_list=[i.strategy_name for i in self.ctx.lost_void.investigation_strategy_list],
                ocr_result_list=ocr_word_list
            )

            if getattr(self.ctx.controller, 'background_mode', False):
                self._mission_pad('right' if is_after else 'left')
                return self.round_retry('手柄翻页寻找目标调查战略', wait=.5)
            start = Point(self.ctx.controller.standard_width // 2, self.ctx.controller.standard_height // 2)
            end = start + Point(800 * (-1 if is_after else 1), 0)
            self.ctx.controller.drag_to(start=start, end=end)
            return self.round_retry(status='未识别到目标调查战略', wait=1)

        target_pos = ocr_result_map[ocr_word_list[idx]].max.center
        if getattr(self.ctx.controller, 'background_mode', False):
            return self._select_strategy_with_pad(target_pos)
        self.ctx.controller.click(target_pos)
        time.sleep(1)

        return self._click_confirm_after_strategy_chosen()

    def _select_strategy_with_pad(self, point):
        focus = focused_card(self.last_screenshot)
        if focus is None:
            self._mission_pad('right')
            return self.round_wait('等待调查战略手柄焦点', wait=.5)
        if focus.x1 <= point.x <= focus.x2:
            self._mission_pad('confirm')
            return self.round_wait('确认已选调查战略，等待详情画面', wait=1)
        self._mission_pad('right' if focus.center.x < point.x else 'left')
        return self.round_wait('手柄定位调查战略，等待新帧核验', wait=.5)

    @node_from(from_name='选择调查战略')
    @operation_node(name='选择周期增益')
    def choose_buff(self) -> OperationRoundResult:
        mission_name = self.config.mission_name
        if mission_name == '特遣调查':
            return self.round_success(status='无需选择')
        buff_no = self.ctx.lost_void.challenge_config.period_buff_no
        if getattr(self.ctx.controller, 'background_mode', False):
            return self._choose_buff_with_pad(('第一个', '第二个', '第三个').index(buff_no))
        return self.round_by_click_area('迷失之地-战线肃清', f'周期增益-{buff_no}',
                                        success_wait=1, retry_wait=1)

    def _choose_buff_with_pad(self, wanted):
        """Mouse messages don't select cards: A focuses the list, D-pad moves, A selects."""
        selected, focus = period_buff_state(self.last_screenshot)
        if selected == wanted:
            self._buff_requests = 0
            return self.round_success(f'已核验周期增益：{wanted + 1}')
        requests = getattr(self, '_buff_requests', 0)
        if requests >= 8:
            return self.round_fail('手柄选择周期增益未生效')
        self._buff_requests = requests + 1
        if focus is None or focus == wanted:
            self._mission_pad('confirm')
            return self.round_wait('手柄确认周期增益焦点，等待新帧核验', wait=.8)
        self._mission_pad('down' if focus < wanted else 'up')
        return self.round_wait('手柄移动周期增益焦点，等待新帧核验', wait=.5)

    @node_from(from_name='选择周期增益')
    @operation_node(name='下一步')
    def click_next(self) -> OperationRoundResult:
        if getattr(self.ctx.controller, 'background_mode', False):
            ready = self.round_by_find_area(self.last_screenshot, '通用-出战', '按钮-出战')
            if ready.is_success:
                return ready
            if detail_mission(self.ctx, self.last_screenshot) != self.config.mission_name:
                return self.round_retry('等待目标副本下一步', wait=.5)
            self._mission_pad('next')
            return self.round_wait('手柄下一步，等待出战画面', wait=1)
        return self.round_by_find_and_click_area(screen_name='通用-出战', area_name='按钮-下一步',
                                                 until_find_all=[('通用-出战', '按钮-出战')],
                                                 success_wait=1, retry_wait=1)

    @node_from(from_name='下一步')
    @operation_node(name='检查预备编队')
    def check_predefined_team(self) -> OperationRoundResult:
        """
        根据配置判断是否需要切换编队
        :return:
        """
        self.use_priority_agent = False
        mission_name = self.config.mission_name
        if mission_name == '特遣调查':
            # 本周第一次挑战 且开启了优先级配队
            if (self.ctx.lost_void.challenge_config.choose_team_by_priority
                    and not self.run_record.complete_task_force_with_up):
                self.ctx.lost_void.predefined_team_idx = self.get_target_team_idx_by_priority()
                if self.ctx.lost_void.predefined_team_idx != -1:
                    self.use_priority_agent = True
                    return self.round_success(status='需选择预备编队')

        # 配置中选择特定编队
        if self.ctx.lost_void.challenge_config.predefined_team_idx != -1:
            self.ctx.lost_void.predefined_team_idx = self.ctx.lost_void.challenge_config.predefined_team_idx
            return self.round_success(status='需选择预备编队')

        return self.round_success(status='无需选择预备编队')

    def get_target_team_idx_by_priority(self) -> int:
        """
        根据当前识别的优先代理人 选择最合适的预备编队
        :return:
        """
        best_match_team_idx: int = self.ctx.lost_void.challenge_config.predefined_team_idx  # 如果都没匹配 使用默认的预备编队
        best_match_agent_cnt: int = 0
        for idx, team in enumerate(self.ctx.team_config.team_list):
            match_agent_cnt: int = 0
            for agent in self.priority_agent_list:
                if agent.agent_id in team.agent_id_list:
                    match_agent_cnt += 1

            if match_agent_cnt > best_match_agent_cnt:
                best_match_team_idx = idx
                best_match_agent_cnt = match_agent_cnt

        return best_match_team_idx

    @node_from(from_name='检查预备编队', status='需选择预备编队')
    @operation_node(name='选择预备编队')
    def choose_predefined_team(self) -> OperationRoundResult:
        op = ChoosePredefinedTeam(self.ctx, target_team_idx_list=[self.ctx.lost_void.predefined_team_idx])
        return self.round_by_op_result(op.execute())

    @node_from(from_name='检查预备编队', status='无需选择预备编队')
    @node_from(from_name='选择预备编队')
    @operation_node(name='出战')
    def deploy(self) -> OperationRoundResult:
        self.next_region_type = LostVoidRegionType.ENTRY
        self.ctx.lost_void.in_start_room = True
        op = Deploy(self.ctx)
        return self.round_by_op_result(op.execute())

    @node_from(from_name='识别初始画面', status='迷失之地-大世界')
    @node_from(from_name='出战')
    @node_from(from_name='矩阵行动-开始挑战')
    @operation_node(name='加载自动战斗配置')
    def load_auto_op(self) -> OperationRoundResult:
        self.ctx.auto_battle_context.init_auto_op(
            sub_dir='auto_battle',
            op_name=self.ctx.lost_void.get_auto_op_name(),
        )
        return self.round_success()

    @node_from(from_name='加载自动战斗配置')
    @node_from(from_name='层间移动')
    @operation_node(name='层间移动')
    def run_level(self) -> OperationRoundResult:
        log.info(f'推测楼层类型 {self.next_region_type.value.value}')
        op = LostVoidRunLevel(self.ctx, self.next_region_type)
        op_result = op.execute()
        if op_result.success:
            if op_result.status in (LostVoidRunLevel.STATUS_NEXT_LEVEL, LostVoidRunLevel.STATUS_COMPLETE):
                self.ctx.lost_void.in_start_room = False
            if op_result.status == LostVoidRunLevel.STATUS_NEXT_LEVEL:
                self.ctx.lost_void.had_interacted_ophelia_on_current_level = False
                self.ctx.lost_void.completed_npc_names = set()
                if op_result.data is not None:
                    self.next_region_type = LostVoidRegionType.from_value(op_result.data)
                else:
                    self.next_region_type = LostVoidRegionType.ENTRY
            elif op_result.status == LostVoidRunLevel.STATUS_COMPLETE:
                self.ctx.lost_void.had_interacted_ophelia_on_current_level = False
                self.ctx.lost_void.completed_npc_names = set()
                self.next_region_type = LostVoidRegionType.ENTRY

        return self.round_by_op_result(op_result)

    @node_from(from_name='层间移动', status=LostVoidRunLevel.STATUS_COMPLETE)
    @operation_node(name='通关后处理', timeout_seconds=180)
    def after_complete(self) -> OperationRoundResult:
        if getattr(self.ctx.controller, 'background_mode', False) and battle_result(self.ctx, self.last_screenshot) == '完成':
            if failed_grade(self.ctx, self.last_screenshot):
                return self.round_fail('失败结算不计完成次数')
            requests = getattr(self, '_final_result_requests', 0)
            if requests >= 3:
                return self.round_fail('最终结算确认未生效')
            self._final_result_requests = requests + 1
            ds4 = self.ctx.game_config.background_gamepad_type == 'ds4'
            self.ctx.controller.btn_press('ds4_circle' if ds4 else 'xbox_b', press_time=.12)
            return self.round_wait('仍在最终结算，确认完成并等待入口核验', wait=1)
        result = self._wait_for_lost_void_entry()
        if not result.is_success:
            return result

        self.run_record.add_complete_times()
        self._final_result_requests = 0
        if self.use_priority_agent:
            self.run_record.complete_task_force_with_up = True

        return self.round_success()

    def _find_ocr_text_mr(self, ocr_result_map: dict[str, MatchResultList], target_text: str) -> MatchResult | None:
        target = gt(target_text, 'game')
        ocr_word_list = list(ocr_result_map.keys())

        idx = str_utils.find_best_match_by_difflib(target, ocr_word_list, cutoff=0.5)
        if idx is not None and idx >= 0:
            mrl = ocr_result_map[ocr_word_list[idx]]
            if mrl.max is not None:
                return mrl.max

        for ocr_word, mrl in ocr_result_map.items():
            if str_utils.find_by_lcs(target, ocr_word, percent=0.6) and mrl.max is not None:
                return mrl.max

        return None

    @node_from(from_name='识别悬赏委托完成进度', status=STATUS_ENOUGH_TIMES)
    @operation_node(name='打开悬赏委托')
    def open_reward_list(self) -> OperationRoundResult:
        if getattr(self.ctx.controller, 'background_mode', False):
            # Mouse messages don't open this Unity panel; the entry shows a Y prompt instead.
            if not self.round_by_find_area(self.last_screenshot, '迷失之地-入口', '按钮-悬赏委托').is_success:
                self._reward_list_requests = 0
                return self.round_success('悬赏委托已打开')
            requests = getattr(self, '_reward_list_requests', 0)
            if requests >= 3:
                return self.round_fail('手柄打开悬赏委托未生效')
            self._reward_list_requests = requests + 1
            self._mission_pad('strategy')
            return self.round_wait('手柄打开悬赏委托，等待列表画面', wait=1)
        return self.round_by_find_and_click_area(screen_name='迷失之地-入口', area_name='按钮-悬赏委托',
                                                 until_not_find_all=[('迷失之地-入口', '按钮-悬赏委托')],
                                                 success_wait=1, retry_wait=1)

    @node_from(from_name='打开悬赏委托')
    @node_notify(when=NotifyTiming.CURRENT_DONE)
    @operation_node(name='全部领取', node_max_retry_times=2)
    def claim_all(self) -> OperationRoundResult:
        if getattr(self.ctx.controller, 'background_mode', False):
            result = self.round_by_find_area(self.last_screenshot, '迷失之地-入口', '按钮-悬赏委托-全部领取')
            if not result.is_success:
                return self.round_retry('未识别到全部领取', wait=0.5)
            self._mission_pad('claim_all')
            return self.round_success('手柄全部领取', wait=1)
        return self.round_by_find_and_click_area(screen_name='迷失之地-入口', area_name='按钮-悬赏委托-全部领取',
                                                 success_wait=1, retry_wait=0.5)

    @node_from(from_name='全部领取')
    @node_from(from_name='全部领取', success=False)
    @operation_node(name='完成后返回')
    def back_at_last(self) -> OperationRoundResult:
        op = BackToNormalWorld(self.ctx)
        return self.round_by_op_result(op.execute())


def __debug():
    ctx = ZContext()
    ctx.init()
    ctx.run_context.current_app_id = lost_void_const.APP_ID
    ctx.run_context.start_running()
    op = LostVoidApp(ctx, lost_void_debug=True, next_region_type = LostVoidRegionType.FRIENDLY_TALK)
    op.execute()


if __name__ == '__main__':
    __debug()
