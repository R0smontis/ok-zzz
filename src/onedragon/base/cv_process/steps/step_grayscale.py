# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: one_dragon/base/cv_process/steps/step_grayscale.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
# coding: utf-8
import cv2
from onedragon.base.cv_process.cv_step import CvStep, CvPipelineContext


class CvStepGrayscale(CvStep):

    def __init__(self):
        super().__init__('灰度化')

    def get_description(self) -> str:
        return "将彩色图像转换为灰度图像，消除颜色信息，是后续处理步骤（如二值化）的前提。"

    def _execute(self, context: CvPipelineContext, **kwargs):
        if len(context.display_image.shape) == 3:  # 检查是否为彩色图
            gray_image = cv2.cvtColor(context.display_image, cv2.COLOR_RGB2GRAY)
            # 更新主显示图像为灰度图，但保持3通道以便于后续绘制彩色调试信息
            context.display_image = cv2.cvtColor(gray_image, cv2.COLOR_GRAY2RGB)
            context.mask_image = gray_image  # 将单通道灰度图存入mask，供下一步使用
            context.analysis_results.append("图像已转换为灰度")
        else:
            context.analysis_results.append("图像已经是灰度图，跳过灰度化")