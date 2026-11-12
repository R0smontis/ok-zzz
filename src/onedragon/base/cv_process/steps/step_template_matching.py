# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: one_dragon/base/cv_process/steps/step_template_matching.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
# coding: utf-8
from typing import Dict, Any
import cv2
from onedragon.base.cv_process.cv_step import CvStep, CvPipelineContext


class CvTemplateMatchingStep(CvStep):

    def __init__(self):
        self.method_map = {
            'TM_CCOEFF_NORMED': cv2.TM_CCOEFF_NORMED,
            'TM_CCORR_NORMED': cv2.TM_CCORR_NORMED,
            'TM_SQDIFF_NORMED': cv2.TM_SQDIFF_NORMED,
        }
        super().__init__('模板匹配')

    def get_params(self) -> Dict[str, Any]:
        return {
            'template_name': {'type': 'enum_template_image', 'default': '', 'label': '模板图像名称', 'tooltip': '用于在原图中滑窗搜索的模板小图。'},
            'threshold': {'type': 'float', 'default': 0.8, 'range': (0.0, 1.0), 'label': '匹配置信度', 'tooltip': '匹配结果的置信度阈值。只有高于此值的匹配才会被接受。'},
            'method': {'type': 'enum', 'default': 'TM_CCOEFF_NORMED', 'options': list(self.method_map.keys()), 'label': '匹配算法', 'tooltip': '选择模板匹配的计算方法。'},
        }

    def get_description(self) -> str:
        return "在当前图像上寻找与模板图像最匹配的区域。这个步骤不依赖之前的二值化或轮廓步骤。"

    def _execute(self, context: CvPipelineContext, template_name: str = '', threshold: float = 0.8, method: str = 'TM_CCOEFF_NORMED', **kwargs):
        raise NotImplementedError("ok-zzz 未移植图像分析 GUI 逻辑")