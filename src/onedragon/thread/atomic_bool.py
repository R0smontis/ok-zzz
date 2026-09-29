# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: one_dragon/thread/atomic_bool.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
import threading


class AtomicBool:
    def __init__(self, value: bool = False):
        self._value: bool = value
        self._lock = threading.Lock()

    def get(self):
        with self._lock:
            return self._value

    def set(self, value: bool):
        with self._lock:
            self._value = value

    def set_true(self):
        with self._lock:
            self._value = True

    def set_false(self):
        with self._lock:
            self._value = False
