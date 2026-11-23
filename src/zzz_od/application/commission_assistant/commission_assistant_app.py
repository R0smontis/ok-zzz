# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/application/commission_assistant/commission_assistant_app.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
import time

from cv2.typing import MatLike

from onedragon.base.matcher.match_result import MatchResult
from onedragon.base.operation.application import application_const
from onedragon.base.operation.context_event_bus import ContextEventItem
from onedragon.base.operation.context_keyboard_event import ContextKeyboardEventEnum
from onedragon.base.operation.operation_base import OperationResult
from onedragon.base.operation.operation_edge import node_from
from onedragon.base.operation.operation_node import operation_node
from onedragon.base.operation.operation_round_result import (
    OperationRoundResult, OperationRoundResultEnum,
)
from onedragon.utils import str_utils
from onedragon.utils.i18_utils import gt
from zzz_od.application.commission_assistant import commission_assistant_const
from onedragon.base.controller.input_guard import execution_input_allowed
from src.navigation.dialogue import send_story_action
from zzz_od.application.commission_assistant.story_dialogue import StoryDialogue
from zzz_od.application.commission_assistant.commission_assistant_config import (
    CommissionAssistantConfig,
)
from zzz_od.application.zzz_application import ZApplication
from zzz_od.context.zzz_context import ZContext
from zzz_od.hollow_zero.event import hollow_event_utils
from zzz_od.operation.wait_normal_world import WaitNormalWorld


