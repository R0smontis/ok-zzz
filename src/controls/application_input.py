"""独立任务和一条龙共用的输入准备：输入方式只由首页的前台/后台模式决定。"""
from contextlib import contextmanager


@contextmanager
def application_inputs(task):
    ctx = task.ctx
    # 无控制器的离线任务替身仍能验证业务逻辑。
    if not hasattr(ctx, 'init_controller'):
        yield
        return
    try:
        try:
            ctx.init_controller(activate=False)
        except RuntimeError as exc:
            task.info['执行结果'] = str(exc)
            task.log_error(str(exc), notify=True)
            raise
        controller = ctx.controller
        from src.controls.window_input import ELEVATION_MESSAGE, input_blocked_by_elevation
        game_win = getattr(controller, 'game_win', None)
        if game_win is not None and input_blocked_by_elevation(game_win.get_hwnd()):
            task.info['执行结果'] = '需要管理员权限'
            task.log_error(ELEVATION_MESSAGE, notify=True)
            raise PermissionError(ELEVATION_MESSAGE)
        task.info['任务交互方式'] = '后台模式' if controller.background_mode else '前台模式'
        task.log_info(f'任务交互方式：{task.info["任务交互方式"]}')
        yield
    finally:
        if ctx.controller is not None:
            ctx.controller.cancel_inputs()
