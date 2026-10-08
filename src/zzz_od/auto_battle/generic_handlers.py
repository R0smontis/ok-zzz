"""Fallback handlers added after expanding user/merged battle templates."""
from onedragon.base.conditional_operation.state_handler import StateHandler


def normal_handler(unknown_only=False):
    return StateHandler({
        'states': ('[前台-未识别, 0, 1] & ' if unknown_only else '')
                  + '[按键可用-普通攻击, 0, 0.25]',
        'debug_name': '通用角色操作', 'operations': [{'op_name': '通用战斗'}],
    })


def event_handlers(triggers):
    result = []
    for warning in ('闪避识别-黄光', '闪避识别-红光', '闪避识别-声音'):
        if warning not in triggers:
            continue
        result.append(StateHandler({
            'states': '[按键可用-普通攻击, 0, 0.25] & [' + warning + ', 0, 0.25]',
            'debug_name': '通用角色黄光支援' if warning.endswith('黄光') else '通用角色闪避反击',
            'operations': [{'op_name': '实时战斗响应', 'data': [warning]}],
        }))
    if '按键可用-快速支援' in triggers:
        result.append(StateHandler({
            'states': '[按键可用-普通攻击, 0, 0.25] & [按键可用-快速支援, 0, 0.25]',
            'debug_name': '通用角色快速支援',
            'operations': [{'op_name': '按键-快速支援'}],
        }))
    if '按键可用-连携技' in triggers:
        # The timer and a known portrait have already confirmed this screen.
        # No normal attack, skill, turn or movement is issued on this UI.
        result.append(StateHandler({
            'states': '[按键可用-连携技, 0, 0.25]', 'debug_name': '通用角色连携技',
            'operations': [{'op_name': '按键-连携技-左'}],
        }))
    return result
