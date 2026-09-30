# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: one_dragon/base/controller/pc_screenshot/screencapper_base.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from abc import ABC, abstractmethod

from cv2.typing import MatLike

from onedragon.base.controller.pc_game_window import PcGameWindow
from onedragon.base.geometry.rectangle import Rect


class ScreencapperBase(ABC):
    """截图方法的抽象基类"""

    def __init__(self, game_win: PcGameWindow, standard_width: int, standard_height: int):
        self.game_win: PcGameWindow = game_win
        self.standard_width: int = standard_width
        self.standard_height: int = standard_height

    @abstractmethod
    def init(self) -> bool:
        """初始化截图器

        Returns:
            是否初始化成功
        """
        raise NotImplementedError

    @abstractmethod
    def capture(self, rect: Rect, independent: bool = False) -> MatLike | None:
        """执行截图

        Args:
            rect: 截图区域
            independent: 是否独立截图

        Returns:
            截图图像，失败返回 None
        """
        raise NotImplementedError

    @abstractmethod
    def cleanup(self):
        """清理截图器使用的资源"""
        raise NotImplementedError
