# -*- coding: utf-8 -*-
"""下载识别模型（YOLO 闪避分类器等）与 OCR 模型。

YOLO 模型来自 OneDragon-YOLO release（zzz_model tag），
onnx_model_loader 约定: {base_url}/{model_name}.zip → 解压出 model.onnx + labels.csv
用法:
    python tools/download_models.py                 # 按 config/model.yml 下载闪光分类器
    python tools/download_models.py --all           # 全部模型（闪光/空洞/迷失之地）
"""
import argparse
import os
import sys
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from onedragon.utils.log_utils import log  # noqa: E402
from zzz_od.config.model_config import MODEL_DOWNLOAD_SOURCES  # noqa: E402

MODELS = {
    'flash_classifier': ('yolov8n-640-flash-20250921', 'yolov8n-640-flash-20250906'),
    'hollow_zero_event': ('yolov8s-736-hollow-zero-event-0126', 'yolov8s-736-hollow-zero-event-1130'),
    'lost_void_det': ('yolov26n-736-lost-void-det-20260630', 'yolov8n-736-lost-void-det-20250921'),
}


def model_dir(category: str) -> str:
    return os.path.join('assets', 'models', category)


def is_model_ready(path: str) -> bool:
    return (os.path.exists(os.path.join(path, 'model.onnx'))
            and os.path.exists(os.path.join(path, 'labels.csv')))


def download(category: str, model_name: str, source: str = 'github') -> bool:
    import urllib.request
    target_dir = os.path.join(model_dir(category), model_name)
    if is_model_ready(target_dir):
        log.info(f'[跳过] {category}/{model_name} 已就绪')
        return True
    url = f"{MODEL_DOWNLOAD_SOURCES.get(source, '')}/{model_name}.zip"
    if not url.startswith('http'):
        log.error(f'未知下载源: {source}')
        return False
    os.makedirs(target_dir, exist_ok=True)
    zip_path = os.path.join(target_dir, f'{model_name}.zip')
    log.info(f'下载 {url}')
    try:
        with urllib.request.urlopen(url, timeout=120) as resp, open(zip_path, 'wb') as fp:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                fp.write(chunk)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(target_dir)
        os.remove(zip_path)
        if not is_model_ready(target_dir):
            log.warning(f'{category}/{model_name} 解压后缺少 model.onnx/labels.csv，请检查包内容')
            return False
        log.info(f'[完成] {category}/{model_name}')
        return True
    except Exception as e:
        log.error(f'下载失败 {url}: {e}')
        return False
    finally:
        if os.path.exists(zip_path):
            os.remove(zip_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--all', action='store_true', help='下载全部模型')
    parser.add_argument('--source', default='github', choices=list(MODEL_DOWNLOAD_SOURCES))
    args = parser.parse_args()

    names = MODELS if args.all else {'flash_classifier': MODELS['flash_classifier']}
    ok = True
    for category, (default_name, backup_name) in names.items():
        if not download(category, default_name, args.source):
            if not download(category, backup_name, args.source):
                ok = False
    if not ok:
        sys.exit(1)


if __name__ == '__main__':
    main()
