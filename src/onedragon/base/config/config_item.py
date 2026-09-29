# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: one_dragon/base/config/config_item.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from enum import Enum
from typing import Optional, Iterable, Any

from onedragon.utils.i18_utils import gt


class ConfigItem:

    def __init__(self, label: str, value: Any = None, desc: Optional[str] = None):
        """
        选项值
        :param label: 显示文本
        :param value: 真实值
        """
        self.label: str = label  # 显示文本
        self.value: Any = label if value is None else value  # 值
        self.desc: str = desc if desc is not None else ''  # 选项解释

    @property
    def ui_text(self) -> str:
        """
        显示的文本
        :return:
        """
        return gt(self.label)


def get_config_item_from_enum(enum: Iterable[Enum], value: Any) -> Optional[ConfigItem]:
    """
    从一个配置枚举中 获取目标配置
    :param enum: 枚举
    :param value: 配置值
    :return:
    """
    for item in enum:
        if not isinstance(item.value, ConfigItem):
            continue
        config_item: ConfigItem = item.value
        if config_item.value == value:
            return config_item
    return None
