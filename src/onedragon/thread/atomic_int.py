# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: one_dragon/thread/atomic_int.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
import threading


class AtomicInt:
    def __init__(self, value=0):
        self.value = value
        self.lock = threading.Lock()

    def get(self):
        with self.lock:
            return self.value

    def set(self, value):
        with self.lock:
            self.value = value

    def inc(self):
        with self.lock:
            self.value += 1
    def dec(self):
        with self.lock:
            self.value -= 1
