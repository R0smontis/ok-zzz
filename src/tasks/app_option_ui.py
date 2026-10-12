# -*- coding: utf-8 -*-
"""应用控件说明与模板下拉；不改变底层配置键，兼容已有配置。"""
from src.tasks.auto_combat_task import list_battle_templates

OPTION_LABELS = {
    'plan_list': '刷本计划',
    'auto_battle': '战斗配置', 'auto_battle_config': '战斗配置',
    'auto_battle_switch': '战斗开关快捷键', 'dodge_config': '闪避配置',
    'dodge_assistant_config': '闪避配置', 'dodge_switch': '闪避开关快捷键',
    'auto_ultimate_enabled': '自动终结技',
    'screenshot_interval': '截图间隔秒', 'use_merged_file': '使用合并指令文件',
    'challenge_config': '挑战配置', 'daily_plan_times': '每日计划次数',
    'weekly_plan_times': '每周计划次数', 'mission_name': '任务名称',
    'extra_task': '额外任务', 'extra_exit': '额外任务退出时机',
    'predefined_team_idx': '预备编队编号', 'loop': '循环执行',
    'weekly_challenge_start_weekday': '每周挑战开始日',
    'combat_simulation_double_reward_config': '双倍奖励刷本计划',
    'daily_reset_plan_times': '每日重置计划次数', 'double_reward': '刷取双倍奖励',
    'restore_charge': '体力恢复方式', 'transport_point': '传送点',
    'run_charge_plan_afterwards': '完成后执行体力计划',
    'dialog_click_interval': '对话点击间隔秒', 'dialog_option': '对话选项',
    'sleep_after_empty_screen': '空白画面等待秒数', 'story_mode': '剧情处理方式',
    'agent_name_1': '录像店推荐角色一', 'agent_name_2': '录像店推荐角色二',
    'dismantle_abandon': '拆解已标记弃置的驱动盘', 'dismantle_level': '拆解等级',
    'critical_max_node_idx': '式舆防卫战最大节点', 'exp_grind_mode': '经验刷取模式',
    'daily_loop_count': '每日循环次数', 'loop_interval_seconds': '循环间隔秒',
    'route_list': '路线清单', 'route_retry_action': '路线重试处理',
    'route_retry_times': '路线重试次数', 'ui_disappear_action': '界面消失处理',
    'ui_disappear_seconds': '界面消失等待秒数',
    'operation_template': '指令模板', 'repeat_enabled': '重复执行',
    'dodge_detect': '检测闪避预警', 'frequency_second': '截图频率秒',
    'key_save': '保存截图快捷键', 'length_second': '保留截图时长秒',
    'mini_map_angle_detect': '检测小地图朝向', 'screenshot_before_key': '保留按键前截图',
    'selected_sign': '每日签到目标', 'adventure_duration': '游历时长',
    'adventure_mission_1': '游历任务一', 'adventure_mission_2': '游历任务二',
    'adventure_mission_3': '游历任务三', 'adventure_mission_4': '游历任务四',
    'auto_manage_enabled': '自动托管', 'craft_drag_times': '制造最大下拉次数',
    'boo_box_adventure_price': '邦巢游历最低价格',
    'boo_box_craft_price': '邦巢制造最低价格', 'boo_box_sell_price': '邦巢出售最低价格',
    'boo_box_purchase_enabled': '邦巢购买', 'good_goods_purchase_enabled': '好物铺购买',
    'pawnshop_crest_enabled': '云纹徽兑换', 'pawnshop_crest_priority': '云纹徽兑换优先级',
    'pawnshop_crest_unlimited_denny_enabled': '云纹徽兑换不限购丁尼',
    'pawnshop_omnicoin_enabled': '万能币兑换', 'pawnshop_omnicoin_priority': '万能币兑换优先级',
    'yum_cha_sin': '饮茶仙', 'yum_cha_sin_period_refresh': '饮茶仙定期采办刷新',
    'matrix_team_mode': '矩阵行动编队方式',
    'matrix_agent_1': '主战角色一', 'matrix_agent_2': '主战角色二',
    'matrix_agent_3': '主战角色三',
    'Dodge Key': '闪避按键', 'Normal Attack Key': '普通攻击按键',
    'Special Attack Key': '特殊技按键', 'Ultimate Key': '终结技按键',
    'Switch Agent Key': '切换角色按键',
}

# 计划清单由引擎保存为列表；任务界面以 JSON 文本承载，并保留引擎维护的完成次数。
PLAN_LIST_APPS = ('charge_plan', 'notorious_hunt')


