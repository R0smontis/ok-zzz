# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: one_dragon/base/conditional_operation/atomic_op.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
class AtomicOp:

    def __init__(self, op_name: str, async_op: bool = False):
        """
        一个原子指令，没有任何判断，执行后上抛事件
        :param op_name: 指令名称
        :param async_op: 是否一个异步操作。
        """
        self.op_name: str = op_name
        self.async_op: bool = async_op

    def execute(self):
        """
        执行指令 必要时上抛状态事件
        """
        pass

    def dispose(self) -> None:
        """
        销毁时 解除事件监听
        :return:
        """
        pass

    def stop(self) -> None:
        """
        停止运行
        """
        pass
