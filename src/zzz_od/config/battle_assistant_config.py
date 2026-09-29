# -*- coding: utf-8 -*-
"""战斗助手配置 — 精简移植版。

移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
src/zzz_od/application/battle_assistant/battle_assistant_config.py。
"""
from onedragon.base.config.lean_yaml_config import LeanYamlConfig


class BattleAssistantConfig(LeanYamlConfig):

    def __init__(self, dir_path: str | None = None):
        LeanYamlConfig.__init__(self, 'battle_assistant', dir_path=dir_path)

    @property
    def screenshot_interval(self) -> float:
        return self.get('screenshot_interval', 0.02)

    @screenshot_interval.setter
    def screenshot_interval(self, new_value: float) -> None:
        self.update('screenshot_interval', new_value)

    @property
    def background_mode(self) -> bool:
        return self.get('background_mode', False)

    @background_mode.setter
    def background_mode(self, new_value: bool) -> None:
        self.update('background_mode', new_value)

    @property
    def auto_battle_config(self) -> str:
        return self.get('auto_battle_config', '全配队通用')

    @auto_battle_config.setter
    def auto_battle_config(self, new_value: str) -> None:
        self.update('auto_battle_config', new_value)

    @property
    def use_merged_file(self) -> bool:
        """使用合并后的单文件"""
        return self.get('use_merged_file', True)

    @use_merged_file.setter
    def use_merged_file(self, new_value: bool) -> None:
        self.update('use_merged_file', new_value)

    @property
    def auto_ultimate_enabled(self) -> bool:
        """自动释放终结技开关"""
        return self.get('auto_ultimate_enabled', False)

    @auto_ultimate_enabled.setter
    def auto_ultimate_enabled(self, new_value: bool) -> None:
        self.update('auto_ultimate_enabled', new_value)
