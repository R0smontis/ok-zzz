# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: one_dragon/base/cv_process/steps/step_erode.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
# coding: utf-8
from typing import Dict, Any
import cv2
import numpy as np
from onedragon.base.cv_process.cv_step import CvStep, CvPipelineContext


class CvErodeStep(CvStep):

    def __init__(self):
        super().__init__('腐蚀')

    def get_params(self) -> Dict[str, Any]:
        return {
            'kernel_size': {'type': 'int', 'default': 3, 'range': (1, 21), 'label': '腐蚀核大小', 'tooltip': '腐蚀操作的核大小，奇数。值越大，腐蚀效果（消除噪点）越强。'},
            'iterations': {'type': 'int', 'default': 1, 'range': (1, 10), 'label': '迭代次数', 'tooltip': '腐蚀操作的执行次数。'},
        }

    def get_description(self) -> str:
        return "腐蚀操作可以去除小的噪点。 `kernel_size` 是腐蚀核的大小，越大腐蚀效果越强。`iterations` 是迭代次数。"

    def _execute(self, context: CvPipelineContext, kernel_size: int = 3, iterations: int = 1, **kwargs):
        if context.mask_image is None:
            return
        kernel = np.ones((kernel_size, kernel_size), np.uint8)
        eroded_mask = cv2.erode(context.mask_image, kernel, iterations=iterations)
        context.mask_image = eroded_mask
        context.display_image = cv2.bitwise_and(context.display_image, context.display_image, mask=eroded_mask)