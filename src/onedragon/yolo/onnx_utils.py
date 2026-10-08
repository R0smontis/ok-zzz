# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: one_dragon/yolo/onnx_utils.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from typing import Tuple

import cv2
import numpy as np
from cv2.typing import MatLike


def scale_input_image_u(image: MatLike, onnx_input_width: int, onnx_input_height: int) -> Tuple[np.ndarray, int, int]:
    """
    按照 ultralytics 的方式，将图片缩放至模型使用的大小
    参考 https://github.com/orgs/ultralytics/discussions/6994?sort=new#discussioncomment-8382661
    :param image: 输入的图片 RBG通道
    :param onnx_input_width: 模型需要的图片宽度
    :param onnx_input_height: 模型需要的图片高度
    :return: 缩放后的图片 RGB通道
    """
    img_height, img_width = image.shape[:2]

    # 将图像缩放到模型的输入尺寸中较短的一边
    min_scale = min(onnx_input_height / img_height, onnx_input_width / img_width)

    # 未进行padding之前的尺寸
    scale_height = int(round(img_height * min_scale))
    scale_width = int(round(img_width * min_scale))

    # 缩放到目标尺寸
    if onnx_input_height != img_height or onnx_input_width != img_width:  # 需要缩放
        input_img = np.full(shape=(onnx_input_height, onnx_input_width, 3),
                            fill_value=114, dtype=np.uint8)
        scale_img = cv2.resize(image, (scale_width, scale_height), interpolation=cv2.INTER_LINEAR)
        input_img[0:scale_height, 0:scale_width, :] = scale_img
    else:
        input_img = image

    # 直接在 float32 上完成 HWC->CHW 与归一化，避免 float64 中间数组；结果与 /255.0 后转 float32 逐位一致
    input_tensor = np.empty((1, 3, input_img.shape[0], input_img.shape[1]), dtype=np.float32)
    input_tensor[0] = input_img.transpose(2, 0, 1)
    input_tensor /= np.float32(255)

    return input_tensor, scale_height, scale_width
