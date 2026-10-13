# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/application/world_patrol/world_patrol_run_record.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from onedragon.base.operation.application_run_record import AppRunRecord


class WorldPatrolRunRecord(AppRunRecord):

    def __init__(self, instance_idx: int | None = None, game_refresh_hour_offset: int = 0):
        self.finished: list[str] = []
        self.time_cost: dict[str, list[float]] = {}
        self.completed_rounds: int = 0
        self.routes_per_round: int = 0
        AppRunRecord.__init__(self, 'world_patrol', instance_idx=instance_idx,
                              game_refresh_hour_offset=game_refresh_hour_offset)
        self.finished = self.get('finished', [])
        self.completed_rounds = self.get('completed_rounds', 0)
        self.routes_per_round = self.get('routes_per_round', 0)

        # 每日多轮循环运行时字段（仅内存，不持久化）
        self.current_round: int = 1
        self.total_rounds: int = 1
        self.round_start_time: float | None = None
        self.round_wait_seconds: float = 0.0
        self.round_wait_start_time: float | None = None
        self._migrate_completion_record()

    def _migrate_completion_record(self) -> None:
        """旧版本把遍历结束误记为完成轮次；有明确缺项的最后一轮必须恢复为可续跑。"""
        if self.get('completion_version', 0) >= 1:
            return
        if (not self._should_reset_by_dt() and self.run_status == AppRunRecord.STATUS_SUCCESS
                and self.completed_rounds > 0 and self.routes_per_round > 0
                and len(set(self.finished)) < self.routes_per_round):
            from onedragon.utils.log_utils import log
            self.completed_rounds -= 1
            self.run_status = AppRunRecord.STATUS_WAIT
            self.update('completed_rounds', self.completed_rounds, False)
            self.update('run_status', self.run_status, False)
            log.warning('修正巡逻旧完成记录：仅完成 %d/%d 条，保留完成路线并恢复续跑',
                        len(set(self.finished)), self.routes_per_round)
        self.update('completion_version', 1, False)
        self.save()

    def reset_record(self):
        AppRunRecord.reset_record(self)
        self.finished = []
        self.completed_rounds = 0
        self.update('finished', self.finished, False)
        self.update('completed_rounds', self.completed_rounds, False)
        self.save()

    def reset_round_timing(self) -> None:
        """重置本轮的计时字段，不影响 finished、completed_rounds 等持久化记录。"""
        self.round_start_time = None
        self.round_wait_seconds = 0.0
        self.round_wait_start_time = None

    def reset_finished(self) -> None:
        """清空当日已完成路线列表，不影响其他记录字段。"""
        self.finished = []
        self.update('finished', self.finished, False)
        self.save()

    def inc_completed_rounds(self) -> None:
        """当日已完成轮数 +1，下次启动据此决定从第几轮继续。"""
        if self.routes_per_round <= 0 or len(set(self.finished)) < self.routes_per_round:
            raise ValueError('路线未全部完成，不能计入完成轮次')
        self.completed_rounds += 1
        self.update('completed_rounds', self.completed_rounds, False)
        self.save()

    def set_routes_per_round(self, count: int) -> None:
        """记录本次任务执行的路线数。"""
        self.routes_per_round = count
        self.update('routes_per_round', self.routes_per_round, False)
        self.save()

    def add_record(self, route_id: str):
        if route_id not in self.finished:
            self.finished.append(route_id)
        if route_id not in self.time_cost:
            self.time_cost[route_id] = []
        while len(self.time_cost[route_id]) > 3:
            self.time_cost[route_id].pop(0)

        self.update('dt', self.dt, False)
        self.update('finished', self.finished, False)
        self.save()
