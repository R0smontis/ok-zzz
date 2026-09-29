# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: one_dragon/base/matcher/ocr/ocr_match_result.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from onedragon.base.matcher.match_result import MatchResult


class OcrMatchResult(MatchResult):

    def __init__(
            self,
            c: float,
            x: float | int,
            y: float | int,
            w: float | int,
            h: float | int,
            template_scale: float = 1,
            data: str | None = None
    ):
        MatchResult.__init__(
            self,
            c=c,
            x=x,
            y=y,
            w=w,
            h=h,
            template_scale=template_scale,
            data=data
        )
        self.data: str = data