def choice_schema(options, labels=None):
    return {'type': 'drop_down', 'options': list(options),
            'option_labels': labels or {}, 'localized_choices': True}


def option_schema(app_id, key):
    """从实际游戏数据建立选项，区分枚举名、显示名称和存储值。"""
    if key == 'route_list':
        import yaml
        from pathlib import Path
        from onedragon.utils import os_utils
        directory = Path(os_utils.get_path_under_work_dir('config', 'world_patrol_route_list'))
        names = []
        for path in sorted(directory.glob('*.yml')):
            try:
                data = yaml.safe_load(path.read_text(encoding='utf-8'))
                if isinstance(data, dict) and isinstance(data.get('name'), str):
                    names.append(data['name'])
            except (OSError, ValueError, yaml.YAMLError):
                continue
        return choice_schema(['', *dict.fromkeys(names)], {'': '默认路线（全部）'})
    if key in ('auto_battle', 'auto_battle_config', 'dodge_config', 'dodge_assistant_config',
               'challenge_config', 'operation_template'):
        directory = {'operation_template': 'auto_battle_operation'}.get(key)
        if key == 'challenge_config':
            directory = {'lost_void': 'lost_void_challenge',
                         'withered_domain': 'hollow_zero_challenge'}.get(app_id)
        elif directory is None:
            directory = 'dodge' if 'dodge' in key else 'auto_battle'
        if directory:
            options = list_battle_templates(directory)
            return choice_schema(options)
    if key == 'matrix_team_mode':
        schema = choice_schema(['沿用挑战配置', '自定义编队'])
        schema['sub_configs'] = {'自定义编队': ['matrix_agent_1', 'matrix_agent_2', 'matrix_agent_3']}
        return schema
    if key in ('agent_name_1', 'agent_name_2', 'matrix_agent_1', 'matrix_agent_2', 'matrix_agent_3'):
        from zzz_od.game_data.agent import AgentEnum
        matrix = key.startswith('matrix_')
        # 编队存代理人 ID；录像店推荐按原版约定存名字。
        options = ['unknown' if matrix else '随机']
        labels = {'unknown': '未选择'}
        for item in AgentEnum:
            agent = item.value
            raw = agent.agent_id if matrix else agent.agent_name
            options.append(raw)
            labels[raw] = agent.agent_name
        return choice_schema(options, labels)
    if key == 'selected_sign':
        return choice_schema(['hou_hou_bakery', 'trigrams_collection', 'scratch_card'],
                             {'hou_hou_bakery': '吼吼饼铺', 'trigrams_collection': '卦象集录',
                              'scratch_card': '刮刮卡'})
    if key == 'route_retry_action':
        return choice_schema(['skip_on_stuck_again', 'retry_on_stuck_again'],
                             {'skip_on_stuck_again': '再次卡住时跳过路线',
                              'retry_on_stuck_again': '再次卡住时重试路线'})
    if key == 'ui_disappear_action':
        return choice_schema(['silent_fail', 'restart_and_skip', 'restart_and_retry'],
                             {'silent_fail': '停止当前任务', 'restart_and_skip': '重启游戏并跳过路线',
                              'restart_and_retry': '重启游戏并重试路线'})
    if key == 'weekly_challenge_start_weekday':
        return choice_schema(range(1, 8), dict(enumerate(
            ['周一', '周二', '周三', '周四', '周五', '周六', '周日'], 1)))
    if key == 'predefined_team_idx':
        return choice_schema(range(-1, 20), {-1: '不指定预备编队',
                                            **{idx: f'预备编队 {idx + 1}' for idx in range(20)}})
    if key == 'mission_name':
        import yaml
        from onedragon.utils import os_utils
        from pathlib import Path
        data = yaml.safe_load(Path(os_utils.get_path_under_work_dir(
            'assets', 'game_data', 'compendium_data.yml')).read_text(encoding='utf-8'))
        names = []
        for tab in data:
            for category in tab.get('category_list', []):
                for mission_type in category.get('mission_type_list', []):
                    match = (mission_type['mission_type_name'] == '迷失之地' if app_id == 'lost_void'
                             else mission_type['mission_type_name'] in ('旧都列车', '施工废墟', '巨厦遗骸'))
                    if match:
                        names.extend(m['mission_name'] for m in mission_type.get('mission_list', []))
        return choice_schema(dict.fromkeys(names))
    if app_id == 'suibian_temple':
        from zzz_od.application.suibian_temple import suibian_temple_config as temple
        enum = None
        if key == 'adventure_duration':
            enum = temple.SuibianTempleAdventureDispatchDuration
        elif key.startswith('adventure_mission_'):
            enum = temple.SuibianTempleAdventureMission
        elif key in ('boo_box_adventure_price', 'boo_box_craft_price', 'boo_box_sell_price'):
            enum = temple.BangbooPrice
        elif key == 'pawnshop_crest_priority':
            enum = temple.PawnshopCrestGoods
        elif key == 'pawnshop_omnicoin_priority':
            enum = temple.PawnshopOmnicoinGoods
        if enum is not None:
            schema = choice_schema([member.name for member in enum],
                                   {member.name: str(member.value) for member in enum})
            if key.endswith('_priority'):
                schema['type'] = 'ordered_choices'
            return schema


