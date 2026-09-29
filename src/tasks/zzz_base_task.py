# -*- coding: utf-8 -*-
"""ok-zzz 任务基类。"""
from ok import BaseTask, og

from onedragon.utils.log_utils import log


class ZzzBaseTask(BaseTask):
    """提供 ZzzContext 访问与游戏窗口激活等公共能力。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @property
    def ctx(self):
        """ZzzContext（惰性创建，首次访问时完成 ok-script 设备桥接）。"""
        return og.my_app.context

    def activate_game_window(self):
        """把游戏窗口带到前台（委托给当前 interaction，如可用）。"""
        device_manager = getattr(og.executor, 'device_manager', None)
        interaction = getattr(device_manager, 'interaction', None)
        if interaction is None:
            return
        for method_name in ('try_activate', 'activate'):
            method = getattr(interaction, method_name, None)
            if callable(method):
                try:
                    method()
                    return
                except Exception as e:
                    log.warning(f'激活游戏窗口失败({method_name}): {e}')
