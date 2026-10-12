# -*- coding: utf-8 -*-
# 由 tools/gen_app_tasks.py 生成：一条龙各应用的 ok-script 运行任务。
# 每个任务的细则选项与一条龙原版配置键一致，运行前写回应用配置。
# 重新生成: .venv/Scripts/python tools/gen_app_tasks.py

import json

from ok import BaseTask

from src.tasks.app_task_base import AppTaskBase


class App_AutoBattle(AppTaskBase):
    app_id = 'auto_battle'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '⚔️ 自动战斗'
        self.description = '运行一条龙应用：自动战斗'
        self.default_config.update({
            'auto_battle_config': '全配队通用',
            'screenshot_interval': 0.02,
            'use_merged_file': True,
            'auto_ultimate_enabled': False,
            '结束后': '无',
            '关机延迟秒': 60,
        })
        self.config_type.update({
            'auto_battle_config': {'type': 'drop_down', 'options': ['全配队通用']},
        })
        self._option_keys = ['auto_battle_config', 'screenshot_interval', 'use_merged_file', 'auto_ultimate_enabled']


class App_DodgeAssistant(AppTaskBase):
    app_id = 'dodge_assistant'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '🛡️ 闪避助手'
        self.description = '运行一条龙应用：闪避助手'
        self.default_config.update({
            'dodge_assistant_config': '闪避',
            'screenshot_interval': 0.02,
            '结束后': '无',
            '关机延迟秒': 60,
        })
        self.config_type.update({
            'dodge_assistant_config': {'type': 'drop_down', 'options': ['闪避', '智能格挡', '本-格挡', '闪A切下一个', '闪A切强攻', '切换角色-下一个']},
        })
        self._option_keys = ['dodge_assistant_config', 'screenshot_interval']


class App_ChargePlan(AppTaskBase):
    app_id = 'charge_plan'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '⚡ 体力刷本'
        self.description = '运行一条龙应用：体力刷本'
        self.default_config.update({
            'plan_list': '',
            'combat_simulation_double_reward_config': '{\n "tab_name": "训练",\n "category_name": "实战模拟室",\n "mission_type_name": "基础材料",\n "mission_name": "调查专项",\n "level": "默认等级",\n "auto_battle_config": "全配队通用",\n "run_times": 0,\n "plan_times": 1,\n "card_num": "默认数量",\n "predefined_team_idx": -1,\n "notorious_hunt_buff_num": 1,\n "plan_id": "b903dbed-9d85-45ba-bb56-c43483df1cb8",\n "skipped": false\n}',
            'daily_reset_plan_times': False,
            'double_reward': False,
            'loop': True,
            'restore_charge': '不使用',
            '结束后': '无',
            '关机延迟秒': 60,
        })
        self.config_type.update({
            'combat_simulation_double_reward_config': {'type': 'text_edit'},
            'restore_charge': {'type': 'drop_down', 'options': ['不使用', '使用储蓄电量', '使用以太电池', '同时使用储蓄电量和以太电池']},
        })
        self._option_keys = ['combat_simulation_double_reward_config', 'daily_reset_plan_times', 'double_reward', 'loop', 'restore_charge']


class App_CityFund(AppTaskBase):
    app_id = 'city_fund'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '🏙️ 丽都城募'
        self.description = '运行一条龙应用：丽都城募'
        self.default_config.update({'结束后': '无', '关机延迟秒': 60})
        self._option_keys = []


class App_Coffee(AppTaskBase):
    app_id = 'coffee'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '☕ 咖啡店'
        self.description = '运行一条龙应用：咖啡店'
        self.default_config.update({
            'run_charge_plan_afterwards': False,
            'transport_point': '六分街 - 咖啡店',
            '结束后': '无',
            '关机延迟秒': 60,
        })
        self.config_type.update({
            'transport_point': {'type': 'drop_down', 'options': ['六分街 - 咖啡店', '澄辉坪 - 汀曼咖啡', '布亚斯特城区 - 片刻闲']},
        })
        self._option_keys = ['run_charge_plan_afterwards', 'transport_point']