def configure_app_options(task):
    from src.tasks.option_widgets import install_option_widgets
    install_option_widgets()
    from zzz_od.application.app_options_data import APP_OPTIONS
    metadata = next((a for a in APP_OPTIONS if a.get('app_id') == task.app_id), {})
    from src.tasks.task_presentation import TASK_DESCRIPTIONS, OPTION_DESCRIPTIONS, DEBUG_APPS
    task.description = TASK_DESCRIPTIONS.get(task.app_id, '')
    if task.app_id in DEBUG_APPS:
        task.visible = False
        task.debug_tool = True
    for option in metadata.get('options', []):
        key = option['key']
        label = OPTION_LABELS.get(key, key)
        description = OPTION_DESCRIPTIONS.get(key, '')
        if option['type'] == 'json':
            description = (description+'；' if description else '')+'填写JSON对象或数组，运行前校验，格式错误时停止任务'
        elif key == 'predefined_team_idx':
            description = '不指定时沿用当前队伍'
        elif key == 'weekly_challenge_start_weekday':
            description = '从指定星期开始执行每周挑战'
        task.config_description[key] = description
        schema = option_schema(task.app_id, key)
        if schema is None and option.get('choices'):
            schema = choice_schema(option['choices'])
        if schema is not None:
            options = schema['options']
            current = task.config.get(key, task.default_config.get(key))
            if schema['type'] == 'drop_down' and current is not None and current not in options:
                options.append(current)
                schema['option_labels'][current] = f'已有配置：{current}'
            task.config_type[key] = schema
            if schema['type'] == 'ordered_choices':
                task.config_description[key] = f'{label}；从上到下依次兑换，选择“不兑换”以移除物品'
        if key.startswith('matrix_agent_'):
            task.config_description[key] = f'主战第 {key[-1]} 槽；未选择时留空'
        elif key == 'matrix_team_mode':
            task.config_description[key] = '仅矩阵行动生效；按角色一、二、三的顺序组成主战队伍'
    if task.app_id == 'lost_void':
        task.config_description['extra_task'] = '完成悬赏委托：按画面当前目标判断，满额后领取并结束；需要继续刷本可选“完成周计划次数”'
    if task.app_id in PLAN_LIST_APPS:
        # '' 表示尚未从引擎读取；已保存的计划文本优先，重启后不丢失界面中的修改。
        if task.config.get('plan_list') in ('', None):
            from ok import og
            if getattr(og, 'my_app', None) is not None and hasattr(og.my_app, 'context'):
                app = task.ctx.run_context.get_config(task.app_id, instance_idx=task.ctx.current_instance_idx)
                import json
                task.config['plan_list'] = json.dumps([item.to_dict() for item in app.plan_list], ensure_ascii=False)
        task.default_config['plan_list'] = '[]'
        if 'plan_list' not in task._option_keys:
            task._option_keys.append('plan_list')
    if task.app_id == 'notorious_hunt':
        task.config_type['plan_list'] = {'type': 'charge_plans', 'mode': 'notorious_hunt', 'label': '狩猎计划'}
        task.config_description['plan_list'] = ('从上到下挑战；选择狩猎目标、等级、增益与编队，'
                                                '未配置计划时只领取奖励')
    if task.app_id == 'charge_plan':
        task.config_type['plan_list'] = {'type': 'charge_plans'}
        task.config_type['combat_simulation_double_reward_config'] = {'type': 'charge_plans', 'single': True}
        task.config_type['double_reward'] = {'sub_configs': {True: ['combat_simulation_double_reward_config']}}
        task.config_description['plan_list'] = '从上到下执行；下拉选择类别、类型与副本，填写次数与编队；多条计划在列表内滚动查看'
        task.config_description['combat_simulation_double_reward_config'] = '有实战模拟室双倍奖励次数时优先执行这一条计划'
