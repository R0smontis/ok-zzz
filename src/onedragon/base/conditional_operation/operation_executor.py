# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: one_dragon/base/conditional_operation/operation_executor.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from threading import Lock

from onedragon.base.conditional_operation.atomic_op import AtomicOp
from onedragon.base.controller.input_guard import execution_input_guard
from onedragon.utils import thread_utils
from onedragon.utils.log_utils import log

# 当前执行1个 新的打断1个 即理论最多2个同时运行
_od_op_task_executor = ThreadPoolExecutor(thread_name_prefix='_od_op_task_executor', max_workers=4)


class OperationExecutor:

    def __init__(
        self,
        op_list: list[AtomicOp],
        trigger_time: float,
        input_guard=None,
    ):
        """
        指令执行器 用于管理如何执行/终止一串指令
        """
        self.op_list: list[AtomicOp] = op_list
        self.trigger_time: float = trigger_time  # 触发时间
        self.input_guard = input_guard

        self.running: bool = False
        self._current_op: AtomicOp | None = None  # 当前执行的指令
        self._async_ops: list[AtomicOp] = []  # 执行过异步操作
        self._op_lock: Lock = Lock()  # 操作锁 用于保证stop里的一定是最后执行的op

    def run_async(self) -> Future:
        """
        异步执行
        :return:
        """
        self.running = True
        future: Future = _od_op_task_executor.submit(self._run)
        future.add_done_callback(thread_utils.handle_future_result)
        return future

    def _run(self) -> bool:
        """
        执行
        :return: 是否完成所有指令了
        """
        for idx in range(len(self.op_list)):
            with self._op_lock:
                if not self.running:
                    # 被stop中断了 不继续后续的操作
                    break
                if self.input_guard is not None and not self.input_guard():
                    self.running = False
                    return True
                self._current_op = self.op_list[idx]
                if self._current_op.async_op:
                    self._async_ops.append(self._current_op)
                future: Future = _od_op_task_executor.submit(self._execute_op, self._current_op)
                future.add_done_callback(thread_utils.handle_future_result)

            # 使用短超时循环等待，以便能响应 stop()
            while not future.done():
                if not self.running:
                    break
                try:
                    future.result(timeout=0.05)
                except TimeoutError:
                    continue
                except Exception:
                    log.error('指令执行出错', exc_info=True)
                    break

            with self._op_lock:
                if not self.running:
                    # 被stop中断了 那么应该认为这个op没有执行完 不进行后续判断
                    break
                self._current_op = None
                if self.running and idx == len(self.op_list) - 1:
                    self.running = False
                    return True

        return False

    def _execute_op(self, op):
        token = execution_input_guard.set(self.input_guard)
        try:
            if self.running and (self.input_guard is None or self.input_guard()):
                op.execute()
        finally:
            execution_input_guard.reset(token)

    def stop(self) -> bool:
        """
        停止运行
        :return: 停止前是否已经完成所有指令了
        """
        with self._op_lock:
            if not self.running:
                # Completed indefinite presses still own a held key.
                for op in self._async_ops:
                    op.stop()
                self._current_op = None
                self._async_ops.clear()
                return True

            self.running = False
            if self._current_op is not None:
                self._current_op.stop()
                self._current_op = None
            for op in self._async_ops:
                op.stop()
            self._async_ops.clear()
            return False

    @staticmethod
    def after_app_shutdown() -> None:
        """
        整个脚本运行结束后的清理
        """
        _od_op_task_executor.shutdown(wait=False, cancel_futures=True)