class App_CommissionAssistant(AppTaskBase):
    app_id = 'commission_assistant'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '🤝 委托助手'
        self.description = '运行一条龙应用：委托助手'
        self.default_config.update({
            'auto_battle': '全配队通用',
            'auto_battle_switch': '6',
            'dialog_click_interval': 0.5,
            'dialog_option': '最后一个',
            'dodge_config': '闪避',
            'dodge_switch': '5',
            'sleep_after_empty_screen': 0.5,
            'story_mode': '自动点击',
            '结束后': '无',
            '关机延迟秒': 60,
        })
        self.config_type.update({
            'dialog_option': {'type': 'drop_down', 'options': ['第一个', '最后一个']},
            'story_mode': {'type': 'drop_down', 'options': ['自动点击', '等待剧情自动播放', '跳过剧情']},
        })
        self._option_keys = ['auto_battle', 'auto_battle_switch', 'dialog_click_interval', 'dialog_option', 'dodge_config', 'dodge_switch', 'sleep_after_empty_screen', 'story_mode']


class App_DailySignin(AppTaskBase):
    app_id = 'daily_signin'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '📅 每日签到'
        self.description = '运行一条龙应用：每日签到'
        self.default_config.update({
            'selected_sign': 'hou_hou_bakery',
            '结束后': '无',
            '关机延迟秒': 60,
        })
        self._option_keys = ['selected_sign']


class App_OperationDebug(AppTaskBase):
    app_id = 'operation_debug'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '▶️ 指令调试'
        self.description = '运行一条龙应用：指令调试'
        self.default_config.update({
            'operation_template': '安比-3A特殊攻击',
            'repeat_enabled': True,
            '结束后': '无',
            '关机延迟秒': 60,
        })
        self._option_keys = ['operation_template', 'repeat_enabled']


class App_ScreenshotHelper(AppTaskBase):
    app_id = 'screenshot_helper'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '▶️ 闪避截图'
        self.description = '运行一条龙应用：闪避截图'
        self.default_config.update({
            'dodge_detect': True,
            'frequency_second': 0.1,
            'key_save': '1',
            'length_second': 1,
            'mini_map_angle_detect': False,
            'screenshot_before_key': True,
            '结束后': '无',
            '关机延迟秒': 60,
        })
        self._option_keys = ['dodge_detect', 'frequency_second', 'key_save', 'length_second', 'mini_map_angle_detect', 'screenshot_before_key']


class App_DriveDiscDismantle(AppTaskBase):
    app_id = 'drive_disc_dismantle'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '💎 驱动盘拆解'
        self.description = '运行一条龙应用：驱动盘拆解'
        self.default_config.update({
            'dismantle_abandon': False,
            'dismantle_level': 'A及以下',
            '结束后': '无',
            '关机延迟秒': 60,
        })
        self.config_type.update({
            'dismantle_level': {'type': 'drop_down', 'options': ['B', 'A及以下', 'S及以下']},
        })
        self._option_keys = ['dismantle_abandon', 'dismantle_level']


class App_Email(AppTaskBase):
    app_id = 'email'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '📧 邮件'
        self.description = '运行一条龙应用：邮件'
        self.default_config.update({'结束后': '无', '关机延迟秒': 60})
        self._option_keys = []


class App_EngagementReward(AppTaskBase):
    app_id = 'engagement_reward'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '🎁 活跃度奖励'
        self.description = '运行一条龙应用：活跃度奖励'
        self.default_config.update({'结束后': '无', '关机延迟秒': 60})
        self._option_keys = []


class App_MouseSensitivityChecker(AppTaskBase):
    app_id = 'mouse_sensitivity_checker'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '▶️ 鼠标灵敏度检测'
        self.description = '运行一条龙应用：鼠标灵敏度检测'
        self.default_config.update({'结束后': '无', '关机延迟秒': 60})
        self._option_keys = []


class App_PredefinedTeamChecker(AppTaskBase):
    app_id = 'predefined_team_checker'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '▶️ 预备编队角色识别'
        self.description = '运行一条龙应用：预备编队角色识别'
        self.default_config.update({'结束后': '无', '关机延迟秒': 60})
        self._option_keys = []


