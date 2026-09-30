# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/application/daily_signin/daily_signin_config.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from onedragon.base.operation.application.application_config import ApplicationConfig


class DailySignInConfig(ApplicationConfig):

    def __init__(self, instance_idx: int, group_id: str):
        ApplicationConfig.__init__(self, 'daily_signin', instance_idx, group_id)

    @property
    def selected_sign(self) -> str:
        """选择签到的商店，默认为 hou_hou_bakery"""
        return self.get('selected_sign', 'hou_hou_bakery')

    @selected_sign.setter
    def selected_sign(self, value: str) -> None:
        self.update('selected_sign', value)
