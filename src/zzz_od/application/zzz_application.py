# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/application/zzz_application.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from collections.abc import Callable

from onedragon.base.operation.application_base import Application
from onedragon.base.operation.application_run_record import AppRunRecord
from onedragon.base.operation.operation import Operation
from onedragon.base.operation.operation_base import OperationResult
from zzz_od.context.zzz_context import ZContext
from onedragon.base.operation.operation_round_result import OperationRoundResult
from zzz_od.operation.enter_game import game_startup
from zzz_od.operation.enter_game.game_startup import at_title_screen
from zzz_od.operation.enter_game.open_and_enter_game import OpenAndEnterGame


class ZApplication(Application):

    def __init__(self, ctx: ZContext, app_id: str,
                 node_max_retry_times: int = 1,
                 op_name: str | None = None,
                 timeout_seconds: float = -1,
                 op_callback: Callable[[OperationResult], None] | None = None,
                 need_check_game_win: bool = True,
                 op_to_enter_game: Operation | None = None,
                 run_record: AppRunRecord | None = None,
                 ):
        self.ctx: ZContext = ctx
        if op_to_enter_game is None:
            op_to_enter_game = OpenAndEnterGame(ctx)
        Application.__init__(
            self,
            ctx=ctx,
            app_id=app_id,
            node_max_retry_times=node_max_retry_times,
            op_name=op_name,
            timeout_seconds=timeout_seconds,
            op_callback=op_callback,
            need_check_game_win=need_check_game_win,
            op_to_enter_game=op_to_enter_game,
            run_record=run_record,
        )

    STATUS_AT_TITLE: str = game_startup.STATUS_AT_TITLE
    STATUS_STARTING: str = game_startup.STATUS_STARTING

    def check_game_window(self) -> OperationRoundResult:
        """An open game window may still be starting up or on the title; route it through the enter-game step.

        The not-ready edge leads to OpenAndEnterGame, which skips launching an already open game.
        A freshly started game process goes there until it reaches the game once, because its splash
        screens are neither the title nor a game screen.
        """
        result = Application.check_game_window(self)
        if not result.is_success:
            return result
        try:
            screen = self.screenshot()
        except Exception:
            return result  # The app's own first step reports capture problems.
        if at_title_screen(self.ctx, screen):
            return self.round_fail(ZApplication.STATUS_AT_TITLE)
        if game_startup.startup_seconds(self.ctx) is not None:
            if not game_startup.in_game_screen(self.ctx, screen):
                return self.round_fail(ZApplication.STATUS_STARTING)
            game_startup.mark_game_entered(self.ctx)  # Logged in by hand already.
        return result

    def open_and_enter_game(self) -> OperationRoundResult:
        result = Application.open_and_enter_game(self)
        if result.is_success:
            game_startup.mark_game_entered(self.ctx)
        return result

    def handle_resume(self) -> None:
        self.ctx.controller.active_window()
        Application.handle_resume(self)
