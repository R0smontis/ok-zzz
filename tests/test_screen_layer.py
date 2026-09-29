# -*- coding: utf-8 -*-
"""画面/模板识别层移植验证。"""
import cv2
import numpy as np

from onedragon.utils import os_utils


def test_screen_data_loaded(ctx):
    """一条龙 80 个画面 YAML 应全部加载。"""
    assert len(ctx.screen_loader.screen_info_list) >= 79


def test_get_battle_area(ctx):
    """战斗画面按键区域应可解析（1920x1080 坐标系）。"""
    area = ctx.screen_loader.get_area('战斗画面', '按键-普通攻击')
    assert area is not None
    assert area.rect.width > 0 and area.rect.height > 0


def test_template_closed_loop_match(ctx):
    """把真实模板贴进合成帧，模板匹配应找回其位置。"""
    sub_dir, template_id = 'battle', 'btn_dodge'
    info = ctx.template_loader.load_template(sub_dir, template_id)
    assert info is not None, 'btn_dodge 模板应存在'
    tpl = info.get_image('raw')
    assert tpl is not None and tpl.size > 0

    frame = np.full((1080, 1920, 3), 40, dtype=np.uint8)
    expect_x, expect_y = 960, 800
    h, w = tpl.shape[:2]
    frame[expect_y:expect_y + h, expect_x:expect_x + w] = tpl

    result = ctx.tm.match_template(frame, sub_dir, template_id, threshold=0.8)
    assert result.max is not None, '应匹配到贴图位置'
    best = result.max
    assert abs(best.x - expect_x) <= 3
    assert abs(best.y - expect_y) <= 3
