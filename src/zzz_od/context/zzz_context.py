# -*- coding: utf-8 -*-
"""ok-zzz 总上下文（ZContext，兼容一条龙命名与属性面）。

装配一条龙全部框架能力：多账号实例、应用运行上下文、识别服务
（画面/模板/CV 流水线/OCR）、控制器（键鼠+虚拟手柄）、战斗引擎。
区别于原版 OneDragonContext：环境管理（envs）、代码自更新、
推送服务等由 ok-script / 后续阶段承担。
"""
from onedragon.base.config.custom_config import CustomConfig
from onedragon.base.config.game_account_config import GameAccountConfig
from onedragon.base.config.notify_config import NotifyConfig
from onedragon.base.config.one_dragon_config import OneDragonConfig
from onedragon.base.cv_process.cv_service import CvService
from onedragon.base.debug.debug_trace_bus import DebugTraceBus
from onedragon.base.matcher.ocr.ok_ocr_matcher import OkOcrMatcher
from onedragon.base.matcher.ocr.ocr_service import OcrService
from onedragon.base.matcher.template_matcher import TemplateMatcher
from onedragon.base.operation.application.application_run_context import (
    ApplicationRunContext,
)
from onedragon.base.operation.context_event_bus import ContextEventBus
from onedragon.base.screen.screen_loader import ScreenContext
from onedragon.base.screen.template_loader import TemplateLoader
from onedragon.envs.env_config import EnvConfig
from onedragon.envs.repo_config import RepoConfig
from onedragon.utils.log_utils import log
from zzz_od.config.game_config import GameConfig
from zzz_od.config.model_config import ModelConfig
from zzz_od.controller.zzz_controller import ZzzController

# 实例级配置：切换实例时需要清除的缓存属性名
_INSTANCE_CONFIG_PROPS = (
    'game_config',
    'battle_assistant_config',
    'team_config',
    'game_account_config',
    'notify_config',
    'env_config',
)


