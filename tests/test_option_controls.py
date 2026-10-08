"""使用真实 Qt 控件验证中文显示、存储类型和条件控件。"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import json
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication
from qfluentwidgets import FluentIcon
from ok import og
from ok.ui.qt.tasks.ConfigCard import ConfigCard
from ok.util.config import Config
from src.tasks.app_option_ui import OPTION_LABELS, configure_app_options, option_schema
from zzz_od.application.app_options_data import APP_OPTIONS

_QT_APP = None


def test_global_recognition_settings_accept_strict_qt_translation(monkeypatch, tmp_path):
    global _QT_APP
    from src.inference import recognition_config
    from src.tasks.option_widgets import install_option_widgets
    from ok.ui.qt.settings.GlobalConfigCard import GlobalConfigCard
    _QT_APP = QApplication.instance() or QApplication([])
    app = SimpleNamespace(tr=lambda text: _QT_APP.translate('ok', text))
    monkeypatch.setattr(og, 'app', app)
    monkeypatch.setattr(og, 'config', {'gui_title': 'ok-zzz'})
    install_option_widgets()
    settings = Config(recognition_config.name, recognition_config.default_config, folder=str(tmp_path))
    card = GlobalConfigCard(settings, recognition_config)
    try:
        box = card.config_widget_by_key['识别帧率上限'].combo_box
        assert box.currentText() == '30 帧/秒'
        box.setCurrentText('20 帧/秒')
        assert settings['识别帧率上限'] == 20
        box.setCurrentText('60 帧/秒')
        assert settings['识别帧率上限'] == 60
    finally:
        card.close()
        card.deleteLater()
        _QT_APP.processEvents()


@pytest.fixture
def ui_task(monkeypatch, tmp_path):
    global _QT_APP
    _QT_APP = QApplication.instance() or QApplication([])
    app = SimpleNamespace(tr=lambda text: text)  # 翻译未加载也必须显示中文
    monkeypatch.setattr(og, 'app', app)
    monkeypatch.setattr(og, 'config', {'gui_title': 'ok-zzz'})
    cards = []

    def create(cls):
        task = cls(executor=SimpleNamespace(scene=None), app=app)
        task.config = Config(cls.__name__, task.default_config, folder=str(tmp_path), validator=task.validate)
        configure_app_options(task)
        card = ConfigCard(task, task.name, task.config, task.description, task.default_config,
                          task.config_description, task.config_type, FluentIcon.INFO)
        cards.append(card)
        return task, card

    yield create
    for card in cards:
        card.close()
        card.deleteLater()
    _QT_APP.processEvents()


def test_all_application_parameters_have_chinese_titles(ui_task):
    from src.tasks import app_tasks
    for metadata in APP_OPTIONS:
        if metadata['app_id'] == 'one_dragon' or 'error' in metadata:
            continue
        cls = next(cls for cls in vars(app_tasks).values()
                   if isinstance(cls, type) and getattr(cls, 'app_id', None) == metadata['app_id'])
        task, card = ui_task(cls)
        assert card.reset_config.text() == '恢复默认设置'
        for option in metadata.get('options', []):
            key = option['key']
            assert key in OPTION_LABELS, (task.app_id, key)
            assert card.config_widget_by_key[key].title.text() == OPTION_LABELS[key]
            if option['type'] == 'enum' or option_schema(task.app_id, key) is not None:
                widget = card.config_widget_by_key[key]
                assert hasattr(widget, 'combo_box') or hasattr(widget, 'boxes'), (task.app_id, key)


def test_chinese_enum_choice_saves_original_internal_value(ui_task):
    from src.tasks.app_tasks import App_SuibianTemple
    task, card = ui_task(App_SuibianTemple)
    box = card.config_widget_by_key['adventure_duration'].combo_box
    assert box.currentText() == '20小时'
    box.setCurrentText('6小时')
    assert task.config['adventure_duration'] == 'HOUR_6'
    mission = card.config_widget_by_key['adventure_mission_1'].combo_box
    mission.setCurrentText('制造区1-1')
    assert task.config['adventure_mission_1'] == 'CRAFT_1_1'
    priority = card.config_widget_by_key['pawnshop_omnicoin_priority']
    priority.boxes[0].setCurrentText('不兑换')
    assert json.loads(task.config['pawnshop_omnicoin_priority'])[0] == 'SENIOR_INVESTIGATOR_LOG'
    card.reset_clicked()
    assert box.currentText() == '20小时'
    assert priority.boxes[0].currentText() == '高保真母盘'


def test_numeric_choice_preserves_integer_and_legacy_custom_values(ui_task):
    from src.tasks.app_tasks import App_NotoriousHunt, App_WorldPatrol, App_IntelBoard
    task, card = ui_task(App_NotoriousHunt)
    box = card.config_widget_by_key['weekly_challenge_start_weekday'].combo_box
    box.setCurrentText('周三')
    assert task.config['weekly_challenge_start_weekday'] == 3
    assert isinstance(task.config['weekly_challenge_start_weekday'], int)
    team, team_card = ui_task(App_IntelBoard)
    team_box = team_card.config_widget_by_key['predefined_team_idx'].combo_box
    team_box.setCurrentText('预备编队 2')
    assert team.config['predefined_team_idx'] == 1
    team_card.reset_clicked()
    assert team_box.currentText() == '不指定预备编队'
    task, _card = ui_task(App_WorldPatrol)
    task.config['auto_battle'] = '自定义战斗模板'
    configure_app_options(task)
    assert '自定义战斗模板' in task.config_type['auto_battle']['options']
    assert '中央制造区' in task.config_type['route_list']['options']


def test_matrix_custom_team_controls_and_ids(ui_task):
    from src.tasks.app_tasks import App_LostVoid
    task, card = ui_task(App_LostVoid)
    card.setExpand(True)
    mode = card.config_widget_by_key['matrix_team_mode'].combo_box
    role = card.config_widget_by_key['matrix_agent_1']
    assert role.isHidden()
    mode.setCurrentText('自定义编队')
    assert not role.isHidden()
    role.combo_box.setCurrentText('安比')
    assert task.config['matrix_agent_1'] == 'anby'
    mode.setCurrentText('沿用挑战配置')
    assert role.isHidden()


def test_generator_recognizes_stored_enum_names():
    from tools.gen_app_tasks import find_enum_choices
    from zzz_od.application.suibian_temple import suibian_temple_config as temple
    assert 'HOUR_6' in find_enum_choices(temple, 'HOUR_20')
    assert 'S1' in find_enum_choices(temple, 'S4')


def test_invalid_matrix_options_do_not_save_or_activate_game(ui_task, monkeypatch):
    from unittest.mock import Mock
    from src.tasks.app_tasks import App_LostVoid
    task, _card = ui_task(App_LostVoid)
    task.config.update(mission_name='矩阵行动', matrix_team_mode='自定义编队',
                       matrix_agent_1='anby', matrix_agent_2='anby')
    saved = SimpleNamespace(data={}, update=Mock(), save=Mock())
    ctx = SimpleNamespace(current_instance_idx=0, init_for_application=Mock(),
                          run_context=SimpleNamespace(get_config=Mock(return_value=saved)))
    monkeypatch.setattr(og, 'my_app', SimpleNamespace(context=ctx))
    task.log_error = Mock()
    with pytest.raises(ValueError, match='不能重复'):
        task.run()
    saved.update.assert_not_called()
    saved.save.assert_not_called()
    ctx.init_for_application.assert_not_called()
