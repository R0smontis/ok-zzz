# -*- coding: utf-8 -*-
"""OCR 模型信息 compat（自 onnx_ocr_matcher 拆出的下载元数据）。

ok-zzz 的 OCR 运行时由 ok-script[ocr] 提供（OkOcrMatcher 适配），
此处仅保留模型名/目录/下载地址等元数据，供模型管理与下载使用。
"""
import os

from onedragon.utils import os_utils

DEFAULT_OCR_MODEL_NAME: str = 'ppocrv5'
PPOCRV6_MODEL_NAME: str = 'ppocrv6'

OCR_DOWNLOAD_URLS: dict[str, str] = {
    'github': 'https://github.com/OneDragon-Anything/OneDragon-Env/releases/download',
    'cnb': 'https://cnb.cool/OneDragon-Anything/OneDragon-Env/-/releases/download',
    'gitee': 'https://gitee.com/OneDragon-Anything/OneDragon-Env/releases/download',
}


def get_ocr_model_dir(ocr_model_name: str) -> str:
    return os_utils.get_path_under_work_dir('assets', 'models', 'onnx_ocr', ocr_model_name)


def get_ocr_download_urls(ocr_model_name: str) -> dict[str, str]:
    """获取OCR模型各源的下载地址。"""
    return {
        source_id: f'{website}/{ocr_model_name}/{ocr_model_name}.zip'
        for source_id, website in OCR_DOWNLOAD_URLS.items()
    }


def get_ocr_model_dict_name(ocr_model_name: str) -> str | None:
    """获取模型对应的字典文件名。直接扫描本地文件夹中的字典文件。"""
    base_dir = get_ocr_model_dir(ocr_model_name)
    if os.path.exists(base_dir):
        for f in os.listdir(base_dir):
            if f.endswith('_dict.txt'):
                return f
    return None


def get_final_file_list(ocr_model_name: str) -> list[str]:
    """下载成功后 整个模型的所有文件。"""
    base_dir = get_ocr_model_dir(ocr_model_name)
    files = [
        os.path.join(base_dir, 'det.onnx'),
        os.path.join(base_dir, 'rec.onnx'),
        os.path.join(base_dir, 'cls.onnx'),
        os.path.join(base_dir, 'simfang.ttf'),
    ]
    dict_name = get_ocr_model_dict_name(ocr_model_name)
    if dict_name is not None:
        files.append(os.path.join(base_dir, dict_name))
    return files
