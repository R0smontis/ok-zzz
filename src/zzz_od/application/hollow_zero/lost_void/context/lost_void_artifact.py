# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/application/hollow_zero/lost_void/context/lost_void_artifact.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
class LostVoidArtifact:

    def __init__(self, category: str, name: str, level: str,
                 is_gear: bool = False,
                 template_id: str | None = None):
        self.category: str = category  # 分类
        self.name: str = name  # 名称
        self.level: str = level  # 等级
        self.is_gear: bool = is_gear  # 是否武备
        self.template_id: str | None = template_id  # 模板ID 仅部分武备有

    @property
    def display_name(self) -> str:
        """
        游戏中显示的完整名字
        :return:
        """
        if self.category not in ['卡牌', '无详情']:
            return f'[{self.category}]{self.name}'
        else:
            return self.name