class App_LostVoid(AppTaskBase):
    app_id = 'lost_void'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '🌌 迷失之地'
        self.description = '运行一条龙应用：迷失之地'
        self.default_config.update({
            'challenge_config': '默认-成就模式',
            'daily_plan_times': 5,
            'extra_task': '完成悬赏委托',
            'mission_name': '战线肃清',
            'weekly_plan_times': 2,
            'matrix_team_mode': '沿用挑战配置',
            'matrix_agent_1': 'unknown',
            'matrix_agent_2': 'unknown',
            'matrix_agent_3': 'unknown',
            '结束后': '无',
            '关机延迟秒': 60,
        })
        self.config_type.update({
            'extra_task': {'type': 'drop_down', 'options': ['完成悬赏委托', '刷满业绩点', '刷满周期奖励', '完成周计划次数']},
            'matrix_team_mode': {'type': 'drop_down', 'options': ['沿用挑战配置', '自定义编队']},
        })
        self._option_keys = ['challenge_config', 'daily_plan_times', 'extra_task', 'mission_name', 'weekly_plan_times', 'matrix_team_mode', 'matrix_agent_1', 'matrix_agent_2', 'matrix_agent_3']


class App_WitheredDomain(AppTaskBase):
    app_id = 'withered_domain'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '🕳️ 枯萎之都'
        self.description = '运行一条龙应用：枯萎之都'
        self.default_config.update({
            'challenge_config': '默认-专属空洞-艾莲',
            'daily_plan_times': 99,
            'extra_exit': '通关',
            'extra_task': '刷满周期奖励',
            'mission_name': '旧都列车-内部',
            'weekly_plan_times': 2,
            '结束后': '无',
            '关机延迟秒': 60,
        })
        self.config_type.update({
            'extra_exit': {'type': 'drop_down', 'options': ['通关', '2层业绩后退出', '3层业绩后退出']},
            'extra_task': {'type': 'drop_down', 'options': ['不进行', '刷满业绩点', '刷满周期奖励']},
        })
        self._option_keys = ['challenge_config', 'daily_plan_times', 'extra_exit', 'extra_task', 'mission_name', 'weekly_plan_times']


class App_HouHouBakery(AppTaskBase):
    app_id = 'hou_hou_bakery'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '🍞 吼吼饼铺'
        self.description = '运行一条龙应用：吼吼饼铺'
        self.default_config.update({'结束后': '无', '关机延迟秒': 60})
        self._option_keys = []


class App_IntelBoard(AppTaskBase):
    app_id = 'intel_board'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '📋 情报板'
        self.description = '运行一条龙应用：情报板'
        self.default_config.update({
            'auto_battle_config': '全配队通用',
            'exp_grind_mode': False,
            'predefined_team_idx': -1,
            '结束后': '无',
            '关机延迟秒': 60,
        })
        self._option_keys = ['auto_battle_config', 'exp_grind_mode', 'predefined_team_idx']


class App_LifeOnLine(AppTaskBase):
    app_id = 'life_on_line'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '🎮 真·拿命验收'
        self.description = '运行一条龙应用：真·拿命验收'
        self.default_config.update({
            'daily_plan_times': 20,
            'predefined_team_idx': -1,
            '结束后': '无',
            '关机延迟秒': 60,
        })
        self._option_keys = ['daily_plan_times', 'predefined_team_idx']


class App_Notify(AppTaskBase):
    app_id = 'notify'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '📢 通知'
        self.description = '运行一条龙应用：通知'
        self.default_config.update({'结束后': '无', '关机延迟秒': 60})
        self._option_keys = []


class App_NotoriousHunt(AppTaskBase):
    app_id = 'notorious_hunt'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '🐲 恶名狩猎'
        self.description = '运行一条龙应用：恶名狩猎'
        self.default_config.update({
            'plan_list': '',
            'loop': True,
            'weekly_challenge_start_weekday': 1,
            '结束后': '无',
            '关机延迟秒': 60,
        })
        self._option_keys = ['loop', 'weekly_challenge_start_weekday']


class App_RandomPlay(AppTaskBase):
    app_id = 'random_play'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '🎬 录像店营业'
        self.description = '运行一条龙应用：录像店营业'
        self.default_config.update({
            'agent_name_1': '随机',
            'agent_name_2': '随机',
            'transport_point': '录像店 - 柜台',
            '结束后': '无',
            '关机延迟秒': 60,
        })
        self.config_type.update({
            'transport_point': {'type': 'drop_down', 'options': ['录像店 - 柜台', '澄辉坪 - 录像店营业点', '布亚斯特城区 - 录像店营业点']},
        })
        self._option_keys = ['agent_name_1', 'agent_name_2', 'transport_point']


class App_RedemptionCode(AppTaskBase):
    app_id = 'redemption_code'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '🎫 兑换码'
        self.description = '运行一条龙应用：兑换码'
        self.default_config.update({'结束后': '无', '关机延迟秒': 60})
        self._option_keys = []


