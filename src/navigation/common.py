# -*- coding: utf-8 -*-
"""导航层共用小工具：OCR 读取、文本归一化、有界计数、遮罩与切片。

每个 navigation 模块都在重复同一套循环：读当前帧 → 归一化 OCR 文本 → 核验唯一焦点 →
按一次手柄键 → 用各自的计数器设上限。这里把其中逐字重复的部分收成一处，
各模块的公开函数与返回语义保持不变（移植代码与测试都从原模块导入）。
"""
import numpy as np

from onedragon.base.geometry.rectangle import Rect


WHOLE_SCREEN = Rect(0, 0, 1920, 1080)
MAP_CURSOR = (695, 540)

# 各模块的 OCR 误读修正表（与迁移前逐文件写法一一对应）。
OCR_FIXES = {
    'hdd': (('·', ''),),
    'hollow': (('枯菱', '枯萎'), ('廈', '厦'), ('・', '-'), ('·', '-')),
    'hollow_events': (('【', '['), ('】', ']')),
    'map': (('「', ''), ('」', '')),
    'redemption': (('兌', '兑'), ('換', '换')),
}


def norm_text(value, module=None, fixes=()):
    """去空格并按模块修正 OCR 误读；调用方各自补充 strip 等额外处理。"""
    text = str(value).replace(' ', '')
    for old, new in (OCR_FIXES[module] if module else fixes):
        text = text.replace(old, new)
    return text


def ocr_rows(op, screen, rect=None, **kwargs):
    """当前帧的 OCR 行；未知画面时读取器可能返回 None，统一成列表。"""
    rows = op.ctx.ocr_service.get_ocr_result_list(
        image=screen, rect=WHOLE_SCREEN if rect is None else rect, **kwargs)
    return rows if isinstance(rows, (list, tuple)) else []


def bump(op, name, limit):
    """流程内计数器：超过 `limit` 后返回 True（调用方据此报失败）。"""
    value = op.__dict__.get(name, 0) + 1
    op.__dict__[name] = value
    return value > limit


def cjk_count(text):
    return sum('一' <= c <= '鿿' for c in str(text))


def has_cjk(row, minimum=2):
    return cjk_count(getattr(row, 'data', '')) >= minimum


def in_rect(point, rect):
    return rect.x1 <= point.x < rect.x2 and rect.y1 <= point.y < rect.y2


def focus_mask(part):
    """手柄焦点填充：在黄色(≈247,219,0)与黄绿(≈152,190,0)之间脉动。"""
    return (part[:, :, 0] > 120) & (part[:, :, 1] > 150) & (part[:, :, 2] < 100)


def lit(mask, x0, x1, y0, y1, minimum):
    """窗口（越界部分按边界收缩）内遮罩均值是否高于 `minimum`。"""
    part = mask[max(0, y0):max(0, y1), max(0, x0):max(0, x1)]
    return bool(part.size) and float(np.mean(part)) > minimum


def slice_bounds(limit, start, end):
    """取正的切片边界；负值会从另一侧回卷，必须截断。"""
    limit = int(limit)
    return max(0, min(int(start), limit)), max(0, min(int(end), limit))


def outlined(mask, y0, y1, x0, x1, minimum=.4):
    """地图格子/点位的外框：窗口内遮罩均值是否高于阈值（默认 .4）。"""
    return lit(mask, x0, x1, y0, y1, minimum)
