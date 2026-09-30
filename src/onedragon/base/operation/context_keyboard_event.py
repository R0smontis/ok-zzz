# -*- coding: utf-8 -*-
"""键盘事件枚举（compat：自 one_dragon_context 拆出，避免引入整个总上下文）。"""
from enum import Enum


class ContextKeyboardEventEnum(Enum):

    PRESS = 'context_keyboard_press'


class ContextInstanceEventEnum(Enum):

    instance_active = 'instance_active'
