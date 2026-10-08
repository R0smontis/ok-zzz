# -*- coding: utf-8 -*-
"""ok-script OCR → 一条龙 OcrMatcher 接口适配器。

一条龙的 screen/cv 体系通过 OcrMatcher 抽象消费 OCR 结果，
本适配器把 ok-script executor 持有的 onnxocr 实例包装成该接口，
避免 vendor 一条龙的 onnxocr 包（ok-script[ocr] 已内置同源实现）。
"""
import threading
from typing import Optional

import cv2
import numpy as np
from cv2.typing import MatLike

from onedragon.base.geometry.rectangle import Rect
from onedragon.base.matcher.match_result import MatchResultList
from onedragon.base.matcher.ocr.ocr_matcher import OcrMatcher
from onedragon.base.matcher.ocr.ocr_match_result import OcrMatchResult
from onedragon.utils import cv2_utils


class OkOcrMatcher(OcrMatcher):
    """把 ok-script 的 ocr_lib(onnxocr) 适配为 OcrMatcher。

    通过 callable 惰性获取底层 lib，避免在 ok-script 完成初始化前创建模型。
    get_lib 返回的对象需支持 ``.ocr(image) -> [ [pos, (text, conf)], ... ]``。
    """

    def __init__(self, get_lib, use_gpu: bool = False):
        """
        Args:
            get_lib: 返回底层 OCR 实例的 callable（如 og.app.executor.ocr_lib 的包装）
            use_gpu: 是否使用 GPU（仅透传给 OcrMatcher 接口语义）
        """
        OcrMatcher.__init__(self)
        self._get_lib = get_lib
        self._use_gpu = use_gpu
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # OcrMatcher 接口
    # ------------------------------------------------------------------ #

    def update_use_gpu(self, use_gpu: bool) -> None:
        self._use_gpu = use_gpu

    def is_use_gpu(self) -> bool:
        return self._use_gpu

    def init_model(self, *args, **kwargs) -> bool:
        """ok-script 侧模型由框架管理，这里只做一次预热调用。"""
        try:
            with self._lock:
                self._get_lib()
            return True
        except Exception:
            return False

    def run_ocr_single_line(self, image: MatLike, threshold: float | None = None,
                            strict_one_line: bool = True) -> str:
        if threshold is None:
            threshold = 0
        results = self.ocr(image, threshold=threshold)
        if len(results) == 0:
            return ''
        # 简单按 y 分行、行内按 x 排序后拼接
        results.sort(key=lambda r: (round(r.y / 20), r.x))
        return ''.join(str(r.data) for r in results)

    def run_ocr(self, image: MatLike, threshold: float | None = None,
                merge_line_distance: float = -1) -> dict[str, MatchResultList]:
        if threshold is None:
            threshold = 0
        ans: dict[str, MatchResultList] = {}
        for result in self.ocr(image, threshold=threshold):
            if result.data not in ans:
                ans[result.data] = MatchResultList()
            ans[result.data].append(result, auto_merge=merge_line_distance != -1)
        return ans

    def ocr(self, image: MatLike, threshold: float = 0,
            merge_line_distance: float = -1) -> list[OcrMatchResult]:
        raw = self._raw_ocr(image)
        results: list[OcrMatchResult] = []
        for pos, (text, conf) in raw:
            if threshold and conf < threshold:
                continue
            xs = [p[0] for p in pos]
            ys = [p[1] for p in pos]
            x, y = int(min(xs)), int(min(ys))
            w, h = int(max(xs)) - x, int(max(ys)) - y
            if w <= 0 or h <= 0:
                continue
            results.append(OcrMatchResult(c=conf, x=x, y=y, w=w, h=h, data=text))
        return results

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #

    def _raw_ocr(self, image: MatLike):
        """调用底层 onnxocr，返回 [(pos, (text, conf)), ...]。"""
        if image is None:
            return []
        if isinstance(image, np.ndarray) and image.size == 0:
            return []
        with self._lock:
            lib = self._get_lib()
            # 一条龙图像是 RGB；ok-script 的 OCR 接口消费 OpenCV BGR。
            converted = cv2.cvtColor(image, cv2.COLOR_RGB2BGR) if image.ndim == 3 else image
            result = lib.ocr(converted)
        if result is None or len(result) == 0 or result[0] is None:
            return []
        return [(item[0], item[1]) for item in result[0]]

    def crop_and_run_ocr(self, image: MatLike, rect: Rect, threshold: float = 0,
                         merge_line_distance: float = -1) -> dict[str, MatchResultList]:
        part = cv2_utils.crop_image_only(image, rect)
        return self.run_ocr(part, threshold, merge_line_distance)
