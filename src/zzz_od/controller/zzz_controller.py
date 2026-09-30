# -*- coding: utf-8 -*-
"""绝区零控制器（ok-zzz）。

继承移植版 ZPcController（完整一条龙控制器栈：截图 capper、键鼠、
虚拟手柄、窗口管理），仅增加 ok-script 帧源注入：battle 引擎等
高频取帧场景可走 ok-script 的 WGC/BitBlt 截图，其余行为不变。
"""
import time

from cv2.typing import MatLike

from zzz_od.config.game_config import GameConfig
from zzz_od.controller.zzz_pc_controller import ZPcController


class ZzzController(ZPcController):

    def __init__(self,
                 game_config: GameConfig,
                 screenshot_method: str = 'auto',
                 standard_width: int = 1920,
                 standard_height: int = 1080,
                 frame_provider=None):
        """
        Args:
            frame_provider: callable() -> (timestamp, frame)。设置后
                screenshot() 优先使用（ok-script 捕获），否则走原版 capper。
        """
        ZPcController.__init__(self,
                               game_config=game_config,
                               screenshot_method=screenshot_method,
                               standard_width=standard_width,
                               standard_height=standard_height)
        self.frame_provider = frame_provider

    def screenshot(self) -> tuple[float, MatLike | None]:
        if self.frame_provider is not None:
            try:
                return self.frame_provider()
            except Exception:
                pass  # ok-script 帧不可用时回退原版 capper
        return ZPcController.screenshot(self)

    def sync_frames(self) -> tuple[float, MatLike | None]:
        """强制使用原版 capper 取帧（避免死循环调用 frame_provider）。"""
        return ZPcController.screenshot(self)

    def wait_frame(self, timeout: float = 5) -> tuple[float, MatLike | None] | None:
        """等待一帧（供需要帧间步进的应用使用）。"""
        start = time.time()
        while time.time() - start < timeout:
            t, frame = self.screenshot()
            if frame is not None:
                return t, frame
            time.sleep(0.05)
        return None
