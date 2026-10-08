# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/application/random_play/random_play_app.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
import difflib
import time
from typing import ClassVar

from cv2.typing import MatLike

from onedragon.base.config.config_item import get_config_item_from_enum
from onedragon.base.geometry.point import Point
from src.background_navigation import pad_press, menu_words, selected_tab
from onedragon.base.geometry.rectangle import Rect
from onedragon.base.matcher.match_result import MatchResult
from onedragon.base.operation.application import application_const
from onedragon.base.operation.operation_edge import node_from
from onedragon.base.operation.operation_node import operation_node
from onedragon.base.operation.operation_notify import NotifyTiming, node_notify
from onedragon.base.operation.operation_round_result import OperationRoundResult
from onedragon.utils import cv2_utils
from onedragon.utils.i18_utils import gt
from onedragon.utils.log_utils import log
from zzz_od.application.random_play import random_play_const
from zzz_od.application.random_play.random_play_config import (
    RANDOM_AGENT_NAME,
    RandomPlayConfig,
    RandomPlayTransportPoint,
)
from zzz_od.application.zzz_application import ZApplication
from zzz_od.context.zzz_context import ZContext
from zzz_od.game_data.agent import Agent, AgentEnum
from zzz_od.operation.back_to_normal_world import BackToNormalWorld
from zzz_od.operation.transport import Transport
from zzz_od.operation.turning.turn_compensation import AngleTurnCompensator
from zzz_od.operation.turning.turn_to_angle import turn_to_angle


