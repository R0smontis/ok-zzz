# -*- coding: utf-8 -*-
"""精简 YAML 配置基类（ok-zzz 特有，非移植）。

一条龙的 YamlConfig 承载了实例目录/Qt 适配器/枚举提示等能力；
ok-zzz 只需要"按名读写 YAML 并落盘"这一个子集，API 保持一致
（get / update），游戏配置键名与一条龙完全兼容。
"""
import os
from typing import Any

import yaml

from onedragon.utils import os_utils
from onedragon.utils.log_utils import log


class LeanYamlConfig:

    def __init__(self, module_name: str, dir_path: str | None = None):
        """
        Args:
            module_name: 配置文件名（不含扩展名）
            dir_path: 配置目录，默认 <工作目录>/config
        """
        if dir_path is None:
            dir_path = os_utils.get_path_under_work_dir('config')
        os.makedirs(dir_path, exist_ok=True)
        self.config_file_path: str = os.path.join(dir_path, f'{module_name}.yml')
        self.data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.config_file_path):
            try:
                with open(self.config_file_path, 'r', encoding='utf-8') as fp:
                    loaded = yaml.safe_load(fp)
                self.data = loaded if isinstance(loaded, dict) else {}
            except Exception as e:
                log.error(f'读取配置失败 {self.config_file_path}', exc_info=e)
                self.data = {}
        else:
            self.data = {}

    def get(self, prop: str, value=None):
        return self.data.get(prop, value)

    def update(self, key: str, value, save: bool = True) -> None:
        self.data[key] = value
        if save:
            self._save()

    def _save(self) -> None:
        try:
            with open(self.config_file_path, 'w', encoding='utf-8') as fp:
                yaml.dump(self.data, fp, allow_unicode=True, sort_keys=False)
        except Exception as e:
            log.error(f'保存配置失败 {self.config_file_path}', exc_info=e)
