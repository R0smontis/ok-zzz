# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/application/daily_signin/daily_signin_run_record.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。

from onedragon.base.operation.application_run_record import AppRunRecord


class DailySignInRunRecord(AppRunRecord):

    def __init__(self, instance_idx: int | None = None, game_refresh_hour_offset: int = 0):
        AppRunRecord.__init__(
            self,
            'daily_signin',
            instance_idx=instance_idx,
            game_refresh_hour_offset=game_refresh_hour_offset
        )
