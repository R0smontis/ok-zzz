# -*- coding: utf-8 -*-
"""战斗引擎移植验证：DSL 解析 + 状态→动作闭环。"""
import time

import pytest

BATTLE_TEMPLATES = [
    '全配队通用',
    '专属配队-艾莲',
    '专属配队-莱卡恩',
    '专属配队-莱特',
    '击破站场-强攻速切',
    '异常站场-强攻速切',
    '强攻站场-击破支援速切',
    '自动守护',
]


@pytest.mark.parametrize('name', BATTLE_TEMPLATES)
def test_battle_config_parses(ctx, name):
    """8 套战斗 DSL 应能全量解析出场景与触发状态。"""
    battle_ctx = ctx.auto_battle_context
    battle_ctx._op_cache.clear()
    battle_ctx.init_auto_op(name)
    op = battle_ctx.auto_op
    assert op is not None
    assert len(op.scenes) > 0
    assert len(op.usage_states) > 0


def test_dodge_state_triggers_action(ctx, stubbed_controller):
    """注入 闪避识别-黄光 状态，引擎应自动触发闪避动作。"""
    context, recorder = stubbed_controller
    battle_ctx = context.auto_battle_context
    battle_ctx._op_cache.clear()
    battle_ctx.init_auto_op('全配队通用')

    battle_ctx.start_auto_battle()
    try:
        # 黄光触发窗口 [0, 0.3]s，轮询等待引擎线程响应；
        # 键盘键位下 dodge = shift，DSL 动作链必含闪避/普攻按键
        dodge_key = context.game_config.get_action_keys('keyboard')['dodge']
        from onedragon.base.conditional_operation.state_recorder import StateRecord
        deadline = time.time() + 5
        while time.time() < deadline:
            battle_ctx.state_record_service.update_state(
                StateRecord('闪避识别-黄光', time.time()))
            if any(ev[1] == dodge_key for ev in recorder.events):
                break
            time.sleep(0.05)
        assert any(ev[1] == dodge_key for ev in recorder.events), \
            f'未触发闪避动作({dodge_key}): {recorder.events}'
    finally:
        battle_ctx.stop_auto_battle()


def test_start_stop_engine(ctx, stubbed_controller):
    """start_auto_battle / stop_auto_battle 应能反复启停。"""
    context, recorder = stubbed_controller
    battle_ctx = context.auto_battle_context
    battle_ctx._op_cache.clear()
    battle_ctx.init_auto_op('全配队通用')

    for _ in range(2):
        battle_ctx.start_auto_battle()
        assert battle_ctx.auto_op.is_running
        battle_ctx.stop_auto_battle()
        assert not battle_ctx.auto_op.is_running
