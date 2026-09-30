# -*- coding: utf-8 -*-
"""一条龙应用工厂（ok-zzz 自写）。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from onedragon.base.operation.application.application_factory import ApplicationFactory
from zzz_od.application.one_dragon_app import one_dragon_app_const
from zzz_od.application.one_dragon_app.zzz_one_dragon_app import ZOneDragonApp

if TYPE_CHECKING:
    from zzz_od.context.zzz_context import ZContext


class ZOneDragonAppFactory(ApplicationFactory):

    def __init__(self, ctx: ZContext):
        ApplicationFactory.__init__(self, one_dragon_app_const)
        self.ctx: ZContext = ctx

    def create_application(self, instance_idx: int, group_id: str):
        return ZOneDragonApp(self.ctx)
