# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/application/battle_assistant/auto_battle/auto_battle_app_factory.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from __future__ import annotations

from typing import TYPE_CHECKING

from onedragon.base.operation.application.application_factory import ApplicationFactory
from onedragon.base.operation.application_base import Application
from zzz_od.application.battle_assistant.auto_battle import auto_battle_const
from zzz_od.application.battle_assistant.auto_battle.auto_battle_app import (
    AutoBattleApp,
)

if TYPE_CHECKING:
    from zzz_od.context.zzz_context import ZContext


class AutoBattleAppFactory(ApplicationFactory):

    def __init__(self, ctx: ZContext):
        ApplicationFactory.__init__(self, auto_battle_const)
        self.ctx: ZContext = ctx

    def create_application(self, instance_idx: int, group_id: str) -> Application:
        return AutoBattleApp(self.ctx)