class ZContext(ContextEventBus):
    """全功能总上下文。

    Attributes:
        run_context: 应用注册表 / 分组 / 运行记录 / 状态机
        one_dragon_config: 多账号实例配置
        controller: 绝区零控制器（键鼠 / 虚拟手柄 / 截图）
        auto_battle_context: 自动战斗引擎入口
    """

    def __init__(self, get_ocr_lib=None, frame_provider=None):
        """
        Args:
            get_ocr_lib: 返回 ok-script OCR 实例的 callable；None 时 OCR 不可用
            frame_provider: 控制器帧源 callable() -> (time, frame)
        """
        ContextEventBus.__init__(self)

        # 多账号实例
        self.one_dragon_config: OneDragonConfig = OneDragonConfig()
        if self.one_dragon_config.current_active_instance is None:
            self.one_dragon_config.create_new_instance(True)
        self.current_instance_idx: int = self.one_dragon_config.current_active_instance.idx

        # 全局识别与调试
        self.debug_trace_bus: DebugTraceBus = DebugTraceBus()
        self.screen_loader: ScreenContext = ScreenContext()
        self.template_loader: TemplateLoader = TemplateLoader()
        self.tm: TemplateMatcher = TemplateMatcher(
            self.template_loader, debug_trace_bus=self.debug_trace_bus
        )
        self._get_ocr_lib = get_ocr_lib
        self._ocr: OkOcrMatcher | None = None
        self._ocr_service: OcrService | None = None

        self.cv_service: CvService = CvService(self)

        # 应用运行上下文（注册应用见 app_registry）
        self.run_context: ApplicationRunContext = ApplicationRunContext(self)

        # 控制器（惰性创建，见 init_controller）
        self.controller: ZzzController | None = None
        self._frame_provider = frame_provider

        self._inited: bool = False

    # ------------------------------------------------------------------ #
    # 惰性组件
    # ------------------------------------------------------------------ #

    def _get_or_create(self, prop: str, factory):
        """实例级配置的缓存读取；switch_instance 时清除。"""
        if prop in self.__dict__:
            return self.__dict__[prop]
        value = factory()
        self.__dict__[prop] = value
        return value

    @property
    def model_config(self) -> ModelConfig:
        return self._get_or_create('model_config', lambda: ModelConfig(RepoConfig()))

    @property
    def game_config(self) -> GameConfig:
        return self._get_or_create(
            'game_config', lambda: GameConfig(self.current_instance_idx))

    @property
    def battle_assistant_config(self):
        from zzz_od.application.battle_assistant.battle_assistant_config import (
            BattleAssistantConfig,
        )
        return self._get_or_create(
            'battle_assistant_config',
            lambda: BattleAssistantConfig(self.current_instance_idx))

    @property
    def team_config(self):
        from zzz_od.config.team_config import TeamConfig
        return self._get_or_create(
            'team_config', lambda: TeamConfig(self.current_instance_idx))

    @property
    def game_account_config(self) -> GameAccountConfig:
        return self._get_or_create(
            'game_account_config',
            lambda: GameAccountConfig(self.current_instance_idx))

    @property
    def env_config(self) -> EnvConfig:
        return self._get_or_create(
            'env_config', lambda: EnvConfig(self.current_instance_idx))

    @property
    def project_config(self) -> 'SimpleNamespace':
        """标准分辨率（原版 project_config 中被引用的字段子集）。"""
        from types import SimpleNamespace
        return self._get_or_create(
            'project_config',
            lambda: SimpleNamespace(screen_standard_width=1920,
                                    screen_standard_height=1080))

    @property
    def custom_config(self) -> CustomConfig:
        return self._get_or_create('custom_config', lambda: CustomConfig())

    @property
    def notify_config(self) -> NotifyConfig:
        return self._get_or_create(
            'notify_config',
            lambda: NotifyConfig(self.current_instance_idx,
                                 self.run_context.get_application_name_map()))

    @property
    def push_service(self):
        """推送服务（24 渠道，配置见 notify.yml）。"""
        return self._get_or_create('push_service', lambda: self._new_push_service())

    def _new_push_service(self):
        from onedragon.base.push.push_service import PushService
        try:
            return PushService(self)
        except Exception as e:
            log.warning(f'推送服务初始化失败（已停用）: {e}')
            return None

    @property
    def ocr(self) -> OkOcrMatcher | None:
        if self._ocr is None and self._get_ocr_lib is not None:
            self._ocr = OkOcrMatcher(self._get_ocr_lib)
            self._ocr_service = OcrService(ocr_matcher=self._ocr)
        return self._ocr

    @property
    def ocr_service(self) -> OcrService | None:
        _ = self.ocr  # 确保成对初始化
        return self._ocr_service

    # ------------------------------------------------------------------ #
    # 控制器
    # ------------------------------------------------------------------ #

    def init_controller(self) -> None:
        """按当前实例配置创建控制器（幂等；切换输入方式时复用对象）。"""
        if self.controller is None:
            self.controller = ZzzController(
                self.game_config,
                screenshot_method=self.env_config.screenshot_method,
                frame_provider=self._frame_provider,
            )
        else:
            self.controller.sync_game_config(self.game_config)

    def set_frame_provider(self, frame_provider) -> None:
        """注入 ok-script 帧源（Globals 在设备就绪后调用）。"""
        self._frame_provider = frame_provider
        if self.controller is not None:
            self.controller.frame_provider = frame_provider

    # ------------------------------------------------------------------ #
    # 多账号实例
    # ------------------------------------------------------------------ #

    def switch_instance(self, instance_idx: int) -> None:
        """切换账号实例：清实例级配置缓存 + 同步控制器。"""
        self.one_dragon_config.active_instance(instance_idx)
        self.current_instance_idx = self.one_dragon_config.current_active_instance.idx
        self.reload_instance_config()
        self.dispatch_event('instance_active', instance_idx)
        log.info(f'切换到实例 {instance_idx}')

    def reload_instance_config(self) -> None:
        for prop in _INSTANCE_CONFIG_PROPS:
            self.__dict__.pop(prop, None)
        if self.controller is not None:
            self.controller.sync_game_config(self.game_config)

    @property
    def instance_list_in_od(self):
        """一条龙需要运行的实例列表（尊重临时实例 -i 参数）。"""
        return self.one_dragon_config.instance_list_in_od

    # ------------------------------------------------------------------ #
    # 事件与初始化
    # ------------------------------------------------------------------ #

    def notify_event(self, title: str, content: str) -> None:
        """上下文通知（原版分发到 overlay/推送；此处记录日志）。"""
        log.info(f'[通知] {title}: {content}')

    def init(self) -> None:
        """加载画面数据等运行前置（幂等）。"""
        if self._inited:
            return
        self.screen_loader.reload()
        self._inited = True
        log.info('ZzzContext 初始化完成')

    def init_for_application(self) -> None:
        """应用运行前刷新（与一条龙同名方法语义一致）。"""
        self.init()
        self.init_controller()
        self.auto_battle_context.init_screen_area()

    @property
    def auto_battle_context(self):
        """战斗引擎（惰性导入以打破循环依赖）。"""
        if '_auto_battle_context' not in self.__dict__:
            from zzz_od.auto_battle.auto_battle_context import AutoBattleContext
            self.__dict__['_auto_battle_context'] = AutoBattleContext(self)
        return self.__dict__['_auto_battle_context']

    def after_app_shutdown(self) -> None:
        """进程退出前清理资源。"""
        try:
            self.auto_battle_context.after_app_shutdown()
        except Exception as e:
            log.warning(f'战斗引擎清理异常: {e}')