class CommissionAssistantApp(ZApplication):

    """委托助手:辅助工具,剧情/委托/钓鱼等画面自动推进。非玩法、无独立消耗。"""

    def __init__(self, ctx: ZContext):
        ZApplication.__init__(
            self,
            ctx=ctx,
            app_id=commission_assistant_const.APP_ID,
            op_name=commission_assistant_const.APP_NAME,
        )

        self.config: CommissionAssistantConfig = self.ctx.run_context.get_config(
            app_id=commission_assistant_const.APP_ID,
            instance_idx=self.ctx.current_instance_idx,
            group_id=application_const.DEFAULT_GROUP_ID,
        )
        # self.last_recorded_time: float = self.last_screenshot_time  # 用于性能分析
        self.withered_domain_inited: bool = False  # 空洞初始化标志

        self.run_mode: int = 0  # 0=对话 1=闪避 2=自动战斗

        self._story = StoryDialogue(ctx)
        self._story_settings = None

        self.fishing_btn_pressed: str | None = None  # 钓鱼在按下的按键
        self.fishing_done: bool = False  # 钓鱼是否结束 通常是比赛类 最后会有挑战结果显示

    def handle_init(self):
        self._story.reset()
        self._story_settings = None
        self._listen_btn()

    def _unlisten_btn(self) -> None:
        self.ctx.unlisten_event(ContextKeyboardEventEnum.PRESS.value, self._on_key_press)

    def _listen_btn(self) -> None:
        self.ctx.listen_event(ContextKeyboardEventEnum.PRESS.value, self._on_key_press)

    def _on_key_press(self, event: ContextEventItem):
        if not self.ctx.run_context.is_context_running:
            return
        key = event.data
        if key == self.config.dodge_switch:
            if self.run_mode == 0:
                self.run_mode = 1
            else:  # 防止并发有问题导致值错乱 最后兜底成初始值
                self.run_mode = 0
        elif key == self.config.auto_battle_switch:
            if self.run_mode == 0:
                self.run_mode = 2
            else:  # 防止并发有问题导致值错乱 最后兜底成初始值
                self.run_mode = 0

    def _need_pause_in_background(self) -> bool:
        # 跟随首页的前台/后台模式：只有前台模式在游戏切走时暂停。
        return not self.ctx.controller.is_background_input and not self.ctx.controller.game_win.is_win_active

    @node_from(from_name='委托助手')
    @node_from(from_name='自动战斗模式')
    @node_from(from_name='剧情模式')
    @node_from(from_name='钓鱼')
    @node_from(from_name='钓鱼', success=False)
    @operation_node(name='委托助手', is_start_node=True)
    def dialog_mode(self) -> OperationRoundResult:
        if self.run_mode != 0 and self._need_pause_in_background():
            self._story.reset()
            return self.round_wait('等待游戏切换至前台', wait=1)

        if self.run_mode in [1, 2]:
            self._story.reset()
            self._load_auto_op()
            return self.round_success('自动战斗模式')

        self.screenshot()

        # start = datetime.now()

        # 邀约同行移动时 下面的current_screen会识别不到
        result = self.round_by_find_area(self.last_screenshot, '战斗画面', '按键-交互')
        if result.is_success:
            self._story.reset()
            return self.round_wait(status='战斗画面-按键-交互', wait=1)

        current_screen = self.check_and_update_current_screen(screen_name_list=['大世界-普通', '大世界-勘域'])
        if current_screen is not None:
            self._story.reset()
            return self.round_wait(status=current_screen, wait=1)

        # 判断二级菜单
        result = self.round_by_find_area(self.last_screenshot, '委托助手', '左上角返回')
        if result.is_success:
            self._story.reset()
            return self.round_wait('处于二级界面, 等待用户操作', wait=1)

        # 空洞事件、空洞完成与短信回复使用全局输入方式；前台模式下游戏切走时不能点击其他程序。
        background_paused = self._need_pause_in_background()

        # 判断是否在空洞中
        result = hollow_event_utils.check_in_hollow(self.ctx, self.last_screenshot)
        if result is not None:
            self._story.reset()
            if background_paused:
                return self.round_wait('等待游戏切换至前台', wait=1)
            result = self._handle_hollow(self.last_screenshot_time)
            return self.round_wait(result.status, wait=0.5)

        # 判断是否空洞内完成
        result = (self.round_by_find_area(self.last_screenshot, '零号空洞-事件', '通关-完成')
                  if background_paused else
                  self.round_by_find_and_click_area(self.last_screenshot, '零号空洞-事件', '通关-完成',
                                                    pre_delay=0))
        if result.is_success:
            self._story.reset()
            if background_paused:
                return self.round_wait('等待游戏切换至前台', wait=1)
            return self.round_wait(result.status, wait=1)


        # 剧情模式 以及一些检测优先级在剧情模式之后的界面
        return self.round_success('检测剧情模式')


    def _handle_hollow(self, screenshot_time: float) -> OperationRoundResult:
        """
        处理在空洞里的情况
        :param screen: 游戏画面
        :param screenshot_time: 截图时间
        """
        # 空洞内不好处理事件
        # return self.round_wait(status='空洞中', wait=1) # Original line, commented out as per previous logic.
        self.ctx.withered_domain.map_service.init_event_yolo()
        if not self.withered_domain_inited:
            self.ctx.withered_domain.init_before_run()
            self.withered_domain_inited = True

        # 判断当前邦布是否存在
        hollow_map = self.ctx.withered_domain.map_service.cal_current_map_by_screen(self.last_screenshot,
                                                                                    screenshot_time)
        if hollow_map is None or hollow_map.contains_entry('当前'):
            return self.round_wait(status='空洞走格子中', wait=1)

        # 处理对话
        return hollow_event_utils.check_event_text_and_run(self, self.last_screenshot, [])


    def check_knock_knock(self) -> OperationRoundResult:
        """
        判断是否在短信中
        返回值:
        wait 表示检测成功, 上游执行 wait 操作
        retry 表示检测失败, 上游会继续检测别的场景
        本函数不返回 success 和 fail
        """
        result = self.round_by_find_area(self.last_screenshot, '委托助手', '标题-短信')
        if not result.is_success:
            return self.round_retry()

        area = self.ctx.screen_loader.get_area('委托助手', '区域-短信-文本框')
        ocr_result_list = self.ctx.ocr_service.get_ocr_result_list(image=self.last_screenshot, rect=area.rect)
        bottom_text: str | None = None  # 最下方的文本
        bottom_mr: MatchResult | None = None  # 找到最下方的文本进行点击
        for mr in ocr_result_list:
            if bottom_mr is None or mr.center.y > bottom_mr.center.y:
                bottom_mr = mr
                bottom_text = mr.data

        if bottom_text is None:
            return self.round_retry()

        if self._need_pause_in_background():
            # 短信回复与关闭跟随全局输入方式；前台模式下游戏切走时等待，不点击其他程序。
            return self.round_wait('等待游戏切换至前台', wait=1)

        if '以上为最新' in bottom_text:
            result = self.round_by_find_and_click_area(self.last_screenshot, '委托助手', '按钮-短信-关闭')
            if result.is_success:
                return self.round_wait(result.status, wait=1)
            else:
                return self.round_retry()
        elif str_utils.find_by_lcs('密友同行', bottom_text, 0.75):
            # 代理人好感页面的"密友同行"不是短信回复选项，点击会打开同行界面。
            return self.round_wait('忽略密友同行界面', wait=1)

        self.ctx.controller.click(bottom_mr.center)
        return self.round_wait(bottom_text, wait=0.3)

    @node_from(from_name='委托助手', status='自动战斗模式')
    @operation_node(name='自动战斗模式')
    def auto_mode(self) -> OperationRoundResult:
        if self.run_mode == 0:
            self.ctx.auto_battle_context.stop_auto_battle()
            return self.round_success()

        self.ctx.auto_battle_context.check_battle_state(self.last_screenshot, self.last_screenshot_time)

        return self.round_wait(wait_round_time=self.ctx.battle_assistant_config.screenshot_interval)

    def _load_auto_op(self) -> None:
        """
        加载战斗指令
        """
        self.ctx.auto_battle_context.init_auto_op(
            sub_dir='auto_battle' if self.run_mode == 2 else 'dodge',
            op_name=self.config.auto_battle if self.run_mode == 2 else self.config.dodge_config
        )
        self.ctx.auto_battle_context.start_auto_battle()

    def check_fishing(self) -> OperationRoundResult | None:
        """
        判断是否进入钓鱼画面
        - 左上角有返回
        - 出现了抛竿文本
        """
        if self._need_pause_in_background():
            return self.round_wait('等待游戏切换至前台', wait=1)
        result = self.round_by_find_area(self.last_screenshot, '钓鱼', '按键-返回')
        if not result.is_success:
            return None

        area = self.ctx.screen_loader.get_area('钓鱼', '指令文本区域')
        ocr_result_list = self.ctx.ocr_service.get_ocr_result_list(
            image=self.last_screenshot,
            rect=area.rect
        )
        ocr_word_list = [i.data for i in ocr_result_list]
        if str_utils.find_best_match_by_difflib(gt('点击按键抛竿', 'game'), ocr_word_list) is None:
            return None

        self.fishing_done = False
        self.ctx.controller.mouse_move(area.left_top)  # 移开鼠标 防止遮挡指令
        return self.round_success('钓鱼', wait=0.1)


    @node_from(from_name='委托助手', status='检测剧情模式')
    @operation_node(name='剧情模式', node_max_retry_times=5)
    def story_mode(self) -> OperationRoundResult:
        if self.run_mode != 0:
            self._story.reset()
            return self.round_success('切换自动对话模式')
        result = self.check_knock_knock()
        if result.result == OperationRoundResultEnum.WAIT:
            self._story.reset()
            return result
        result = self.check_fishing() if not self._need_pause_in_background() else None
        if result is not None:
            self._story.reset()
            return result

        settings = (self.config.story_mode, self.config.dialog_option, self.config.dialog_click_interval)
        if settings != self._story_settings:
            self._story.reset()
            self._story_settings = settings
        controller = self.ctx.controller
        hwnd = controller.game_win.get_hwnd()
        action = self._story.detect(self.last_screenshot, mode=settings[0], option=settings[1],
                                    click_interval=settings[2])
        if action is None:
            return self.round_success(self._story.status, wait=self.config.sleep_after_empty_screen)

        def input_allowed():
            return (controller is self.ctx.controller and self.run_mode == 0
                    and self.ctx.run_context.is_context_running
                    and settings == (self.config.story_mode, self.config.dialog_option,
                                     self.config.dialog_click_interval)
                    and time.time() - self.last_screenshot_time <= .5
                    and execution_input_allowed())

        completed = send_story_action(self.ctx, self.last_screenshot, action, expected_hwnd=hwnd,
                                      input_allowed=input_allowed)
        self._story.feedback(action, completed)
        return self.round_wait(action.text if completed else f'等待执行：{action.text}', wait=.1)


    @node_from(from_name='剧情模式', status='钓鱼')
    @operation_node('钓鱼', node_max_retry_times=50)  # 约5s没识别到指令就退出
    def on_finishing(self) -> OperationRoundResult:
        # 判断当前指令
        area = self.ctx.screen_loader.get_area('钓鱼', '指令文本区域')
        ocr_result_map = self.ctx.ocr.crop_and_run_ocr(self.last_screenshot, area.rect)
        ocr_result_list = list(ocr_result_map.keys())

        target_command_list = [
            gt('点击按键抛竿', 'game'),
            gt('等待上鱼', 'game'),
            gt('正确时机点击按键上鱼', 'game'),
            gt('连点', 'game'),
            gt('长按', 'game'),
        ]
        command_idx, _ = str_utils.find_most_similar(target_command_list, ocr_result_list)

        if command_idx != 4:  # 松开按键
            if self.fishing_btn_pressed == 'd':
                self.ctx.controller.move_d(release=True)
            elif self.fishing_btn_pressed == 'a':
                self.ctx.controller.move_a(release=True)
            self.fishing_btn_pressed = None

        if command_idx is not None:
            self.fishing_done = False

        if command_idx == 0:  # 点击按键抛竿
            self.ctx.controller.interact(press=True, press_time=0.2)
            return self.round_wait(target_command_list[command_idx], wait=0.1)
        elif command_idx == 1:  # 等待上鱼
            return self.round_wait(target_command_list[command_idx], wait=0.1)
        elif command_idx == 2:  # 正确时机点击按键上鱼
            result = self.round_by_find_area(self.last_screenshot, '钓鱼', '按键-时机上鱼')
            if result.is_success:
                self.ctx.controller.interact(press=True, press_time=0.2)
                return self.round_wait(target_command_list[command_idx], wait=0.1)
            else:
                return self.round_wait(target_command_list[command_idx], wait_round_time=0.1)  # 这个要尽快按
        elif command_idx == 3:  # 连点
            power = None
            left = self.round_by_find_area(self.last_screenshot, '钓鱼', '按键-左')
            if left.is_success:
                self.ctx.controller.move_a(press=True, press_time=0.05)
                power = self.round_by_find_area(self.last_screenshot, '钓鱼', '按键-强力-左')
            else:
                self.ctx.controller.move_d(press=True, press_time=0.05)
                power = self.round_by_find_area(self.last_screenshot, '钓鱼', '按键-强力-右')

            if power is not None and power.is_success:
                self.ctx.controller.keyboard_press('space', press_time=0.05)
            return self.round_wait(target_command_list[command_idx], wait_round_time=0.1)  # 这个要尽快按
        elif command_idx == 4:  # 长按
            if self.fishing_btn_pressed is None:
                power = None
                left = self.round_by_find_area(self.last_screenshot, '钓鱼', '按键-左')
                if left.is_success:
                    self.fishing_btn_pressed = 'a'
                    self.ctx.controller.move_a(press=True)
                    power = self.round_by_find_area(self.last_screenshot, '钓鱼', '按键-强力-左')

                right = self.round_by_find_area(self.last_screenshot, '钓鱼', '按键-右')
                if right.is_success:
                    self.fishing_btn_pressed = 'd'
                    self.ctx.controller.move_d(press=True)
                    power = self.round_by_find_area(self.last_screenshot, '钓鱼', '按键-强力-右')

                if power is not None and power.is_success:
                    time.sleep(0.05)  # 稍微等待前面长按 避免按键冲突
                    self.ctx.controller.keyboard_press('space', press_time=0.05)
            return self.round_wait(target_command_list[command_idx], wait_round_time=0.1)

        if command_idx is None:
            result = self.round_by_find_and_click_area(self.last_screenshot, '钓鱼', '按钮-点击空白处关闭')
            if result.is_success:
                return self.round_wait(result.status, wait=0.1)

            result = self.round_by_find_area(self.last_screenshot, '钓鱼', '标题-挑战结果')
            if result.is_success:  # 只判断确定有时候会误判 加上标题
                result = self.round_by_find_and_click_area(self.last_screenshot, '钓鱼', '按钮-确定')
                if result.is_success:
                    self.fishing_done = True
                    return self.round_wait(result.status, wait=0.1)

            if self.fishing_done:
                return self.round_success('钓鱼结束')

            op = WaitNormalWorld(self.ctx, check_once=True)
            result = self.round_by_op_result(op.execute())
            if result.is_success:
                return self.round_success('钓鱼结束')

        return self.round_retry('未识别到指令', wait=0.1)

    def handle_pause(self):
        ZApplication.handle_pause(self)
        self._story.reset()
        self._unlisten_btn()
        if self.run_mode != 0:
            self.ctx.auto_battle_context.stop_auto_battle()

    def handle_resume(self) -> None:
        ZApplication.handle_resume(self)
        self._listen_btn()
        if self.run_mode != 0:
            self.ctx.auto_battle_context.resume_auto_battle()

    def after_operation_done(self, result: OperationResult):
        ZApplication.after_operation_done(self, result)
        self._unlisten_btn()


def __debug():
    ctx = ZContext()
    ctx.init()
    ctx.run_context.start_running()
    app = CommissionAssistantApp(ctx)
    app.execute()


if __name__ == '__main__':
    __debug()
