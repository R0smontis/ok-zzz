# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/application/hollow_zero/lost_void/operation/interact/lost_void_artifact_pos.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from typing import Optional

from onedragon.base.geometry.rectangle import Rect
from zzz_od.application.hollow_zero.lost_void.context.lost_void_artifact import LostVoidArtifact


class LostVoidArtifactPos:

    def __init__(
        self,
        art: LostVoidArtifact,
        rect: Rect,
        ocr_text: str = '',
        is_primary_name: bool = True,
    ):
        self.artifact: LostVoidArtifact = art
        self.rect: Rect = rect
        self.ocr_text: str = ocr_text  # OCR原始文本
        self.is_primary_name: bool = is_primary_name  # 是否为 [] / 【】 结构的主选名称

        self.can_choose: bool = True
        self.chosen: bool = False  # 已经被选择了
        self.has_same_style: bool = False  # 有同流派武备
        self.store_price: Optional[int] = None
        self.store_buy_rect: Optional[Rect] = None
        self.is_new: bool = False

    def add_price(self, price: int, rect: Rect) -> bool:
        """
        添加价格
        @return:
        """
        x_dis = abs(self.rect.center.x - rect.center.x)
        if x_dis >= self.rect.width:
            return False

        self.store_price = price
        return True

    def add_buy(self, rect: Rect) -> bool:
        """
        添加购买按钮
        @return:
        """
        x_dis = abs(self.rect.center.x - rect.center.x)
        if x_dis >= self.rect.width:
            return False

        self.store_buy_rect = rect
        return True
