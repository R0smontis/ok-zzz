# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/screen_area/screen_normal_world.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from enum import Enum

from onedragon.base.geometry.rectangle import Rect
from onedragon.base.screen.screen_area import ScreenArea


class ScreenNormalWorldEnum(Enum):

    UID = ScreenArea(area_name='uid', pc_rect=Rect(1814, 1059, 1919, 1079))
