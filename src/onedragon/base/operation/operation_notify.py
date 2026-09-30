# -*- coding: utf-8 -*-
"""节点通知兼容层（ok-zzz stub）。

原版 operation_notify 依赖 PushService/NotifyPool 完成节点级推送；
P11 接入推送体系前，本模块保持装饰器与调用点可用（消息仅记录日志）。
"""
import functools

from onedragon.utils.log_utils import log


class NotifyTiming:
    """节点通知时机（与原版枚举值保持兼容）。"""

    CURRENT_DONE = 'current_done'
    CURRENT_SUCCESS = 'current_success'
    CURRENT_FAIL = 'current_fail'
    PREVIOUS_DONE = 'previous_done'
    APPLICATION_DONE = 'application_done'


class NotifyDetail:
    OFF = 'off'
    ERROR_ONLY = 'error_only'
    ALL = 'all'
    MERGE = 'merge'


def node_notify(when: str = NotifyTiming.CURRENT_DONE,
                custom_message: str = None,
                send_image: bool = False,
                detail: str = NotifyDetail.ERROR_ONLY):
    """节点通知装饰器：P11 前仅透传，不产生副作用。"""

    def decorator(func):
        func.node_notify_annotation = {
            'when': when,
            'custom_message': custom_message,
            'send_image': send_image,
            'detail': detail,
        }

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper

    return decorator


def send_node_notify(op, round_result, from_node, to_node) -> None:
    """节点跳转通知点：记录日志，暂不推送。"""
    try:
        status = getattr(round_result, 'status', None)
        result = getattr(getattr(round_result, 'result', None), 'name', None)
        log.debug(f'节点通知 {getattr(from_node, "cn", from_node)} -> '
                  f'{getattr(to_node, "cn", to_node)} 结果={result} 状态={status}')
    except Exception:
        pass


def send_application_notify(app, success: bool) -> None:
    """应用级通知点：记录日志，暂不推送。"""
    try:
        log.info(f'应用通知 {getattr(app, "op_name", app)} 成功={success}')
    except Exception:
        pass
