# -*- coding: utf-8 -*-
"""模型配置 — 精简移植版。

移植自 ZenlessZoneZero-OneDragon (GPL-3.0) src/zzz_od/config/model_config.py，
模型下载源直接内联 OneDragon-YOLO release 地址（原仓库经 repo_config 间接获取）。
"""
from enum import Enum

from onedragon.base.config.lean_yaml_config import LeanYamlConfig
from onedragon.base.config.config_item import ConfigItem

_DEFAULT_FLASH_CLASSIFIER = 'yolov8n-640-flash-20250921'
_BACKUP_FLASH_CLASSIFIER = 'yolov8n-640-flash-20250906'

_DEFAULT_HOLLOW_ZERO_EVENT = 'yolov8s-736-hollow-zero-event-0126'
_BACKUP_HOLLOW_ZERO_EVENT = 'yolov8s-736-hollow-zero-event-1130'

_DEFAULT_LOST_VOID_DET = 'yolov26n-736-lost-void-det-20260630'
_BACKUP_LOST_VOID_DET = 'yolov8n-736-lost-void-det-20250921'

# 模型下载源（与一条龙 config/repository.yml 中 env_source/yolo repo 配置一致）
MODEL_DOWNLOAD_SOURCES: dict[str, str] = {
    'github': 'https://github.com/OneDragon-Anything/OneDragon-YOLO/releases/download/zzz_model',
    'cnb': 'https://cnb.cool/OneDragon-Anything/OneDragon-YOLO/-/releases/download/zzz_model',
    'gitee': 'https://gitee.com/OneDragon-Anything/OneDragon-YOLO/releases/download/zzz_model',
}


class ModelSourceEnum(Enum):
    GITHUB = ConfigItem('GitHub', 'github')
    CNB = ConfigItem('CNB', 'cnb')
    GITEE = ConfigItem('Gitee', 'gitee')


class ModelConfig(LeanYamlConfig):

    def __init__(self, dir_path: str | None = None):
        LeanYamlConfig.__init__(self, 'model', dir_path=dir_path)

    @property
    def flash_classifier(self) -> str:
        return self.get('flash_classifier', _DEFAULT_FLASH_CLASSIFIER)

    @flash_classifier.setter
    def flash_classifier(self, new_value: str) -> None:
        self.update('flash_classifier', new_value)

    @property
    def flash_classifier_backup(self) -> str:
        return self.get('flash_classifier_backup', _BACKUP_FLASH_CLASSIFIER)

    @property
    def flash_classifier_gpu(self) -> bool:
        return self.get('flash_classifier_gpu', True)

    @flash_classifier_gpu.setter
    def flash_classifier_gpu(self, new_value: bool) -> None:
        self.update('flash_classifier_gpu', new_value)

    @property
    def ocr_use_gpu(self) -> bool:
        return self.get('ocr_use_gpu', True)

    @ocr_use_gpu.setter
    def ocr_use_gpu(self, new_value: bool) -> None:
        self.update('ocr_use_gpu', new_value)

    @property
    def hollow_zero_event(self) -> str:
        return self.get('hollow_zero_event', _DEFAULT_HOLLOW_ZERO_EVENT)

    @hollow_zero_event.setter
    def hollow_zero_event(self, new_value: str) -> None:
        self.update('hollow_zero_event', new_value)

    @property
    def hollow_zero_event_backup(self) -> str:
        return self.get('hollow_zero_event_backup', _BACKUP_HOLLOW_ZERO_EVENT)

    @property
    def hollow_zero_event_gpu(self) -> bool:
        return self.get('hollow_zero_event_gpu', True)

    @property
    def lost_void_det(self) -> str:
        return self.get('lost_void_det', _DEFAULT_LOST_VOID_DET)

    @lost_void_det.setter
    def lost_void_det(self, new_value: str) -> None:
        self.update('lost_void_det', new_value)

    @property
    def lost_void_det_backup(self) -> str:
        return self.get('lost_void_det_backup', _BACKUP_LOST_VOID_DET)

    @property
    def lost_void_det_gpu(self) -> bool:
        return self.get('lost_void_det_gpu', True)

    @property
    def model_download_source(self) -> str:
        return self.get('model_download_source', 'github')

    @model_download_source.setter
    def model_download_source(self, new_value: str) -> None:
        self.update('model_download_source', new_value)

    def get_model_download_base_url(self, config_key: str, source_id: str = 'github') -> str:
        """获取模型 release 下载根地址（onnx_model_loader 会再拼 /<模型名>.zip）。"""
        if source_id not in MODEL_DOWNLOAD_SOURCES:
            source_id = self.model_download_source
        return MODEL_DOWNLOAD_SOURCES.get(source_id, '')
