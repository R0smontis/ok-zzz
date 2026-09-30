# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/hollow_zero/event/event_ocr_result_handler.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from typing import Callable, Optional

from onedragon.base.geometry.rectangle import Rect
from onedragon.base.operation.operation_round_result import OperationRoundResult


class EventOcrResultHandler:

    def __init__(self, target_cn: str,
                 method: Optional[Callable[[str, Rect], OperationRoundResult]] = None,
                 click_result: bool = True,
                 click_wait: float = 0.5,
                 lcs_percent: float = 0.5,
                 is_event_mark: bool = False,
                 status: Optional[str] = None
                 ):

        self.target_cn: str = target_cn
        self.lcs_percent: float = lcs_percent
        self.method: Callable[[str, Rect], OperationRoundResult] = method
        self.click_result: bool = click_result
        self.click_wait: float = click_wait
        self.is_event_mark = is_event_mark
        self.status: str = target_cn if status is None else status
