# -*- coding: utf-8 -*-
"""精简版应用运行上下文（ok-zzz 重建，非逐行移植）。

对齐 ZenlessZoneZero-OneDragon (GPL-3.0) 同名模块的对外 API 面
（注册表 / 组配置 / 运行记录 / 状态机 / 通知池），供节点图执行器与
应用代码以原有语义调用；线程模型简化为单执行器 + 协作式暂停停止。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum, StrEnum
from typing import TYPE_CHECKING, TypeVar

from onedragon.base.operation.application.application_config import ApplicationConfig
from onedragon.base.operation.application.application_group_config import (
    ApplicationGroupConfig,
)
from onedragon.base.operation.application_run_record import AppRunRecord
from onedragon.base.operation.context_event_bus import ContextEventBus
from onedragon.utils.log_utils import log

if TYPE_CHECKING:
    from onedragon.base.operation.application_base import Application
    from onedragon.base.operation.application.application_factory import (
        ApplicationFactory,
    )

CONFIG = TypeVar('CONFIG', bound=ApplicationConfig)
RECORD = TypeVar('RECORD', bound=AppRunRecord)


class RunFinishReason(StrEnum):
    """应用结束原因。"""

    COMPLETED = "COMPLETED"  # 正常完成
    STOPPED = "STOPPED"  # 用户、流程或程序停止
    FAILED = "FAILED"  # 执行失败或运行异常
    NOT_STARTED = "NOT_STARTED"  # 初始化失败、超时或未取得运行权


@dataclass(slots=True)
class ApplicationRunResult:
    """一次应用运行的最终结果。"""

    finish_reason: RunFinishReason
    app_id: str | None = None
    instance_idx: int | None = None
    group_id: str | None = None


class ApplicationRunContextStateEventEnum(StrEnum):
    """应用运行上下文状态事件枚举。"""

    START = "start"
    PAUSE = "pause"
    RESUME = "resume"
    STOP = "stop"


class ApplicationRunStateEnum(Enum):
    STOPPED = 0
    RUNNING = 1
    PAUSE = 2


class NotifyPool:
    """节点消息池（精简版：收集文本，merge 推送时合并；P11 接真实推送）。"""

    def __init__(self):
        self._lock = threading.Lock()
        self.messages: list[str] = []
        self.images: list = []
        self.max_images: int = 1

    def clear(self) -> None:
        with self._lock:
            self.messages.clear()
            self.images.clear()

    def add_message(self, message: str, image=None) -> None:
        with self._lock:
            self.messages.append(message)
            if image is not None and len(self.images) < self.max_images:
                self.images.append(image)


DEFAULT_GROUP_ID = 'one_dragon'


class ApplicationRunContext:
    """应用注册表 + 分组配置 + 运行记录 + 运行状态机（单执行器）。"""

    def __init__(self, ctx):
        self.ctx = ctx
        self.event_bus: ContextEventBus = ContextEventBus()

        self._application_factory_map: dict[str, ApplicationFactory] = {}
        self._group_config_map: dict[tuple, ApplicationGroupConfig] = {}
        self._map_lock = threading.Lock()

        self.notify_pool: NotifyPool = NotifyPool()

        self._run_state = ApplicationRunStateEnum.STOPPED
        self.current_app_id: str | None = None
        self.current_instance_idx: int = getattr(ctx, 'current_instance_idx', 0)
        self.current_group_id: str = DEFAULT_GROUP_ID
        self.current_application: Application | None = None

        self.last_run_result: ApplicationRunResult | None = None
        self.last_application_result = None

        self.default_group_apps: list[ApplicationFactory] = []

    # ------------------------------------------------------------------ #
    # 注册
    # ------------------------------------------------------------------ #

    def registry_application(self, factory: ApplicationFactory) -> None:
        """注册应用工厂；默认组按 PRIORITY 排序维护 default_group_apps。"""
        if factory.app_id in self._application_factory_map:
            raise ValueError(f'应用 app_id 重复注册 {factory.app_id}')
        self._application_factory_map[factory.app_id] = factory
        if factory.default_group:
            self.default_group_apps.append(factory)
            self.default_group_apps.sort(key=lambda f: (getattr(f, 'priority', 999999), f.app_id))
            # 合入组配置（新应用默认禁用，保持用户已有排序与开关）
            self.get_group_config().update_full_app_list(
                [f.app_id for f in self.default_group_apps])

    def get_application_name_map(self) -> dict[str, str]:
        return {app_id: f.app_name for app_id, f in self._application_factory_map.items()}

    def get_factory(self, app_id: str) -> ApplicationFactory:
        factory = self._application_factory_map.get(app_id)
        if factory is None:
            raise ValueError(f'应用未注册 {app_id}')
        return factory

    def get_application(self, app_id: str, instance_idx: int,
                        group_id: str = DEFAULT_GROUP_ID) -> Application:
        factory = self.get_factory(app_id)
        return factory.create_application(instance_idx, group_id)

    # ------------------------------------------------------------------ #
    # 组配置
    # ------------------------------------------------------------------ #

    def get_group_config(self, instance_idx: int | None = None,
                         group_id: str = DEFAULT_GROUP_ID) -> ApplicationGroupConfig:
        if instance_idx is None:
            instance_idx = getattr(self.ctx, 'current_instance_idx', self.current_instance_idx)
        key = (instance_idx, group_id)
        with self._map_lock:
            if key not in self._group_config_map:
                self._group_config_map[key] = ApplicationGroupConfig(
                    instance_idx=instance_idx, group_id=group_id)
            if group_id == DEFAULT_GROUP_ID:
                # Every account needs the registered default applications, including
                # cached empty groups and accounts selected after registration.
                self._group_config_map[key].update_full_app_list(
                    [factory.app_id for factory in self.default_group_apps])
            return self._group_config_map[key]

    def get_group_app_ids(self, instance_idx: int | None = None,
                          group_id: str = DEFAULT_GROUP_ID) -> list[tuple[str, bool]]:
        """返回 [(app_id, enabled)]，按组配置顺序（即用户排序）。"""
        return [(item.app_id, item.enabled) for item in
                self.get_group_config(instance_idx, group_id).app_list]

    # ------------------------------------------------------------------ #
    # 配置与运行记录
    # ------------------------------------------------------------------ #

    def get_config(self, app_id: str, instance_idx: int,
                   group_id: str = DEFAULT_GROUP_ID) -> ApplicationConfig:
        # 工厂创建运行记录时也会获取配置，必须共用工厂缓存，避免完成判定读取旧设置。
        with self._map_lock:
            return self.get_factory(app_id).get_config(instance_idx, group_id)

    def get_run_record(self, app_id: str, instance_idx: int) -> AppRunRecord:
        with self._map_lock:
            return self.get_factory(app_id).get_run_record(instance_idx)

    def is_app_need_notify(self, app_id: str) -> bool:
        try:
            factory = self.get_factory(app_id)
        except ValueError:
            return False
        if not factory.need_notify:
            return False
        notify_config = getattr(self.ctx, 'notify_config', None)
        if notify_config is None:
            return False
        return notify_config.enable_notify

    # ------------------------------------------------------------------ #
    # 状态机
    # ------------------------------------------------------------------ #

    @property
    def is_context_stop(self) -> bool:
        return self._run_state == ApplicationRunStateEnum.STOPPED

    @property
    def is_context_running(self) -> bool:
        return self._run_state == ApplicationRunStateEnum.RUNNING

    @property
    def is_context_pause(self) -> bool:
        return self._run_state == ApplicationRunStateEnum.PAUSE

    def start_running(self) -> bool:
        """STOPPED → RUNNING。成功返回 True。"""
        if self._run_state != ApplicationRunStateEnum.STOPPED:
            return False
        controller = getattr(self.ctx, 'controller', None)
        if controller is not None and hasattr(controller, 'init_before_context_run'):
            controller.init_before_context_run()
        self._run_state = ApplicationRunStateEnum.RUNNING
        self.event_bus.dispatch_event(ApplicationRunContextStateEventEnum.START.value)
        return True

    def switch_context_pause_and_run(self) -> None:
        """RUNNING ↔ PAUSE 切换。"""
        if self._run_state == ApplicationRunStateEnum.RUNNING:
            self._run_state = ApplicationRunStateEnum.PAUSE
            self.event_bus.dispatch_event(ApplicationRunContextStateEventEnum.PAUSE.value)
        elif self._run_state == ApplicationRunStateEnum.PAUSE:
            self._run_state = ApplicationRunStateEnum.RUNNING
            self.event_bus.dispatch_event(ApplicationRunContextStateEventEnum.RESUME.value)

    def stop_running(self) -> ApplicationRunResult:
        """任意状态 → STOPPED（幂等）。"""
        if self._run_state == ApplicationRunStateEnum.STOPPED and self.last_run_result is not None:
            return self.last_run_result
        result = self._finish_running(RunFinishReason.STOPPED)
        return result

    def _finish_running(self, reason: RunFinishReason) -> ApplicationRunResult:
        result = ApplicationRunResult(
            finish_reason=reason,
            app_id=self.current_app_id,
            instance_idx=self.current_instance_idx,
            group_id=self.current_group_id,
        )
        self._run_state = ApplicationRunStateEnum.STOPPED
        self.last_run_result = result
        self.event_bus.dispatch_event(ApplicationRunContextStateEventEnum.STOP.value)
        return result

    # ------------------------------------------------------------------ #
    # 运行入口
    # ------------------------------------------------------------------ #

    def run_application(self, app_id: str, instance_idx: int | None = None,
                        group_id: str = DEFAULT_GROUP_ID,
                        init_timeout: int = 60) -> ApplicationRunResult:
        """同步运行单个应用（含状态机与运行记录更新）。"""
        start_time = time.time()
        if instance_idx is None:
            instance_idx = getattr(self.ctx, 'current_instance_idx', 0)

        app = self.get_application(app_id, instance_idx, group_id)
        if not self.start_running():
            from onedragon.base.operation import dry_run
            dry_run.end_run()
            return ApplicationRunResult(RunFinishReason.NOT_STARTED,
                                        app_id, instance_idx, group_id)

        self.current_app_id = app_id
        self.current_instance_idx = instance_idx
        self.current_group_id = group_id
        self.current_application = app

        log.info(f'开始运行应用 {app.op_name} 实例 {instance_idx}')
        try:
            self.last_application_result = app.execute()
            success = getattr(self.last_application_result, 'success', False)
            if not self.is_context_stop:
                self._finish_running(
                    RunFinishReason.COMPLETED if success else RunFinishReason.FAILED)
            log.info(f'应用运行结束 {app.op_name} 成功={success}')
        except Exception as e:
            log.error(f'应用运行异常 {app.op_name}', exc_info=e)
            self.last_application_result = None
            if not self.is_context_stop:
                self._finish_running(RunFinishReason.FAILED)
        finally:
            self.current_application = None
            from onedragon.base.operation import dry_run
            dry_run.end_run()

        return self.last_run_result
