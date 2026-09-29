# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: one_dragon/utils/yaml_utils.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
import yaml
from typing import Any, IO

try:
    from yaml import CSafeLoader as SafeLoader
except ImportError:
    from yaml import SafeLoader


def safe_load(stream: str | bytes | IO[str] | IO[bytes]) -> Any:
    """Safely parse YAML via CSafeLoader when available, else SafeLoader."""
    return yaml.load(stream, Loader=SafeLoader)
