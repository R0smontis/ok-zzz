# -*- coding: utf-8 -*-
"""ok-ww 式任务组织验证。"""


def test_trigger_tasks_registered():
    """战斗/闪避触发器应注册进 trigger_tasks（ok-ww 模式）。"""
    from src.config import config
    triggers = [t[1] for t in config['trigger_tasks']]
    assert 'AutoCombatTask' in triggers
    assert 'DodgeAssistantTriggerTask' in triggers
    assert 'AutoDialogueTriggerTask' in triggers


def test_onetime_tasks_concise():
    """一次性任务应为精简分组清单（一条龙 + 大型玩法 + 工具）。"""
    from src.config import config
    names = [t[1] for t in config['onetime_tasks']]
    assert 'OneDragonDailyTask' in names
    assert 'App_ChargePlan' in names
    # 简单日常应用不再平铺（收进一条龙多选）
    assert 'App_Email' not in names
    assert 'App_CityFund' not in names
    # 战斗/闪避助手改由触发器承担
    assert 'App_AutoBattle' not in names
    assert 'App_DodgeAssistant' not in names
    assert len(names) <= 22


def test_daily_task_app_names_align():
    """一条龙多选的应用名应与注册表完全对齐。"""
    from src.tasks.daily_task import OneDragonDailyTask
    names = OneDragonDailyTask._all_app_names()
    assert len(names) >= 18
    assert '邮件' in names and '体力刷本' in names


def test_battle_template_scan():
    """战斗/闪避配置下拉应扫描到模板文件。"""
    from src.tasks.auto_combat_task import list_battle_templates
    battle = list_battle_templates('auto_battle', '.merged.yml')
    assert '全配队通用' in battle
    dodge = list_battle_templates('dodge', '.merged.yml')
    assert '闪避' in dodge
