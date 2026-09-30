# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: one_dragon_qt/overlay/overlay_events.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class OverlayEventEnum(StrEnum):
    """Overlay module events published on ContextEventBus."""

    OVERLAY_LOG = "overlay_log"


@dataclass(slots=True)
class OverlayLogEvent:
    """Overlay log payload."""

    created: float
    level_name: str
    message: str
    filename: str
    lineno: int

