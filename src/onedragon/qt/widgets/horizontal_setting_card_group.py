# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: one_dragon_qt/widgets/horizontal_setting_card_group.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QWidget


class HorizontalSettingCardGroup(QWidget):
    """水平布局的设置卡片组，用于在一行中显示多个设置卡片"""

    def __init__(
        self,
        cards: list[QWidget] | None = None,
        spacing: int = 2,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent=parent)

        # 创建水平布局
        self.h_layout = QHBoxLayout(self)
        self.h_layout.setContentsMargins(0, 0, 0, 0)
        self.h_layout.setSpacing(spacing)
        self.h_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 设置固定高度，确保与设置卡片高度一致
        self.setFixedHeight(50)

        # 添加卡片
        if cards:
            for card in cards:
                self.add_card(card)

    def add_card(self, card: QWidget) -> None:
        """添加设置卡片到布局中"""
        card.setParent(self)
        # 确保卡片垂直居中对齐
        self.h_layout.addWidget(card, 1, Qt.AlignmentFlag.AlignTop)

    def add_cards(self, cards: list[QWidget]) -> None:
        """批量添加设置卡片"""
        for card in cards:
            self.add_card(card)
