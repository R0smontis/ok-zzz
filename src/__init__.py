# -*- coding: utf-8 -*-
"""ok-zzz 源码包自举：确保顶层包（onedragon / zzz_od）可被导入。"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
