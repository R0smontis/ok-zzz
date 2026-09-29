# -*- coding: utf-8 -*-
"""ok-zzz 总上下文（ZContext，兼容一条龙命名）。

对齐 ZenlessZoneZero-OneDragon (GPL-3.0) ZContext 中战斗引擎所需的
属性面（controller / screen_loader / tm / ocr_service / cv_service /
model_config / battle_assistant_config / env_config / project_config /
debug_trace_bus），但装配方式改为 ok-script 全局对象注入。
"""
from types import SimpleNamespace

from onedragon.base.debug.debug_trace_bus import DebugTraceBus
from onedragon.base.matcher.ocr.ok_ocr_matcher import OkOcrMatcher
from onedragon.base.matcher.ocr.ocr_service import OcrService
from onedragon.base.matcher.template_matcher import TemplateMatcher
from onedragon.base.operation.context_event_bus import ContextEventBus
from onedragon.base.screen.screen_loader import ScreenContext
from onedragon.base.screen.template_loader import TemplateLoader
from onedragon.base.cv_process.cv_service import CvService
from onedragon.utils.log_utils import log
from zzz_od.config.battle_assistant_config import BattleAssistantConfig
from zzz_od.config.game_config import GameConfig
from zzz_od.config.model_config import ModelConfig
from zzz_od.controller.zzz_controller import ZzzController


class ZContext(ContextEventBus):
    """战斗引擎及其依赖的装配点。

    Attributes:
        controller: 绝区零控制器（键鼠/虚拟手柄）
        screen_loader: 画面定义加载器（assets/game_data/screen_info）
        tm: 模板匹配服务（assets/template）
        ocr / ocr_service: OCR（由 ok-script 的 onnxocr 适配而来）
        auto_battle_context: 自动战斗引擎入口
    """

    def __init__(self, get_ocr_lib=None, frame_provider=None):
        """
        Args:
            get_ocr_lib: 返回 ok-script OCR 实例的 callable；为 None 时
                OCR 服务不可用（可用于纯单测场景）。
            frame_provider: 控制器截图 callable() -> (time, frame)
        """
        ContextEventBus.__init__(self)

        # 配置
        self.game_config: GameConfig = GameConfig()
        self.battle_assistant_config: BattleAssistantConfig = BattleAssistantConfig()
        self.model_config: ModelConfig = ModelConfig()

        # 一条龙 env_config 中战斗引擎只用到代理字段；ok-zzz 默认直连
        self.env_config: SimpleNamespace = SimpleNamespace(
            is_gh_proxy=False,
            gh_proxy_url=None,
            is_personal_proxy=False,
            personal_proxy=None,
        )

        # 标准分辨率（一条龙 project_config 中只用到这两个字段）
        self.project_config: SimpleNamespace = SimpleNamespace(
            screen_standard_width=1920,
            screen_standard_height=1080,
        )

        # 识别与调试
        self.debug_trace_bus: DebugTraceBus = DebugTraceBus()
        self.screen_loader: ScreenContext = ScreenContext()
        self.template_loader: TemplateLoader = TemplateLoader()
        self.tm: TemplateMatcher = TemplateMatcher(
            self.template_loader, debug_trace_bus=self.debug_trace_bus
        )
        self.ocr: OkOcrMatcher | None = None
        self.ocr_service: OcrService | None = None
        if get_ocr_lib is not None:
            self.ocr = OkOcrMatcher(get_ocr_lib)
            self.ocr_service = OcrService(ocr_matcher=self.ocr)
        self.cv_service: CvService = CvService(self)

        # 控制
        self.controller: ZzzController = ZzzController(
            self.game_config, frame_provider=frame_provider
        )

        # 战斗引擎（在 controller 之后创建；惰性导入以打破循环依赖）
        from zzz_od.auto_battle.auto_battle_context import AutoBattleContext

        self.auto_battle_context: AutoBattleContext = AutoBattleContext(self)

        self._inited: bool = False

    def init(self) -> None:
        """加载画面数据等运行前置（幂等）。"""
        if self._inited:
            return
        self.screen_loader.reload()
        self._inited = True
        log.info('ZzzContext 初始化完成')

    def init_for_application(self) -> None:
        """与一条龙对齐的入口：应用运行前刷新服务数据。"""
        self.init()
        self.auto_battle_context.init_screen_area()
