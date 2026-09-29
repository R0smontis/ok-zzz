# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: one_dragon/base/operation/context_notify_event.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import ClassVar


class ContextNotifyLevelEnum(Enum):
    """上下文通知级别。"""

    INFORMATION = "information"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


@dataclass(slots=True)
class ContextNotifyEvent:
    """上下文通知事件体。"""

    EVENT_ID: ClassVar[str] = 'context_notify'

    title: str
    content: str
    level: ContextNotifyLevelEnum = ContextNotifyLevelEnum.INFORMATION

    @classmethod
    def info(cls, title: str, content: str) -> ContextNotifyEvent:
        """创建普通通知。"""
        return cls(title=title, content=content, level=ContextNotifyLevelEnum.INFORMATION)

    @classmethod
    def success(cls, title: str, content: str) -> ContextNotifyEvent:
        """创建成功通知。"""
        return cls(title=title, content=content, level=ContextNotifyLevelEnum.SUCCESS)

    @classmethod
    def warning(cls, title: str, content: str) -> ContextNotifyEvent:
        """创建警告通知。"""
        return cls(title=title, content=content, level=ContextNotifyLevelEnum.WARNING)

    @classmethod
    def error(cls, title: str, content: str) -> ContextNotifyEvent:
        """创建错误通知。"""
        return cls(title=title, content=content, level=ContextNotifyLevelEnum.ERROR)
