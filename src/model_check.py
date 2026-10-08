"""Offline inference checks for bundled resident-assistant models."""
import time
from pathlib import Path


def check_realtime_models(root):
    import cv2
    import numpy as np
    from onedragon.envs.repo_config import RepoConfig
    from zzz_od.yolo.flash_classifier import FlashClassifier
    from src.gpu_ocr import install_gpu_ocr
    from ok.task.TaskExecutor import TaskExecutor
    from src.inference import directml_adapter
    from onedragon.base.matcher.ocr.ok_ocr_matcher import OkOcrMatcher

    resource = RepoConfig().get_model_resource('flash_classifier')
    parent = Path(root) / 'assets/models/flash_classifier'
    for name in resource.required_files:
        path = parent / resource.default_model / name
        assert path.is_file() and path.stat().st_size > 0, f'缺少闪避识别资源：{path}'
    # Required files are checked before construction; never download in this check.
    classifier = FlashClassifier(model_download_url='', model_name=resource.default_model,
                                 model_parent_dir_path=str(parent), backup_model_name=None,
                                 gh_proxy=False, gpu=True)
    blank = np.zeros((1080, 1920, 3), np.uint8)
    timings = []
    for _ in range(3):
        started = time.perf_counter()
        result = classifier.run(blank)
        timings.append((time.perf_counter() - started) * 1000)
        assert result.class_idx not in (1, 2), '空白帧不应触发红光或黄光'
    assert classifier.last_run_result is result

    install_gpu_ocr()
    ocr_executor = TaskExecutor.__new__(TaskExecutor)
    ocr_executor.config = {'ocr': {'default': {'lib': 'onnxocr', 'params': {}}}}
    ocr = ocr_executor._create_ocr_lib('default')
    text_frame = np.full((160, 640, 3), 255, np.uint8)
    cv2.putText(text_frame, 'SKIP', (35, 110), cv2.FONT_HERSHEY_SIMPLEX,
                2.5, (0, 0, 0), 5, cv2.LINE_AA)
    ocr_timings = []
    for _ in range(3):
        started = time.perf_counter()
        texts = [match.data for match in OkOcrMatcher(lambda: ocr).ocr(text_frame)]
        ocr_timings.append((time.perf_counter()-started)*1000)
    assert any('SKIP' in text.upper() for text in texts), f'OCR 推理未识别测试文字：{texts}'
    from zzz_od.application.hollow_zero.lost_void.bounty_progress import read_progress
    progress_checks = []
    for current, target in ((2500, 2500), (1250, 2500), (8000, 8000)):
        progress_frame = np.full((100, 480, 3), 30, np.uint8)
        cv2.putText(progress_frame, f'{current}/{target}', (20, 68), cv2.FONT_HERSHEY_SIMPLEX,
                    1.5, (245, 245, 245), 2, cv2.LINE_AA)
        detected = OkOcrMatcher(lambda: ocr).ocr(progress_frame)
        assert read_progress(detected) == (current, target), f'悬赏进度 OCR 未通过：{[item.data for item in detected]}'
        progress_checks.append([current, target])
    return {'flash_model': classifier.model_name,
            'flash_providers': classifier.session.get_providers(),
            'flash_ms': [round(value, 1) for value in timings],
            'gpu_adapter': directml_adapter(),
            'ocr_providers': {'detector': ocr.text_detector.session.get_providers(),
                              'recognizer': ocr.text_recognizer.session.get_providers()},
            'ocr_ms': [round(value, 1) for value in ocr_timings],
            'ocr_test_text': texts,
            'bounty_progress_ocr': progress_checks,
            'optional_models_missing': [model.config_key for model in RepoConfig().model_resources
                                       if model.config_key != 'flash_classifier'
                                       and not all((Path(root) / 'assets/models' / model.config_key
                                                    / model.default_model / name).is_file()
                                                   for name in model.required_files)]}
