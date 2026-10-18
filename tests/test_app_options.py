# -*- coding: utf-8 -*-
"""细则选项桥验证：选项元数据完整性 + 配置写回持久化。"""


def test_options_data_coverage():
    """选项元数据应覆盖全部应用，重点应用细则选项数量达标。"""
    from zzz_od.application.app_options_data import APP_OPTIONS
    by_id = {a['app_id']: a for a in APP_OPTIONS if 'app_id' in a}
    assert len(by_id) >= 25
    assert len(by_id['suibian_temple']['options']) >= 10
    assert len(by_id['commission_assistant']['options']) >= 8
    assert len(by_id['world_patrol']['options']) >= 6
    assert len(by_id['lost_void']['options']) >= 4
    # 枚举选项应带 choices
    coffee = {o['key']: o for o in by_id['coffee']['options']}
    assert coffee['transport_point']['type'] == 'enum'
    assert len(coffee['transport_point']['choices']) >= 2


def test_config_write_back_persists():
    """选项写回应持久化到一条龙格式的应用配置 YAML。"""
    from zzz_od.application.charge_plan.charge_plan_config import ChargePlanConfig
    config = ChargePlanConfig(0, 'one_dragon')
    config.update('loop', False)
    config.update('restore_charge', '使用以太电池')

    reloaded = ChargePlanConfig(0, 'one_dragon')
    assert reloaded.get('loop') is False
    assert reloaded.get('restore_charge') == '使用以太电池'
    # 运行目录已由 conftest 隔离为临时副本，无需恢复默认值。


def test_generated_task_module():
    """生成的任务模块应可导入且类数量正确。"""
    import src.tasks.app_tasks as app_tasks
    classes = [v for k, v in vars(app_tasks).items()
               if isinstance(v, type) and v.__module__ == app_tasks.__name__]
    assert len(classes) == 29
    ids = {c.app_id for c in classes}
    assert {'email', 'coffee', 'charge_plan', 'withered_domain', 'world_patrol'} <= ids
    # 队列本身不生成任务类（由 OneDragonTask 承担）
    assert 'one_dragon' not in ids
