# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/auto_battle/atomic_op/btn_chain_left.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from onedragon.base.conditional_operation.atomic_op import AtomicOp
from zzz_od.auto_battle.auto_battle_state import BattleStateEnum

if TYPE_CHECKING:
    from zzz_od.auto_battle.auto_battle_context import AutoBattleContext


class AtomicBtnChainLeft(AtomicOp):

    def __init__(self, ctx: AutoBattleContext, press: bool = False, press_time: Optional[float] = None, release: bool = False):
        if press:
            op_name = BattleStateEnum.BTN_CHAIN_LEFT.value + '按下'
        elif release:
            op_name = BattleStateEnum.BTN_CHAIN_LEFT.value + '松开'
        else:
            op_name = BattleStateEnum.BTN_CHAIN_LEFT.value
        AtomicOp.__init__(self, op_name=op_name, async_op=press and press_time is None)
        self.ctx: AutoBattleContext = ctx
        self.press: bool = press
        self.press_time: Optional[float] = press_time
        self.release: bool = release

    def execute(self):
        self.ctx.chain_left(self.press, self.press_time, self.release)

    def stop(self) -> None:
        if self.press:
            self.ctx.chain_left(release=True)
