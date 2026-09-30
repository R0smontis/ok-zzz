# -*- coding: utf-8 -*-
"""YamlConfigAdapter compat：原版 Qt 设置卡的配置绑定器。

ok-zzz 用 ok-script 选项桥承载 GUI，此处仅保留"字段读写"语义，
供移植代码中的类型引用与潜在运行时使用。
"""
from typing import Any, Callable


class YamlConfigAdapter:

    def __init__(self, config, field: str,
                 getter_convert: Callable[[Any], Any] = None,
                 setter_convert: Callable[[Any], Any] = None):
        self._config = config
        self._field = field
        self._getter_convert = getter_convert
        self._setter_convert = setter_convert

    def get_value(self):
        value = self._config.get(self._field)
        if self._getter_convert is not None and value is not None:
            value = self._getter_convert(value)
        return value

    def update_value(self, value) -> None:
        if self._setter_convert is not None and value is not None:
            value = self._setter_convert(value)
        self._config.update(self._field, value)

    @property
    def value(self):
        return self.get_value()

    @value.setter
    def value(self, new_value) -> None:
        self.update_value(new_value)
