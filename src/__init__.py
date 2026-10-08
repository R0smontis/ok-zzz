# -*- coding: utf-8 -*-
"""ok-zzz 源码包自举：确保顶层包（onedragon / zzz_od）可被导入。"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
# 冻结程序已包含 onedragon/zzz_od 顶层包；插入虚拟 src 路径会让
# PyInstaller 把这些导入错误映射到 src.*，导致命名空间配置包无法加载。
if not getattr(sys, 'frozen', False) and _HERE not in sys.path:
    sys.path.insert(0, _HERE)
