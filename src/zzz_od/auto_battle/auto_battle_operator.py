# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/auto_battle/auto_battle_operator.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import TYPE_CHECKING, Any

from onedragon.base.conditional_operation.atomic_op import AtomicOp
from onedragon.base.conditional_operation.loader import ConditionalOperatorLoader
from onedragon.base.conditional_operation.operation_def import OperationDef
from onedragon.base.conditional_operation.state_handler import StateHandler
from onedragon.base.conditional_operation.scene import Scene
from onedragon.base.conditional_operation.operator import ConditionalOperator
from onedragon.base.controller.input_guard import execution_input_guard
from onedragon.utils import thread_utils
from onedragon.utils.log_utils import log
from zzz_od.auto_battle.atomic_op.btn_lock import AtomicBtnLock
from zzz_od.auto_battle.atomic_op.turn import AtomicTurn
from zzz_od.context.zzz_context import ZContext

if TYPE_CHECKING:
    from zzz_od.auto_battle.auto_battle_context import AutoBattleContext

_auto_battle_operator_executor = ThreadPoolExecutor(thread_name_prefix='_auto_battle_operator_executor', max_workers=2)

# 自动战斗配置的默认回退模板名
FALLBACK_TEMPLATE_NAME = '全配队通用'


class AutoBattleOperator(ConditionalOperator):

    def __init__(
        self,
        ctx: AutoBattleContext,
        sub_dir: str,
        template_name: str,
        read_from_merged: bool = True,
    ):
        original_file_path = ConditionalOperatorLoader.get_yaml_file_path(
            sub_dir=[sub_dir],
            template_name=template_name,
            read_from_merged=read_from_merged,
        )
        if not os.path.exists(original_file_path):
            log.warning(f'自动战斗配置 {original_file_path} 不存在，回退到 {FALLBACK_TEMPLATE_NAME}')
            template_name = FALLBACK_TEMPLATE_NAME

        ConditionalOperator.__init__(
            self,
            sub_dir=[sub_dir],
            template_name=template_name,
            operation_template_sub_dir=['auto_battle_operation'],
            state_handler_template_sub_dir=['auto_battle_state_handler'],
            read_from_merged=read_from_merged,
            state_record_service=ctx.state_record_service,
        )

        # 配置文件的zzz定制内容
        self.author: str = ''  #  作者
        self.homepage: str = ''
        self.thanks: str = ''
        self.version: str = ''
        self.introduction: str = ''
        self.team_list: list[list[str]] = []  # 配队信息

        self.check_dodge_interval: float = 0.02  # 检测闪避的间隔
        self.check_agent_interval: float = 0.5  # 检测代理人的间隔
        self.check_chain_interval: float = 1  # 检测连携技的间隔
        self.check_quick_interval: float = 0.5  # 检测快速支援的间隔
        self.check_end_interval: float = 5  # 检测战斗结束的间隔
        self.target_lock_interval: float = 1  # 检测锁定目标的间隔
        self.abnormal_status_interval: float = 0  # 检测异常状态的间隔
        self.auto_lock_interval = 1  # 自动锁定的间隔
        self.auto_turn_interval = 2  # 自动转向的间隔

        self.ctx: AutoBattleContext = ctx

        # 自动周期
        self.last_lock_time: float = 0  # 上一次锁定的时间
        self.last_turn_time: float = 0  # 上一次转动视角的时间

        # 停止事件
        self._stop_event = Event()
        self._periodic_generation: int = 0  # 会话代际计数器
        self.event_only = False
        self.execution_allowed = None
        self.execution_guard_factory = None
        self.event_started_at = 0.0

    def load_other_info(self, data: dict[str, Any]) -> None:
        """
        加载其他所需的信息

        Args:
            data: 配置文件内容
        """
        self.author = data.get('author', '')
        self.homepage = data.get('homepage', 'https://qm.qq.com/q/wuVRYuZzkA')
        self.thanks = data.get('thanks', '')
        self.version = data.get('version', '')
        self.introduction = data.get('introduction', '')
        self.team_list = data.get('team_list', [])

        self.check_dodge_interval = data.get('check_dodge_interval', 0.02)
        self.check_agent_interval = data.get('check_agent_interval', 0.5)
        self.check_chain_interval = data.get('check_chain_interval', 1)
        self.check_quick_interval = data.get('check_quick_interval', 0.5)
        self.check_end_interval = data.get('check_end_interval', 5)
        self.target_lock_interval = data.get('target_lock_interval', 1)
        self.abnormal_status_interval = data.get('abnormal_status_interval', 0)
        self.auto_lock_interval = data.get('auto_lock_interval', 1)
        self.auto_turn_interval = data.get('auto_turn_interval', 2)

    def load(self) -> None:
        super().load()
        # Loaded after merged/user templates too: preserving their contents
        # must not keep the old no-operation behavior for an unknown portrait.
        if self._sub_dir != ['auto_battle']:
            return
        from zzz_od.auto_battle.generic_handlers import normal_handler, event_handlers
        for scene in self.scenes:
            if scene.triggers:
                fallbacks = event_handlers(scene.triggers)
                unknown = []
                for handler in event_handlers(scene.triggers):
                    handler.states = '[前台-未识别, 0, 1] & (' + handler.states + ')'
                    handler.original_data['states'] = handler.states
                    unknown.append(handler)
                scene.set_handlers(unknown + scene.handlers + fallbacks)
            else:
                scene.set_handlers([normal_handler(unknown_only=True)] + scene.handlers
                                   + [normal_handler()])
        self.scenes.append(Scene({
            'triggers': ['自定义-实时闪避事件'], 'priority': 100, 'interval': .25,
            'handlers': [{
                'states': '[按键可用-普通攻击, 0, 0.25] & [自定义-实时闪避事件, 0, 0.25]',
                'debug_name': '优先实时弹刀或闪避',
                'operations': [{'op_name': '实时战斗响应'}],
            }],
        }))

    def init_before_running(self) -> tuple[bool, str]:
        """
        运行前进行初始化
        :return:
        """
        try:
            ConditionalOperator.init(self)
            log.info(f'自动战斗配置加载成功 {self.get_template_name()}')
            return True, ''
        except Exception:
            log.error('自动战斗初始化失败 如果是共享配队文件请在群内提醒对应作者修复', exc_info=True)
            return False, '初始化失败'

    def get_atomic_op(self, op_def: OperationDef) -> AtomicOp:
        """
        获取一个原子操作

        Args:
            op_def: 操作定义

        Returns:
            AtomicOp: 原子操作
        """
        return self.ctx.atomic_op_factory.get_atomic_op(op_def)

    def dispose(self) -> None:
        """
        销毁 注意要解绑各种事件监听
        :return:
        """
        ConditionalOperator.dispose(self)

    def start_running_async(self) -> bool:
        success = ConditionalOperator.start_running_async(self)
        if success and not self.event_only:
            self._periodic_generation += 1
            self._stop_event.clear()
            gen = self._periodic_generation
            lock_f = _auto_battle_operator_executor.submit(self._guarded_periodic, gen, self._make_input_guard())
            lock_f.add_done_callback(thread_utils.handle_future_result)

        return success

    def batch_update_states(self, state_records):
        if self.event_only:
            state_records = [record for record in state_records
                             if record.state_name.startswith('闪避识别-')
                             and not record.is_clear
                             and record.trigger_time >= self.event_started_at
                             and 0 <= time.time() - record.trigger_time <= 0.25]
            if not state_records:
                return
        super().batch_update_states(state_records)

    def _trigger_scene(self, state_name, generation=None):
        if self.event_only:
            recorder = self.state_record_service.get_state_recorder(state_name)
            if (recorder is None or recorder.last_record_time < self.event_started_at
                    or not 0 <= time.time() - recorder.last_record_time <= 0.25):
                return
        super()._trigger_scene(state_name, generation)

    def _guarded_periodic(self, generation, guard):
        token = execution_input_guard.set(guard)
        try:
            self.operate_periodically(generation)
        finally:
            execution_input_guard.reset(token)

    def operate_periodically(self, generation: int) -> None:
        """
        周期性完成动作

        1. 锁定敌人
        2. 转向 - 有机会找到后方太远的敌人；迷失之地可以转动下层入口
        :return:
        """
        if self.auto_lock_interval <= 0 and self.auto_turn_interval <= 0:  # 不开启自动锁定 和 自动转向
            return
        lock_op = AtomicBtnLock(self.ctx)
        turn_op = AtomicTurn(self.ctx, 100)
        while self.is_running and self._periodic_generation == generation:
            now = time.time()

            if not self.ctx.last_check_in_battle:  # 当前画面不是战斗画面 就不运行了
                if self._stop_event.wait(timeout=0.2):
                    break
                continue

            any_done: bool = False
            if not self.is_running:
                break
            if self.auto_lock_interval > 0 and now - self.last_lock_time > self.auto_lock_interval:
                lock_op.execute()
                self.last_lock_time = now
                any_done = True
            if not self.is_running:
                break
            if self.auto_turn_interval > 0 and now - self.last_turn_time > self.auto_turn_interval:
                turn_op.execute()
                self.last_turn_time = now
                any_done = True

            if not any_done:
                if self._stop_event.wait(timeout=0.2):
                    break

    def stop_running(self) -> None:
        """
        停止执行
        """
        self._stop_event.set()
        ConditionalOperator.stop_running(self)

    @staticmethod
    def after_app_shutdown() -> None:
        """
        整个脚本运行结束后的清理
        """
        _auto_battle_operator_executor.shutdown(wait=False, cancel_futures=True)


def __debug():
    ctx = ZContext()
    ctx.init()
    auto_op = AutoBattleOperator(ctx.auto_battle_context, 'auto_battle', '全配队通用')
    auto_op.init()
    auto_op.usage_states
    # auto_op.start_running_async()
    # time.sleep(5)
    # auto_op.stop_running()


if __name__ == '__main__':
    __debug()