class App_RiduWeekly(AppTaskBase):
    app_id = 'ridu_weekly'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '📈 丽都周纪 (领奖励)'
        self.description = '运行一条龙应用：丽都周纪 (领奖励)'
        self.default_config.update({'结束后': '无', '关机延迟秒': 60})
        self._option_keys = []


class App_ScratchCard(AppTaskBase):
    app_id = 'scratch_card'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '🎟️ 刮刮卡'
        self.description = '运行一条龙应用：刮刮卡'
        self.default_config.update({'结束后': '无', '关机延迟秒': 60})
        self._option_keys = []


class App_ShiyuDefense(AppTaskBase):
    app_id = 'shiyu_defense'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '▶️ 式舆防卫战'
        self.description = '运行一条龙应用：式舆防卫战'
        self.default_config.update({
            'critical_max_node_idx': 7,
            '结束后': '无',
            '关机延迟秒': 60,
        })
        self._option_keys = ['critical_max_node_idx']


class App_SuibianTemple(AppTaskBase):
    app_id = 'suibian_temple'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '🏪 随便观'
        self.description = '运行一条龙应用：随便观'
        self.default_config.update({
            'adventure_duration': 'HOUR_20',
            'adventure_mission_1': 'RESEARCH_3_4',
            'adventure_mission_2': 'RESEARCH_2_4',
            'adventure_mission_3': 'RESEARCH_1_4',
            'adventure_mission_4': 'COMMUNITY_3_4',
            'auto_manage_enabled': True,
            'boo_box_adventure_price': 'S4',
            'boo_box_craft_price': 'S4',
            'boo_box_purchase_enabled': False,
            'boo_box_sell_price': 'S4',
            'craft_drag_times': 10,
            'good_goods_purchase_enabled': False,
            'pawnshop_crest_enabled': True,
            'pawnshop_crest_priority': '[\n "BANGBOO_SYSTEM_WIDGET",\n "DENNY"\n]',
            'pawnshop_crest_unlimited_denny_enabled': False,
            'pawnshop_omnicoin_enabled': True,
            'pawnshop_omnicoin_priority': '[\n "HIFI_MASTER_COPY",\n "SENIOR_INVESTIGATOR_LOG",\n "W_ENGINE_ENERGY_MODULE",\n "ETHER_PLATING_AGENT",\n "PREPAID_POWER_CARD"\n]',
            'yum_cha_sin': True,
            'yum_cha_sin_period_refresh': True,
            '结束后': '无',
            '关机延迟秒': 60,
        })
        self.config_type.update({
            'pawnshop_crest_priority': {'type': 'text_edit'},
            'pawnshop_omnicoin_priority': {'type': 'text_edit'},
        })
        self._option_keys = ['adventure_duration', 'adventure_mission_1', 'adventure_mission_2', 'adventure_mission_3', 'adventure_mission_4', 'auto_manage_enabled', 'boo_box_adventure_price', 'boo_box_craft_price', 'boo_box_purchase_enabled', 'boo_box_sell_price', 'craft_drag_times', 'good_goods_purchase_enabled', 'pawnshop_crest_enabled', 'pawnshop_crest_priority', 'pawnshop_crest_unlimited_denny_enabled', 'pawnshop_omnicoin_enabled', 'pawnshop_omnicoin_priority', 'yum_cha_sin', 'yum_cha_sin_period_refresh']


class App_TrigramsCollection(AppTaskBase):
    app_id = 'trigrams_collection'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '🔮 卦象集录'
        self.description = '运行一条龙应用：卦象集录'
        self.default_config.update({'结束后': '无', '关机延迟秒': 60})
        self._option_keys = []


class App_WorldPatrol(AppTaskBase):
    app_id = 'world_patrol'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '🌍 锄大地'
        self.description = '运行一条龙应用：锄大地'
        self.default_config.update({
            'auto_battle': '全配队通用',
            'daily_loop_count': 1,
            'loop_interval_seconds': 1800,
            'route_list': '',
            'route_retry_action': 'skip_on_stuck_again',
            'route_retry_times': 1,
            'ui_disappear_action': 'silent_fail',
            'ui_disappear_seconds': 10,
            '结束后': '无',
            '关机延迟秒': 60,
        })
        self._option_keys = ['auto_battle', 'daily_loop_count', 'loop_interval_seconds', 'route_list', 'route_retry_action', 'route_retry_times', 'ui_disappear_action', 'ui_disappear_seconds']
