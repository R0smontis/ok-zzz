# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: one_dragon_qt/widgets/setting_card/help_card.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from qfluentwidgets import FluentIcon, HyperlinkCard
from onedragon.utils.i18_utils import gt


class HelpCard(HyperlinkCard):
    def __init__(self,
                 url: str = '',
                 text: str = '点此查看指南',
                 title: str = '使用说明',
                 content: str = '先看说明 再使用与提问',
                 parent=None):
        super().__init__(url, text, FluentIcon.HELP, gt(title), gt(content), parent)
        self.setFixedHeight(50)
        if not url:
            self.linkButton.setVisible(False)