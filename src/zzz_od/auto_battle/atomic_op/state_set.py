# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/auto_battle/atomic_op/state_set.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from onedragon.base.conditional_operation.atomic_op import AtomicOp
from onedragon.base.conditional_operation.operation_def import OperationDef

if TYPE_CHECKING:
    from zzz_od.auto_battle.auto_battle_custom_context import AutoBattleCustomContext


class AtomicSetState(AtomicOp):

    OP_NAME: ClassVar[str] = '设置状态'

    def __init__(self, ctx: AutoBattleCustomContext, op_def: OperationDef):
        self.ctx: AutoBattleCustomContext = ctx
        self.state_name: str = op_def.state_name
        self.state_name_list: list[str] = op_def.state_name_list
        self.diff_time: float = op_def.state_seconds
        self.diff_time_add: float = op_def.state_seconds_add
        self.value: int = op_def.state_value
        self.value_add: int = op_def.state_value_add

        if op_def.data is not None:
            if len(op_def.data) > 0:
                self.state_name = op_def.data[0]
            if len(op_def.data) > 1:
                self.diff_time = float(op_def.data[1])
            if len(op_def.data) > 2:
                self.value = int(op_def.data[2])

        AtomicOp.__init__(self, op_name='%s %s' % (AtomicSetState.OP_NAME,self.state_name))

    def execute(self):
        if self.state_name_list is not None:
            self.ctx.set_state(self.state_name_list, self.diff_time, self.diff_time_add , self.value, self.value_add)
        else:
            self.ctx.set_state([self.state_name], self.diff_time, self.diff_time_add , self.value, self.value_add)
