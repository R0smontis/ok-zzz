# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: one_dragon/base/controller/pc_screenshot/pil_screencapper.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
import numpy as np
from cv2.typing import MatLike
from pyautogui import screenshot as pyautogui_screenshot

from onedragon.base.controller.pc_screenshot.screencapper_base import ScreencapperBase
from onedragon.base.geometry.rectangle import Rect


class PilScreencapper(ScreencapperBase):
    """使用 PIL (pyautogui) 进行截图的策略"""

    def init(self) -> bool:
        """初始化 PIL 截图方法

        PIL 不需要初始化

        Returns:
            始终返回 True
        """
        return True

    def capture(self, rect: Rect, independent: bool = False) -> MatLike | None:
        """使用 PIL 截图

        Args:
            rect: 截图区域
            independent: 是否独立截图

        Returns:
            截图数组，失败返回 None
        """
        try:
            img = pyautogui_screenshot(region=(rect.x1, rect.y1, rect.width, rect.height))
            screenshot = np.array(img)
        except Exception:
            return None

        return screenshot

    def cleanup(self):
        """PIL不需要清理资源"""
        pass
