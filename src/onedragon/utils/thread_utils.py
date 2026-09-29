# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: one_dragon/utils/thread_utils.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from concurrent.futures import Future

from onedragon.utils.log_utils import log


def handle_future_result(future: Future):
    try:
        future.result()
    except Exception:
        log.error('异步执行失败', exc_info=True)
