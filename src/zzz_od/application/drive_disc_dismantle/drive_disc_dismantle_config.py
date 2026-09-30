# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/application/drive_disc_dismantle/drive_disc_dismantle_config.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from enum import Enum
from typing import Optional

from onedragon.base.config.config_item import ConfigItem
from onedragon.base.config.yaml_config import YamlConfig
from onedragon.base.operation.application.application_config import ApplicationConfig


class DismantleLevelEnum(Enum):

    LEVEL_B = ConfigItem('B')
    LEVEL_A = ConfigItem('A及以下')
    LEVEL_S = ConfigItem('S及以下')


class DriveDiscDismantleConfig(ApplicationConfig):

    def __init__(self, instance_idx: int, group_id: str):
        ApplicationConfig.__init__(
            self,
            app_id='drive_disc_dismantle',
            instance_idx=instance_idx,
            group_id=group_id,
        )

    @property
    def dismantle_level(self) -> str:
        return self.get('dismantle_level', DismantleLevelEnum.LEVEL_A.value.value)

    @dismantle_level.setter
    def dismantle_level(self, new_value: str) -> None:
        self.update('dismantle_level', new_value)

    @property
    def dismantle_abandon(self) -> bool:
        """
        全选已弃置
        :return:
        """
        return self.get('dismantle_abandon', False)

    @dismantle_abandon.setter
    def dismantle_abandon(self, new_value: bool) -> None:
        self.update('dismantle_abandon', new_value)