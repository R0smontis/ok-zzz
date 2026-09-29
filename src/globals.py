# -*- coding: utf-8 -*-
"""ok-zzz 全局单例（ok-script my_app）。

持有 ZzzContext（战斗引擎装配点），并桥接 ok-script 运行时：
- OCR: og.app.executor.ocr_lib('default')（onnxocr）
- 截图: og.executor.next_frame / frame
"""
import time

from ok import Logger, OkGlobals  # noqa: F401
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
        """控制器截图委托：强制取新帧并返回 (截图时间, 帧)。"""
        og.executor.next_frame()
        return time.time(), og.executor.frame

    @property
    def context(self):
        """ZzzContext 惰性创建（需要 ok-script 完成设备初始化后调用）。"""
        if self._context is None:
            from zzz_od.context.zzz_context import ZContext
            self._context = ZContext(
                get_ocr_lib=self._get_ocr_lib if og.executor is not None else None,
                frame_provider=self._frame_provider,
            )
            self._context.init()
            logger.info('ZzzContext 已创建并初始化')
        return self._context

    def ensure_context_for_game(self):
        """游戏启动后的完整初始化（画面区域等）。"""
        self.context.init_for_application()
        return self.context
