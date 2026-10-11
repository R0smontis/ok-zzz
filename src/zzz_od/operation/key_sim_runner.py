# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/operation/key_sim_runner.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from onedragon.base.conditional_operation.atomic_op import AtomicOp
from onedragon.base.conditional_operation.operation_def import OperationDef
from onedragon.base.config.yaml_config import YamlConfig
from onedragon.base.operation.operation_edge import node_from
from onedragon.base.operation.operation_node import operation_node
from onedragon.base.operation.operation_round_result import OperationRoundResult
from onedragon.utils.i18_utils import gt
from zzz_od.context.zzz_context import ZContext
from zzz_od.operation.zzz_operation import ZOperation


class KeySimRunner(ZOperation):

    def __init__(self, ctx: ZContext, config_name: str):
        ZOperation.__init__(self, ctx,
                            op_name='%s %s' % (
                                gt('模拟按键'),
                                config_name
                            ))
        self.config_name: str = config_name
        self.ops: list[AtomicOp] = []

    @operation_node(name='加载配置', is_start_node=True)
    def load_config(self) -> OperationRoundResult:
        config = YamlConfig(self.config_name, sub_dir=['key_sim'], sample=True, copy_from_sample=False)
        self.ops = []
        rows = config.data.get('operations') if isinstance(config.data, dict) else None
        if not isinstance(rows, list) or not rows:
            return self.round_fail(f'模拟按键配置缺失或为空：{self.config_name}')
        if any(not isinstance(row, dict) or not isinstance(row.get('op_name'), str)
               or not row['op_name'].strip() for row in rows):
            return self.round_fail(f'模拟按键配置格式错误：{self.config_name}')
        try:
            ops = [self.ctx.auto_battle_context.atomic_op_factory.get_atomic_op(OperationDef(row)) for row in rows]
        except (ValueError, TypeError) as error:
            return self.round_fail(f'模拟按键配置无效：{self.config_name}；{error}')
        self.ops = ops
        return self.round_success()

    @node_from(from_name='加载配置')
    @operation_node(name='执行按键')
    def run_key_sim(self) -> OperationRoundResult:
        for op in self.ops:
            op.execute()

        return self.round_success()