class RandomPlayApp(ZApplication):

    """录像店营业:录像带店日常经营(宣传/营业/结算)。无消耗,产出菲林与丁尼。"""

    STATUS_ALL_VIDEO_CHOOSE: ClassVar[str] = '已选择全部录像带'
    STATUS_ALREADY_RUNNING: ClassVar[str] = '正在营业'

    def __init__(self, ctx: ZContext):
        ZApplication.__init__(
            self,
            ctx=ctx,
            app_id=random_play_const.APP_ID,
            op_name=random_play_const.APP_NAME,
        )

        self.config: RandomPlayConfig = self.ctx.run_context.get_config(
            app_id=self.app_id,
            instance_idx=self.ctx.current_instance_idx,
            group_id=application_const.DEFAULT_GROUP_ID,
        )

    def handle_init(self) -> None:
        """
        执行前的初始化 由子类实现
        注意初始化要全面 方便一个指令重复使用
        """
        self._all_video_themes: list[str] = [
            '纪实', '怀旧', '冒险', '幻想', '喜剧', '动作', '惊悚', '悬疑',
            '访谈', '都市', '时尚', '灾难', '悲剧', '亲情', '广告', '爱情',
        ]
        self._need_video_themes: list[str] = []
        self._current_idx: int = 0
        self.turn_compensator: AngleTurnCompensator = AngleTurnCompensator(self.ctx.controller)
        self.retried_transport: bool = False
        self._pad_promoter_open=0
        self._pad_video_open=0
        self._pad_start=0
        self._business_failure=None
        self._pad_promoter_name=None
        self._pad_promoter_confirms=0
        self._pad_recommended=0
        self._pad_business_confirms=0

    def _business_page(self):
        tabs=menu_words(self,Rect(1200,10,1900,100))
        footer=menu_words(self,Rect(1450,840,1900,1000))
        return '经营状况' in tabs and any(w in footer for w in ('开始营业','正在营业'))

    def _business_cards(self):
        return menu_words(self,Rect(870,510,1800,570))

    def _promoter_page(self):
        # The full-width footer downscales the small confirm text below OCR's
        # detection size. Read the two independent labels at their native size.
        title = menu_words(self,Rect(90,990,280,1060))
        confirm = menu_words(self,Rect(1665,995,1755,1055))
        return '选择宣传员' in title and '确定' in confirm

    def _business_focus(self):
        import cv2
        import numpy as np
        part=self.last_screenshot[560:855,850:1810]
        mask=((part[:,:,0]>150)&(part[:,:,1]>140)&(part[:,:,2]<100)).astype(np.uint8)
        contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        boxes=[cv2.boundingRect(c) for c in contours]
        boxes=[b for b in boxes if b[2]>150 and b[3]>240]
        if len(boxes)!=1:
            return None
        x=850+boxes[0][0]+boxes[0][2]/2
        return min(range(4),key=lambda i:abs(x-(965,1200,1440,1680)[i]))

    @node_from(from_name='交互对话', success=False)
    @node_from(from_name='等待经营画面加载', success=False)
    @operation_node(name='传送', is_start_node=True)
    def transport(self) -> OperationRoundResult:
        if self.previous_node.name in {'交互对话', '等待经营画面加载'}:
            if self.retried_transport:
                return self.round_fail(status='进入经营画面失败，重传送超限')
            self.retried_transport = True

        self.turn_compensator.clear_pending_sample()
        item = get_config_item_from_enum(RandomPlayTransportPoint, self.config.transport_point)
        op = Transport(self.ctx, item.area_name, item.tp_name)
        return self.round_by_op_result(op.execute())

    @node_from(from_name='传送')
    @operation_node(name='移动交互', node_max_retry_times=10)
    def move_and_interact(self) -> OperationRoundResult:
        """
        录像店-柜台 / 布亚斯特城区-录像店营业点：转向正东后前移再交互
        澄辉坪-录像店营业点：传送落点已正对入口，直接交互
        :return:
        """
        if self.config.transport_point in {
            RandomPlayTransportPoint.POINT_1.value.value,
            RandomPlayTransportPoint.POINT_3.value.value,
        }:
            result = turn_to_angle(self, target_angle=0, turn_status='转向正东')
            if not result.is_success:
                return result
            self.ctx.controller.move_w(press=True, press_time=1, release=True)

        time.sleep(1) # 防止交互无效 issue #2405 #2395 #2328
        self.ctx.controller.interact(press=True, press_time=0.2, release=True)

        return self.round_success(wait=1)

    @node_from(from_name='移动交互')
    @operation_node(name='交互对话', node_max_retry_times=10)
    def handle_interaction_dialog(self) -> OperationRoundResult:
        # 录像店-柜台交互后没有选项对话，直接交给经营画面加载节点
        if self.config.transport_point == RandomPlayTransportPoint.POINT_1.value.value:
            return self.round_success()

        # 录像店营业点交互后的选项对话框，优先选择“查看经营状况”
        area = self.ctx.screen_loader.get_area('影像店营业', '右侧选项区域')
        result = self.round_by_ocr_and_click(self.last_screenshot, '查看经营状况', area=area)
        if result.is_success:
            return self.round_success(status=result.status, wait=1)

        # (布亚斯特城区-录像店营业点)需要推进一次对话框，右侧选项区域才会出现“查看经营状况”
        result = self.round_by_click_area('影像店营业', '对话框标题')
        if result.is_success:
            return self.round_retry(status='继续对话', wait=1)
        return result

    @node_from(from_name='交互对话')
    @operation_node(name='等待经营画面加载', node_max_retry_times=10)
    def wait_run(self) -> OperationRoundResult:
        # 每日首次。点完关闭按钮后回到本节点重判，防止昨日账本残影或未关闭
        result = self.round_by_find_area(self.last_screenshot, '影像店营业', '昨日账本')
        if result.is_success:
            if getattr(self.ctx.controller,'background_mode',False):
                pad_press(self,'b')
                return self.round_retry('手柄关闭昨日账本，等待经营画面',wait=1)
            self.round_by_find_and_click_area(self.last_screenshot, '影像店营业', '按钮-关闭')
            return self.round_retry(wait=1)
        if getattr(self.ctx.controller,'background_mode',False):
            current=selected_tab(self,Rect(1200,10,1900,100),('经营状况','无人咨询','咨询中'))
            if current=='经营状况':
                return self.round_success('已核验经营状况页',wait=.5)
            if current in ('无人咨询','咨询中'):
                pad_press(self,'lb')
                return self.round_retry('切换经营状况，等待实际页签',wait=1)
            return self.round_retry('等待经营画面',wait=1)
        # 识别到"经营状况"就点击一下以保证在该分支。二次运行时，有极低概率"无人咨询"变成"咨询中"并被默认跳转
        result = self.round_by_find_and_click_area(self.last_screenshot, '影像店营业', '经营状况')
        if result.is_success:
            return self.round_success(wait=1)

        return self.round_retry(status='等待经营画面', wait=1)

    @node_from(from_name='等待经营画面加载')
    @operation_node(name='识别营业状态')
    def check_running(self) -> OperationRoundResult:
        if getattr(self.ctx.controller,'background_mode',False):
            words=menu_words(self,Rect(1450,840,1900,1000))
            if '正在营业' in words:
                return self.round_success(self.STATUS_ALREADY_RUNNING)
            if '开始营业' in words:
                return self.round_success('已核验开始营业按钮')
            return self.round_retry('等待实际营业状态',wait=1)
        result = self.round_by_find_area(self.last_screenshot, '影像店营业', '正在营业')
        if result.is_success:
            return self.round_success(RandomPlayApp.STATUS_ALREADY_RUNNING)
        result = self.round_by_find_area(self.last_screenshot, '影像店营业', '开始营业')
        if result.is_success:
            return self.round_success()

        return self.round_retry(status='等待营业状态', wait=1)

    @node_from(from_name='识别营业状态', status=STATUS_ALREADY_RUNNING)
    @node_from(from_name='点击宣传员入口', success=False)
    @operation_node(name='关闭经营页面')
    def close_business_page(self) -> OperationRoundResult:
        if self.previous_node.name=='点击宣传员入口' and not self.previous_node.is_success:
            self._business_failure=self.previous_node.status or '宣传员入口未完成'
        if getattr(self.ctx.controller,'background_mode',False):
            return self.round_by_op_result(BackToNormalWorld(self.ctx).execute())
        return self.round_by_find_and_click_area(self.last_screenshot, '影像店营业', '返回',
                                                 retry_wait=1)

    @node_from(from_name='识别营业状态')
    @operation_node(name='点击宣传员入口',node_max_retry_times=12)
    def click_promoter_entry(self) -> OperationRoundResult:
        """
        在经营状况页面 点击代理人的位置
        :return:
        """
        if getattr(self.ctx.controller,'background_mode',False):
            if self._promoter_page():
                return self.round_success('已打开宣传员列表')
            if not self._business_page():
                return self.round_retry('未核验宣传员卡片焦点，未操作',wait=1)
            allowed=(self.config.agent_name_1,self.config.agent_name_2)
            promoter=menu_words(self,Rect(870,510,1060,570))
            if promoter and '选择宣传员' not in promoter and (RANDOM_AGENT_NAME in allowed or any(n in allowed for n in promoter)):
                self._pad_promoter_name=promoter[0]
                return self.round_success('已核验当前宣传员符合配置')
            focus=self._business_focus()
            if focus is None:
                return self.round_retry('未核验宣传员卡片焦点，未操作',wait=1)
            if focus!=0:
                pad_press(self,'dpad_left')
                return self.round_retry('手柄选择宣传员卡片，等待实际焦点',wait=.6)
            if self._pad_promoter_open>=3:
                return self.round_fail('宣传员入口确认未生效')
            pad_press(self,'a');self._pad_promoter_open+=1
            return self.round_retry('手柄打开宣传员列表，等待实际页面',wait=1)
        return self.round_by_click_area('影像店营业', '宣传员入口',
                                        retry_wait=1)

    @node_from(from_name='点击宣传员入口')
    @operation_node(name='选择宣传员',node_max_retry_times=12)
    def choose_promoter(self) -> OperationRoundResult:
        """
        在经营状况页面 点击代理人的位置
        :return:
        """
        if getattr(self.ctx.controller,'background_mode',False):
            if self._business_page() and self._pad_promoter_name in self._business_cards():
                return self.round_success('已核验宣传员已应用：'+self._pad_promoter_name)
            if not self._promoter_page():
                return self.round_retry('未核验宣传员选择页，未操作',wait=1)
            names=menu_words(self,Rect(20,100,450,210))
            allowed=(self.config.agent_name_1,self.config.agent_name_2)
            if names and (RANDOM_AGENT_NAME in allowed or names[0] in allowed):
                if self._pad_promoter_confirms>=3:
                    return self.round_fail('宣传员选择未生效')
                self._pad_promoter_name=names[0]
                pad_press(self,'a');self._pad_promoter_confirms+=1
                return self.round_retry('确认宣传员，等待实际经营页面',wait=1)
            pad_press(self,'dpad_right')
            return self.round_retry('手柄查找配置宣传员，未使用其他角色兜底',wait=.6)
        result = self.round_by_find_area(self.last_screenshot, '影像店营业', '选择宣传员')
        if not result.is_success:
            return self.round_retry(status=result.status, wait_round_time=1)

        # 已经选择过了 直接返回
        result = self.round_by_find_area(self.last_screenshot, '影像店营业', '换下')
        if result.is_success:
            return self.round_by_find_and_click_area(self.last_screenshot, '影像店营业', '返回')

        target_agent_name_1 = self.config.agent_name_1
        target_agent_name_2 = self.config.agent_name_2
        dt = self.run_record.get_current_dt()
        idx = (int(dt[-1]) % 2) + 1

        if RANDOM_AGENT_NAME in (target_agent_name_1, target_agent_name_2):
            # 随机选择
            self.round_by_click_area('影像店营业', f'宣传员-{idx}', pre_delay=1)
            return self.round_by_find_and_click_area(self.last_screenshot, '影像店营业', '确认',
                                                     retry_wait=1)

        area = self.ctx.screen_loader.get_area('影像店营业', '宣传员列表')
        if idx == 1:
            candidates = [target_agent_name_1, target_agent_name_2]
        else:
            candidates = [target_agent_name_2, target_agent_name_1]

        # 依次尝试匹配每个候选代理人（名称 OCR → 头像匹配）
        for agent_name in candidates:
            if self._try_select_agent(agent_name, area):
                return self.round_by_find_and_click_area(self.last_screenshot, '影像店营业', '确认',
                                                         retry_wait=1)
            log.info(f'代理人匹配失败: {agent_name}')

        if self.node_retry_times >= 2:
            # 滚动多次仍未找到, 兜底选第一个位置
            log.info('滚动多次仍未找到, 选择默认位置')
            self.round_by_click_area('影像店营业', '宣传员-1')
            return self.round_by_find_and_click_area(self.last_screenshot, '影像店营业', '确认',
                                                     retry_wait=1)
        # 向下滚动并重试
        log.info('所有候选代理人匹配失败, 向下滚动重试')
        self.scroll_area('影像店营业', '宣传员列表')
        return self.round_retry(wait=0.5)

    def _try_select_agent(self, agent_name: str, area) -> bool:
        """尝试通过名称 OCR 或头像匹配选择代理人"""
        result = self.round_by_ocr_and_click(self.last_screenshot, agent_name, area=area,
                                             color_range=[(230, 230, 230), (255, 255, 255)])
        if result.is_success:
            return True

        mr = self.get_pos_by_avatar(self.last_screenshot, agent_name)
        if mr is not None:
            self.ctx.controller.click(mr.center)
            return True

        return False

    def get_pos_by_avatar(self, screen: MatLike, target_agent_name: str) -> MatchResult | None:
        """
        根据头像匹配
        @param screen: 游戏画面
        @param target_agent_name: 需要选择的代理人名称
        @return:
        """
        agent: Agent | None = None
        for agent_enum in AgentEnum:
            if agent_enum.value.agent_name == target_agent_name:
                agent = agent_enum.value
                break

        area = self.ctx.screen_loader.get_area('影像店营业', '宣传员列表')
        part = cv2_utils.crop_image_only(screen, area.rect)

        if agent is None:
            return None

        for template_id in agent.template_id_list:
            mr = self.ctx.tm.match_one_by_feature(part, 'predefined_team', f'avatar_{template_id}')
            if mr is None:
                return None

            mr.add_offset(area.left_top)
            return mr

    @node_from(from_name='选择宣传员')
    @operation_node(name='识别录像带主题')
    def check_video_theme(self) -> OperationRoundResult:
        if getattr(self.ctx.controller,'background_mode',False):
            if not self._business_page():
                return self.round_retry('未核验经营状况，未操作',wait=1)
            words=menu_words(self,Rect(850,130,1220,200))
            self._need_video_themes=[w for w in words if w in self._all_video_themes]
            if len(self._need_video_themes)!=3:
                return self.round_retry('未识别完整录像带主题，未随意补充',wait=1)
            return self.round_success('已核验录像带主题：'+'、'.join(self._need_video_themes))
        result = self.round_by_find_area(self.last_screenshot, '影像店营业', '经营状况')
        if not result.is_success:
            return self.round_retry(status=result.status, wait=1)

        areas = [
            self.ctx.screen_loader.get_area('影像店营业', '录像带主题-1'),
            self.ctx.screen_loader.get_area('影像店营业', '录像带主题-2'),
            self.ctx.screen_loader.get_area('影像店营业', '录像带主题-3')
        ]

        target_list = [gt(i, 'game') for i in self._all_video_themes]
        for area in areas:
            part = cv2_utils.crop_image_only(self.last_screenshot, area.rect)
            ocr_result = self.ctx.ocr.run_ocr_single_line(part)

            results = difflib.get_close_matches(ocr_result, target_list, n=1)

            if results:
                idx = target_list.index(results[0])
                self._need_video_themes.append(self._all_video_themes[idx])

        # 识别不到 随便补充到3个主题
        for theme in self._all_video_themes:
            if len(self._need_video_themes) >= 3:
                break
            if theme in self._need_video_themes:
                continue
            self._need_video_themes.append(theme)

        log.info(f'所需主题 {self._need_video_themes}')
        return self.round_success()

    @node_from(from_name='识别录像带主题')
    @operation_node(name='点击录像带入口')
    def click_video_entry(self) -> OperationRoundResult:
        """
        在经营状况页面 点击录像带的位置
        :return:
        """
        if getattr(self.ctx.controller,'background_mode',False):
            if '推荐上架' in menu_words(self,Rect(1400,980,1900,1060)):
                return self.round_success('已核验录像带选择页')
            if not self._business_page():
                return self.round_retry('未核验经营页，未操作',wait=1)
            focus=self._business_focus()
            if focus is None:
                return self.round_retry('未核验录像带卡片焦点，未操作',wait=1)
            if focus==0:
                pad_press(self,'dpad_right')
                return self.round_retry('手柄选择录像带卡片',wait=.6)
            if self._pad_video_open>=3:
                return self.round_fail('录像带入口确认未生效')
            pad_press(self,'a');self._pad_video_open+=1
            return self.round_retry('手柄打开录像带选择页',wait=1)
        return self.round_by_click_area('影像店营业', '录像带入口',
                                        retry_wait=1)

    @node_from(from_name='点击录像带入口')
    @operation_node(name='识别推荐上架')
    def check_recommended(self) -> OperationRoundResult:
        if getattr(self.ctx.controller,'background_mode',False):
            if self._pad_recommended and self._business_page() and len(self._business_cards())>=4:
                return self.round_success('推荐上架')
            if '推荐上架' not in menu_words(self,Rect(1400,980,1900,1060)):
                return self.round_retry('未核验推荐上架提示，未操作',wait=1)
            if self._pad_recommended>=3:
                return self.round_fail('推荐上架未应用到经营页')
            pad_press(self,'x');self._pad_recommended+=1
            return self.round_retry('手柄推荐上架，等待三张录像带实际应用',wait=1)
        result = self.round_by_find_and_click_area(self.last_screenshot, '影像店营业', '推荐上架')

        if result.is_success:
            return self.round_success(status=result.status, wait=1)

        return self.round_by_find_area(self.last_screenshot, '影像店营业', '上架筛选', retry_wait=1)

    @node_from(from_name='识别推荐上架', status='上架筛选')
    @node_from(from_name='上架')
    @node_from(from_name='上架', success=False)
    @operation_node(name='上架筛选')
    def click_filter(self) -> OperationRoundResult:
        """
        在录像带画面 点击上架筛选
        :return:
        """
        if self._current_idx >= len(self._need_video_themes):
            return self.round_success(status=RandomPlayApp.STATUS_ALL_VIDEO_CHOOSE)

        result = self.round_by_find_and_click_area(self.last_screenshot, '影像店营业', '上架筛选')
        if result.is_success:
            self._current_idx += 1
            return self.round_success(result.status, wait=1)
        else:
            return self.round_retry(result.status, wait=1)

    @node_from(from_name='上架筛选')
    @operation_node(name='选择主题')
    def choose_theme(self) -> OperationRoundResult:
        """
        选择主题
        :return:
        """
        area = self.ctx.screen_loader.get_area('影像店营业', '主题筛选')
        ocr_results = self.ctx.ocr.crop_and_run_ocr(self.last_screenshot, area.rect)

        target_list = [gt(i, 'game') for i in self._all_video_themes]
        current_target = self._need_video_themes[self._current_idx - 1]
        for ocr_str, mrl in ocr_results.items():
            if mrl.max is None:
                continue

            results = difflib.get_close_matches(ocr_str, target_list, n=1)

            if not results:
                continue

            idx = target_list.index(results[0])
            theme = self._all_video_themes[idx]
            if theme != current_target:
                continue

            target_point = area.left_top + mrl.max
            if self.ctx.controller.click(target_point):
                return self.round_success(wait=1)
            else:
                return self.round_retry(wait=0.5)

        # 找不到 往下滑动
        start = area.center
        end = start + Point(0, -100)
        self.ctx.controller.drag_to(start=start, end=end)
        return self.round_retry(status=f'未找到{current_target}', wait=1)

    @node_from(from_name='选择主题')
    @operation_node(name='上架')
    def choose_onshelf(self) -> OperationRoundResult:
        """
        上架
        :return:
        """
        result = self.round_by_find_area(self.last_screenshot, '影像店营业', '下架',)
        if result.is_success:  # 已经上架了
            return self.round_success()

        result = self.round_by_find_area(self.last_screenshot, '影像店营业', '上架')
        if not result.is_success:
            return self.round_wait(status=result.status, wait_round_time=1)

        # 这个点击是为了关闭筛选
        click1 = self.round_by_click_area('影像店营业', '上架')
        click2 = self.round_by_click_area('影像店营业', '上架', pre_delay=0.5)

        if click1.is_success and click2.is_success:
            return self.round_wait(wait=1)
        else:
            return self.round_retry(status=click1.status, wait_round_time=1)

    @node_from(from_name='识别推荐上架', status='推荐上架')
    @node_from(from_name='上架筛选', status=STATUS_ALL_VIDEO_CHOOSE)
    @operation_node(name='返回')
    def back(self) -> OperationRoundResult:
        if getattr(self.ctx.controller,'background_mode',False):
            if self._business_page():
                return self.round_success('已核验返回经营页')
            if ('推荐上架' in menu_words(self,Rect(1400,980,1900,1060))
                    and '上架筛选' in menu_words(self,Rect(1500,10,1850,100))):
                pad_press(self,'b')
            return self.round_retry('等待实际经营页',wait=1)
        result = self.round_by_find_area(self.last_screenshot, '影像店营业', '经营状况')
        if result.is_success:
            return self.round_success()

        return self.round_by_find_and_click_area(self.last_screenshot, '影像店营业', '返回',
                                                 retry_wait=1)

    @node_from(from_name='返回')
    @operation_node(name='开始营业')
    def start(self) -> OperationRoundResult:
        if getattr(self.ctx.controller,'background_mode',False):
            if not self._business_page() or '开始营业' not in menu_words(self,Rect(1450,840,1900,1000)):
                return self.round_retry('未核验开始营业，未操作',wait=1)
            if self._pad_start>=3:
                return self.round_fail('开始营业未生效')
            pad_press(self,'x');self._pad_start+=1
            return self.round_success('手柄开始营业，等待实际确认',wait=1)
        return self.round_by_find_and_click_area(self.last_screenshot, '影像店营业', '开始营业',
                                                 retry_wait=1)

    @node_from(from_name='开始营业')
    @operation_node(name='确认营业')
    def confirm_business(self) -> OperationRoundResult:
        if getattr(self.ctx.controller,'background_mode',False):
            words=menu_words(self,Rect(650,450,1300,750))
            if any('准备营业' in w for w in words) and '确认' in words:
                import numpy as np
                part=self.last_screenshot[595:655,980:1250]
                if np.mean((part[:,:,0]>150)&(part[:,:,1]>140)&(part[:,:,2]<100))<.3:
                    pad_press(self,'dpad_right')
                    return self.round_retry('选择营业确认，等待实际焦点',wait=.6)
                if self._pad_business_confirms>=3:
                    return self.round_fail('营业确认未生效')
                pad_press(self,'a');self._pad_business_confirms+=1
                return self.round_success('手柄确认营业，等待真实营业状态',wait=1)
            return self.round_retry('未核验营业确认窗口，未操作',wait=1)
        return self.round_by_find_and_click_area(self.last_screenshot, '影像店营业', '开始营业-确认',
                                                 retry_wait=1)

    @node_from(from_name='确认营业')
    @operation_node(name='营业后确认',node_max_retry_times=10)
    def confirm(self) -> OperationRoundResult:
        if getattr(self.ctx.controller,'background_mode',False):
            if self._business_page() and '正在营业' in menu_words(self,Rect(1450,840,1900,1000)):
                return self.round_success('已核验录像店正在营业')
            words=menu_words(self,Rect(400,300,1500,850))
            if (any(any(label in w for label in ('营业','生意兴隆','诚信经营','丁尼为本')) for w in words)
                    and '确认' in words and self._pad_business_confirms<6):
                pad_press(self,'a');self._pad_business_confirms+=1
                return self.round_retry('确认营业结果，等待实际营业页',wait=1)
            return self.round_retry('等待录像店真实营业结果',wait=1)
        return self.round_by_find_and_click_area(self.last_screenshot, '影像店营业', '营业后确认',
                                                 retry_wait=1)

    @node_from(from_name='营业后确认')
    @node_from(from_name='关闭经营页面')
    @node_notify(when=NotifyTiming.PREVIOUS_DONE)
    @operation_node(name='返回大世界')
    def back_to_world(self) -> OperationRoundResult:
        op = BackToNormalWorld(self.ctx)
        result=op.execute()
        if self._business_failure:
            return self.round_fail(self._business_failure)
        return self.round_by_op_result(result)


def __debug():
    ctx = ZContext()
    ctx.init()
    ctx.run_context.start_running()
    app = RandomPlayApp(ctx)
    app.execute()


if __name__ == '__main__':
    __debug()
