# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/application/trigrams_collection/trigrams_collection_factory.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from __future__ import annotations

from typing import TYPE_CHECKING

from onedragon.base.operation.application.application_factory import ApplicationFactory
from onedragon.base.operation.application_base import Application
from onedragon.base.operation.application_run_record import AppRunRecord
from zzz_od.application.trigrams_collection import trigrams_collection_const
from zzz_od.application.trigrams_collection.trigrams_collection_app import (
    TrigramsCollectionApp,
)
from zzz_od.application.trigrams_collection.trigrams_collection_record import (
    TrigramsCollectionRunRecord,
)

if TYPE_CHECKING:
    from zzz_od.context.zzz_context import ZContext


class TrigramsCollectionFactory(ApplicationFactory):

    def __init__(self, ctx: ZContext):
        ApplicationFactory.__init__(self, trigrams_collection_const)
        self.ctx: ZContext = ctx

    def create_application(self, instance_idx: int, group_id: str) -> Application:
        return TrigramsCollectionApp(self.ctx)

    def create_run_record(self, instance_idx: int) -> AppRunRecord:
        return TrigramsCollectionRunRecord(
            instance_idx=instance_idx,
            game_refresh_hour_offset=self.ctx.game_account_config.game_refresh_hour_offset,
        )
