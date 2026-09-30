# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: one_dragon_qt/widgets/setting_card/yaml_config_adapter.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from typing import Any, Optional

from onedragon.base.config.yaml_operator import YamlOperator


class YamlConfigAdapter:

    def __init__(self, config: YamlOperator, field: str, default_val: Any = None,
                 getter_convert: Optional[str] = None,
                 setter_convert: Optional[str] = None):
        self.config: YamlOperator = config
        self.field: str = field
        self.default_val: Any = default_val
        self.getter_convert: Optional[str] = getter_convert
        self.setter_convert: Optional[str] = setter_convert

    def get_value(self) -> Any:
        # 获取self.field对应的property属性的值
        val = getattr(self.config, self.field)
        if self.getter_convert == 'str':
            return str(val)
        elif self.getter_convert == 'int':
            return int(val)
        elif self.getter_convert == 'float':
            return float(val)
        else:
            return val

    def set_value(self, new_value: Any) -> None:
        if self.setter_convert == 'str':
            val = str(new_value)
        elif self.setter_convert == 'int':
            val = int(new_value)
        elif self.setter_convert == 'float':
            val = float(new_value)
        else:
            val = new_value

        self.config.update(self.field, val)
