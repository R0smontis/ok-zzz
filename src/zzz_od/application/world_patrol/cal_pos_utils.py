# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/application/world_patrol/cal_pos_utils.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from cv2.typing import MatLike

from onedragon.base.geometry.point import Point
from onedragon.base.geometry.rectangle import Rect
from onedragon.base.matcher.match_result import MatchResult
from onedragon.utils import cv2_utils


def cal_pos(
        large_map: MatLike,
        mini_map: MatLike,
        last_pos: Point | None = None,
) -> MatchResult | None:
    """
    计算小地图在大地图上的坐标

    Args:
        large_map: 大地图
        mini_map: 小地图
        last_pos: 上一次的坐标

    Returns:
        MatchResult: 计算坐标
    """
    if last_pos is None:
        source = large_map
        rect = None
    else:
        rect = Rect(
            last_pos.x - mini_map.shape[1] * 2,
            last_pos.y - mini_map.shape[0] * 2,
            last_pos.x + mini_map.shape[1] * 2,
            last_pos.y + mini_map.shape[0] * 2,
        )
        source, rect = cv2_utils.crop_image(large_map, rect)

    mrl = cv2_utils.match_template(
        source=source,
        template=mini_map,
        threshold=0.1,
        ignore_inf=True,
    )

    if rect is not None:
        mrl.add_offset(rect.left_top)

    return mrl.max
