# -*- coding: utf-8 -*-
"""ok-zzz 全局单例（ok-script my_app）。

持有 ZzzContext（战斗引擎与应用框架装配点），并桥接 ok-script 运行时：
- OCR: og.app.executor.ocr_lib('default')（onnxocr）
- 截图: og.executor.next_frame / frame
- 应用注册: discover_factories(ctx)
"""
import time

from ok import Logger
from ok import og

logger = Logger.get_logger(__name__)


class Globals:

    def __init__(self, exit_event):
        super().__init__()
        self.exit_event = exit_event
        self._context = None

    # ------------------------------------------------------------------ #
    # ok-script 桥接
    # ------------------------------------------------------------------ #

    def _get_ocr_lib(self):
        """返回 ok-script 的 onnxocr 实例（供 OkOcrMatcher 惰性调用）。"""
        return og.executor.ocr_lib('default')

    def _frame_provider(self):
        """控制器帧源委托：强制取新帧并返回 (截图时间, 帧)。"""
        og.executor.next_frame()
        return time.time(), og.executor.frame

    @property
    def context(self):
        """ZzzContext 惰性创建（需要 ok-script 完成设备初始化后调用）。"""
        if self._context is None:
            from zzz_od.application.app_registry import discover_factories
            from zzz_od.context.zzz_context import ZContext
            context = ZContext(
                get_ocr_lib=self._get_ocr_lib if og.executor is not None else None,
                frame_provider=self._frame_provider,
            )
            discover_factories(context)
            context.init()
            self._context = context
            logger.info('ZzzContext 已创建并完成应用注册')
        return self._context

    def ensure_context_for_game(self):
        """游戏启动后的完整初始化（画面区域等）。"""
        self.context.init_for_application()
        return self.context

    def ensure_overlay(self):
        """游戏内悬浮窗（识别框/HUD/日志面板，热键 o 开关）；失败静默。"""
        if self._context is None:
            return None
        if getattr(self, '_overlay_manager', None) is not None:
            return self._overlay_manager
        try:
            from onedragon.qt.overlay.overlay_manager import OverlayManager
            self._overlay_manager = OverlayManager(self._context)
            self._overlay_manager.start()
            logger.info('Overlay 已启动（热键 o 开关）')
            return self._overlay_manager
        except Exception as e:
            logger.warning(f'Overlay 启动失败（不影响核心功能）: {e}')
            self._overlay_manager = None
            return None
