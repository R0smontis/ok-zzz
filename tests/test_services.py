# -*- coding: utf-8 -*-
"""OkOcrMatcher 适配器与游戏配置验证。"""
import numpy as np

from onedragon.base.matcher.ocr.ok_ocr_matcher import OkOcrMatcher


class FakeOnnxOcr:
    """模拟 onnxocr 原始输出: [ [pos, (text, conf)], ... ]"""

    def ocr(self, image):
        h, w = image.shape[:2]
        pos = [[[10, 10], [110, 10], [110, 40], [10, 40]]]
        # 模拟相对坐标：返回值坐标应落在图内
        return [[
            [[[10, 10], [110, 10], [110, 40], [10, 40]], ('普通攻击', 0.97)],
            [[[200, 50], [300, 50], [300, 80], [200, 80]], ('闪避', 0.85)],
        ]]


def test_ocr_adapter_parses_raw_output():
    matcher = OkOcrMatcher(get_lib=lambda: FakeOnnxOcr())
    frame = np.zeros((100, 400, 3), dtype=np.uint8)

    results = matcher.ocr(frame)
    assert len(results) == 2
    first = results[0]
    assert first.data == '普通攻击'
    assert first.x == 10 and first.y == 10
    assert first.w == 100 and first.h == 30
    assert abs(first.confidence - 0.97) < 1e-6

    by_text = matcher.run_ocr(frame)
    assert '普通攻击' in by_text and '闪避' in by_text

    single = matcher.run_ocr_single_line(frame)
    assert '普通攻击' in single and '闪避' in single


def test_game_config_action_keys(ctx):
    """键位默认值与一条龙保持一致，且可读写。"""
    keys = ctx.game_config.get_action_keys('keyboard')
    assert keys['dodge'] == 'shift'
    assert keys['ultimate'] == 'q'
    assert keys['normal_attack'] == 'mouse_left'

    gamepad_keys = ctx.game_config.get_gamepad_action_keys('xbox')
    assert gamepad_keys['menu'] == ['xbox_start']
    assert gamepad_keys['compendium'] == ['xbox_lt', 'xbox_a']
    assert gamepad_keys['city_fund'] == ['xbox_lt', 'xbox_b']
    assert ctx.game_config.get_gamepad_action_keys('ds4')['city_fund'] == ['ds4_l2', 'ds4_circle']


def test_screen_service_scale_consistency(ctx):
    """标准分辨率应为 1920x1080（一条龙 pc_rect 坐标系）。"""
    assert ctx.project_config.screen_standard_width == 1920
    assert ctx.project_config.screen_standard_height == 1080
