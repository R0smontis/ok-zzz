# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: one_dragon/base/operation/one_dragon_finalizer.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from onedragon.utils import cmd_utils

if TYPE_CHECKING:
    from onedragon.base.operation.application.application_run_context import (
        ApplicationRunResult,
    )
    from onedragon.base.operation.one_dragon_context import OneDragonContext


@dataclass(slots=True)
class AfterDoneRequest:
    """结束后动作请求。"""

    close_game: bool = False
    shutdown_seconds: int | None = None
    hibernate: bool = False
    sleep: bool = False


def execute_after_done(
    ctx: OneDragonContext,
    run_result: ApplicationRunResult | None,
    request: AfterDoneRequest,
) -> None:
    """执行结束后动作。"""
    from onedragon.base.operation.application.application_run_context import (
        RunFinishReason,
    )

    if (
        run_result is None
        or run_result.finish_reason != RunFinishReason.COMPLETED
        or not (
            request.close_game
            or request.shutdown_seconds is not None
            or request.hibernate
            or request.sleep
        )
    ):
        return

    if request.close_game and ctx.controller is not None:
        ctx.controller.close_game()
    if request.shutdown_seconds is not None:
        cmd_utils.shutdown_sys(request.shutdown_seconds)
    if request.hibernate:
        cmd_utils.hibernate_sys()
    if request.sleep:
        cmd_utils.sleep_sys()
