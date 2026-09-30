# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/application/life_on_line/life_on_line_config.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。

from onedragon.base.operation.application.application_config import ApplicationConfig
from onedragon.base.config.yaml_config_adapter import YamlConfigAdapter


class LifeOnLineConfig(ApplicationConfig):

    def __init__(self, instance_idx: int, group_id: str):
        ApplicationConfig.__init__(
            self,
            app_id='life_on_line',
            instance_idx=instance_idx,
            group_id=group_id,
        )

    @property
    def daily_plan_times(self) -> int:
        return self.get('daily_plan_times', 20)

    @daily_plan_times.setter
    def daily_plan_times(self, new_value: int) -> None:
        self.update('daily_plan_times', new_value)

    @property
    def predefined_team_idx(self) -> int:
        """
        预备编队
        -1 = 游戏内配队
        :return:
        """
        return self.get('predefined_team_idx', -1)

    @predefined_team_idx.setter
    def predefined_team_idx(self, new_value: int) -> None:
        self.update('predefined_team_idx', new_value)
