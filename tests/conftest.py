# -*- coding: utf-8 -*-
"""pytest 公共夹具：确保工作目录为项目根，构建共享 ZzzContext。"""
import os
import sys
import time

import pytest
import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))
os.chdir(PROJECT_ROOT)


@pytest.fixture(scope='session')
def ctx():
    """共享 ZzzContext（无 OCR、无帧源，供引擎/识别层测试）。"""
    from zzz_od.context.zzz_context import ZContext
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    context = ZContext(get_ocr_lib=None, frame_provider=lambda: (time.time(), frame))
    context.init_for_application()
    yield context
    try:
        context.auto_battle_context.after_app_shutdown()
        # 等待已开始的模板加载完成，避免测试捕获流关闭后后台线程继续写日志。
        future = context.auto_battle_context.dodge_context._audio_template_future
        if future is not None and not future.cancelled():
            future.result(timeout=15)
    except Exception:
        pass


class BtnRecorder:
    """替身按键控制器：记录动作而不真实敲键。"""

    def __init__(self):
        self.key_press_time = 0.02
        self.events: list[tuple[str, str]] = []

    def tap(self, key):
        if key:
            self.events.append(('tap', str(key)))

    def press(self, key, press_time=None):
        if key:
            self.events.append(('press', str(key)))

    def release(self, key):
        if key:
            self.events.append(('release', str(key)))

    def reset(self):
        self.events.clear()

    def set_key_press_time(self, t):
        self.key_press_time = t

    def has(self, action_prefix: str) -> bool:
        return any(ev[0] == 'tap' for ev in self.events)


@pytest.fixture()
def stubbed_controller(ctx):
    """把战斗动作导向 BtnRecorder，避免测试真实敲键。"""
    recorder = BtnRecorder()
    controller = ctx.controller
    original_btn = controller.btn_controller
    controller.btn_controller = recorder
    yield ctx, recorder
    controller.btn_controller = original_btn
