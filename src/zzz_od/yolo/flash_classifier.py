# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/yolo/flash_classifier.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from onedragon.utils import yolo_config_utils
from onedragon.yolo.yolov8_onnx_cls import Yolov8Classifier


class FlashClassifier(Yolov8Classifier):
    required_model_files = ('model.onnx', 'labels.csv')

    def __init__(
            self,
            model_download_url: str,
            model_name: str = 'yolov8n-640-flash-20250906',
            backup_model_name: str = 'yolov8n-640-flash-20250622',
            model_parent_dir_path: str = yolo_config_utils.get_model_category_dir('flash_classifier'),
            gh_proxy: bool = True,
            gh_proxy_url: str | None = None,
            personal_proxy: str | None = None,
            gpu: bool = False,
            keep_result_seconds: float = 2
    ):
        """
        :param model_name: 模型名称 在根目录下会有一个以模型名称创建的子文件夹
        :param model_parent_dir_path: 放置所有模型的根目录
        :param gpu: 是否启用GPU加速
        :param keep_result_seconds: 保留多长时间的识别结果
        """
        Yolov8Classifier.__init__(
            self,
            model_name=model_name,
            backup_model_name=backup_model_name,
            model_parent_dir_path=model_parent_dir_path,
            model_download_url=model_download_url,
            gh_proxy=gh_proxy,
            gh_proxy_url=gh_proxy_url,
            personal_proxy=personal_proxy,
            gpu=gpu,
            keep_result_seconds=keep_result_seconds
        )


def __debug():
    from onedragon.utils import os_utils
    from zzz_od.context.zzz_context import ZContext

    ctx = ZContext()
    flash_classifier = FlashClassifier(
        model_download_url=ctx.model_config.get_model_download_base_url(
            'flash_classifier',
        ),
        model_parent_dir_path=os_utils.get_path_under_work_dir('assets', 'models', 'flash_classifier')
    )
    from onedragon.utils import debug_utils
    result = flash_classifier.run(debug_utils.get_debug_image('_1750517690304'))
    print(result.class_idx)


if __name__ == '__main__':
    __debug()
