# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: one_dragon/base/controller/pc_screenshot/bitblt_screencapper.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
import ctypes

from cv2.typing import MatLike

from onedragon.base.controller.pc_screenshot.gdi_screencapper_base import (
    GdiCaptureContext,
    GdiScreencapperBase,
)
from onedragon.base.geometry.rectangle import Rect

# WinAPI / GDI constants
SRCCOPY = 0x00CC0020


class BitBltScreencapper(GdiScreencapperBase):
    """使用 BitBlt API 直接截取窗口区域的策略"""

    def capture(self, rect: Rect, independent: bool = False) -> MatLike | None:
        """获取窗口区域截图

        Args:
            rect: 截图区域（窗口在屏幕上的坐标）
            independent: 是否独立截图

        Returns:
            截图数组，失败返回 None
        """
        if independent:
            return self._capture_independent(0, rect.width, rect.height, src_x=rect.x1, src_y=rect.y1)
        else:
            return self._capture_shared(0, rect.width, rect.height, src_x=rect.x1, src_y=rect.y1)

    def _do_capture(self, context: GdiCaptureContext) -> bool:
        """使用 BitBlt API 执行截图

        Args:
            context: 截图上下文

        Returns:
            是否截图成功
        """
        return ctypes.windll.gdi32.BitBlt(
            context.mfcDC, 0, 0, context.width, context.height,
            context.hwndDC, context.src_x, context.src_y, SRCCOPY
        )
