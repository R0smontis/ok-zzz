"""独立任务和一条龙共用的后台输入策略。"""
from contextlib import contextmanager

from ok import ConfigOption, og

task_input_config = ConfigOption('任务后台操作', {'操作方式': '自动后台'},
    description='应用任务和一条龙的输入方式；后台操作不切前台、不移动系统光标',
    config_type={'操作方式': {'type': 'drop_down',
        'options': ['自动后台', '窗口消息后台', '手柄后台', '跟随交互方式']}},
    config_description={'操作方式': '自动后台优先使用虚拟手柄，不可用时使用窗口消息；窗口消息的移动与转向兼容性需实测；跟随交互方式保留原设置'})


def task_input_mode():
    global_config = getattr(og, 'global_config', None)
    if global_config is None:
        return '自动后台'
    return global_config.get_config(task_input_config).get('操作方式', '自动后台')


@contextmanager
def application_inputs(task):
    ctx = task.ctx
    # 无控制器的离线任务替身仍能验证业务逻辑。
    if not hasattr(ctx, 'init_controller'):
        yield
        return
    mode = task_input_mode()
    previous = getattr(ctx, '_task_input_mode', None)
    try:
        if mode == '跟随交互方式':
            ctx._task_input_mode = None
        else:
            ctx._task_input_mode = 'messages' if mode == '窗口消息后台' else 'gamepad'
        try:
            ctx.init_controller(activate=False)
        except Exception as exc:
            if mode != '自动后台':
                raise
            task.log_info(f'虚拟手柄不可用，使用窗口消息后台：{exc}')
            ctx._task_input_mode = 'messages'
            ctx.init_controller(activate=False)
        controller = ctx.controller
        task.info['任务交互方式'] = ('手柄后台' if controller.background_mode else
            '窗口消息后台' if controller.message_mode else '跟随交互方式（前台）')
        task.log_info(f'任务交互方式：{task.info["任务交互方式"]}')
        yield
    finally:
        ctx._task_input_mode = previous
        if ctx.controller is not None:
            ctx.controller.cancel_inputs()
            ctx.game_config._task_input_mode = previous
            ctx.controller.sync_game_config(ctx.game_config, activate=False)
