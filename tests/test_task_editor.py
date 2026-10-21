"""Real configuration editors, persistent engine plans and private Win32 APIs."""
import ctypes
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QApplication, QScrollArea
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QDropEvent
from ok import og
from ok.util.config import Config
from ok.ui.qt.tasks.ConfigCard import ConfigCard
from qfluentwidgets import FluentIcon, PushButton
from src.tasks.option_widgets import install_option_widgets
from src.tasks.app_tasks import App_ChargePlan, App_NotoriousHunt
from src.tasks.daily_task import OneDragonDailyTask
from src.tasks.plan_widgets import ChargePlanWidget, AppSettingsDialog, parse_charge_plans

_APP = None


@pytest.fixture
def editor(tmp_path, monkeypatch):
    global _APP
    _APP = QApplication.instance() or QApplication([])
    install_option_widgets()
    monkeypatch.setattr(og, 'app', SimpleNamespace(tr=lambda text: text))
    monkeypatch.setattr(og, 'config', {'gui_title': 'ok-zzz'})
    monkeypatch.setattr(og, 'my_app', None)
    executor = SimpleNamespace(scene=None, get_all_tasks=lambda: [], current_task=None,
        onetime_tasks=[], trigger_tasks=[])
    monkeypatch.setattr(og, 'executor', executor)
    def build(cls):
        task=cls(executor=executor,app=og.app)
        task.config=Config(cls.__name__,task.default_config,folder=str(tmp_path),validator=task.validate)
        task.post_init()
        card=ConfigCard(task,task.name,task.config,task.description,task.default_config,
            task.config_description,task.config_type,FluentIcon.INFO)
        return task,card
    yield build
    _APP.processEvents()


def test_category_switch_shows_split_counts_only_for_double_capable_plans(editor):
    task, card = editor(App_ChargePlan)
    widget = card.config_widget_by_key['plan_list']
    widget.add_plan()
    widget.editors[0]['plan_times'].setValue(4)
    assert {'double_times', 'single_times'}.isdisjoint(widget.editors[0])
    category = widget.editors[0]['category_name']
    category.setCurrentIndex(category.findData('专业挑战室'))
    _APP.processEvents()
    controls = widget.editors[0]
    assert 'plan_times' not in controls
    assert (controls['double_times'].value(), controls['single_times'].value()) == (0, 4)
    controls['double_times'].setValue(2)
    saved = json.loads(task.config['plan_list'])[0]
    assert (saved['double_times'], saved['single_times'], saved['plan_times']) == (2, 4, 6)
    controls['single_times'].setValue(0)
    controls['double_times'].setValue(0)
    assert widget.error_label.text()
    assert json.loads(task.config['plan_list'])[0]['plan_times'] == 2
    controls['single_times'].setValue(1)
    assert not widget.error_label.text()
    category = widget.editors[0]['category_name']
    category.setCurrentIndex(category.findData('区域巡防'))
    _APP.processEvents()
    controls = widget.editors[0]
    assert {'double_times', 'single_times'}.isdisjoint(controls)
    saved = json.loads(task.config['plan_list'])[0]
    assert (saved['double_times'], saved['plan_times']) == (0, 1)
    card.close()


def test_legacy_disabled_double_plan_runs_its_total_as_single():
    rows = parse_charge_plans([{'category_name': '专业挑战室', 'mission_type_name': '「征服者」',
        'mission_name': None, 'plan_times': 8, 'run_times': 1, 'double_reward_enabled': False,
        'double_times': 2, 'single_times': 6, 'plan_id': 'kept'}])
    assert (rows[0]['double_times'], rows[0]['single_times'], rows[0]['plan_times']) == (0, 8, 8)
    assert (rows[0]['run_times'], rows[0]['plan_id']) == (1, 'kept')
    assert 'double_reward_enabled' not in rows[0]


def test_charge_rows_edit_add_reorder_and_preserve_identity(editor):
    task,card=editor(App_ChargePlan)
    widget=card.config_widget_by_key['plan_list']
    assert isinstance(widget,ChargePlanWidget)
    widget.add_button.click()
    first=json.loads(task.config['plan_list'])[0]
    widget.editors[0]['mission_name'].setCurrentIndex(widget.editors[0]['mission_name'].findData('调查专项'))
    widget.editors[0]['plan_times'].setValue(4)
    widget.add_button.click()
    second=json.loads(task.config['plan_list'])[1]
    widget.move_plan(1,-1)
    saved=json.loads(task.config['plan_list'])
    assert [row['plan_id'] for row in saved]==[second['plan_id'],first['plan_id']]
    assert saved[1]['plan_times']==4
    widget.remove_plan(0)
    assert json.loads(task.config['plan_list'])[0]['plan_id']==first['plan_id']
    assert widget.editors[0]['plan_times'].value() == 4
    card.close()


def test_daily_editor_order_and_toggle_reach_group_yaml(editor,tmp_path,monkeypatch):
    from onedragon.utils import os_utils
    from onedragon.base.operation.application.application_group_config import ApplicationGroupConfig
    from zzz_od.application.app_options_data import APP_OPTIONS
    task,card=editor(OneDragonDailyTask)
    widget=card.config_widget_by_key['启用应用']
    assert '执行顺序' not in card.config_widget_by_key
    names=task._all_app_names()
    target=names.index('体力刷本')
    widget.move(target,-target)
    assert widget.order[0]=='体力刷本'
    widget.checks[0].setChecked(False)
    assert '体力刷本' not in task.config['启用应用']
    widget.checks[0].setChecked(True)
    monkeypatch.setattr(os_utils,'get_work_dir',lambda:str(tmp_path))
    group=ApplicationGroupConfig(0,'one_dragon')
    group.update_full_app_list([app['app_id'] for app in APP_OPTIONS if app.get('default_group')])
    ctx=SimpleNamespace(current_instance_idx=0,run_context=SimpleNamespace(get_group_config=lambda **_:group,
        get_group_app_ids=lambda **_:[(item.app_id,item.enabled) for item in group.app_list]))
    monkeypatch.setattr(og,'my_app',SimpleNamespace(context=ctx))
    task._sync_group_config()
    reloaded=ApplicationGroupConfig(0,'one_dragon')
    assert reloaded._all_apps[0].app_id=='charge_plan' and reloaded._all_apps[0].enabled
    assert task.group_name=='一条龙日常'
    card.close()


def test_daily_rows_offer_edit_only_for_apps_with_settings(editor):
    task, card = editor(OneDragonDailyTask)
    widget = card.config_widget_by_key['启用应用']
    def edit_button(name):
        cell = widget.table.cellWidget(widget.order.index(name), 3)
        return None if cell is None else cell.findChild(PushButton)
    for name in ('邮件', '活跃度奖励', '丽都城募', '丽都周纪 (领奖励)', '兑换码', '通知'):
        assert edit_button(name) is None, name  # Nothing in the dialog would affect the daily.
    for name in ('每日签到', '录像店营业', '咖啡店', '体力刷本', '恶名狩猎', '迷失之地'):
        assert edit_button(name) is not None, name
    first_plain = widget.order.index('邮件')
    widget.move(first_plain, -first_plain)  # Rows are rebuilt on reorder; the cell must stay empty.
    assert widget.order[0] == '邮件' and widget.table.cellWidget(0, 3) is None
    assert edit_button('体力刷本') is not None
    card.close()


def test_daily_drop_moves_whole_row_and_preserves_enabled_state(editor, tmp_path):
    task, card = editor(OneDragonDailyTask)
    widget = card.config_widget_by_key['启用应用']
    original = widget.order[:]
    enabled = task.config['启用应用'][:]
    table = widget.table
    table.resize(700, 440)
    table.show()
    _APP.processEvents()
    # Drop the first task below the third task, through the actual drop handler.
    rect = table.visualRect(table.model().index(2, 0))
    mime = table.row_mime(0)  # QDropEvent borrows this QObject; keep it alive.
    event = QDropEvent(QPointF(rect.center().x(), rect.bottom()-1), Qt.MoveAction,
                       mime, Qt.LeftButton, Qt.NoModifier)
    table.dropEvent(event)
    assert event.isAccepted()
    assert widget.order[:3] == [original[1], original[2], original[0]]
    assert task.config['启用应用'] == enabled
    reloaded = Config(type(task).__name__, task.default_config, folder=str(tmp_path))
    assert reloaded['执行顺序'] == widget.order
    assert table.item(2, 2).data(Qt.UserRole) == original[0]
    assert widget.checks[2].isChecked() == (original[0] in enabled)
    card.close()


def test_daily_task_card_starts_expanded(editor):
    from ok.ui.qt.tasks.TaskCard import TaskCard
    task, form = editor(OneDragonDailyTask)
    task.executor.waiting_for_task = lambda task: None
    task_card = TaskCard(task, True)
    assert task_card.isExpand
    task_card.dispose()
    task_card.close()
    form.close()


def test_charge_dropdown_dependencies_save_game_values_and_keep_progress(editor, ctx):
    from zzz_od.application.charge_plan.charge_plan_config import ChargePlanConfig, ChargePlanItem
    task, card = editor(App_ChargePlan)
    widget = card.config_widget_by_key['plan_list']
    row = ChargePlanItem(plan_times=5, run_times=2).to_dict()
    task.config['plan_list'] = json.dumps([row], ensure_ascii=False)
    widget.update_value()
    controls = widget.editors[0]
    assert controls['mission_name'].currentText() == '代理人经验'
    assert controls['mission_name'].currentData() == '调查专项'
    controls['category_name'].setCurrentIndex(controls['category_name'].findData('区域巡防'))
    saved = json.loads(task.config['plan_list'])[0]
    assert saved['mission_type_name'] == '怪兽与怪客' and saved['mission_name'] is None
    assert saved['plan_id'] == row['plan_id'] and saved['run_times'] == 2
    assert ChargePlanConfig.validate_item(ctx, ChargePlanItem(**saved)) is None
    assert '摇摆爵士' in controls['mission_type_name'].currentText()
    controls['category_name'].setCurrentIndex(controls['category_name'].findData('实战模拟室'))
    controls['mission_type_name'].setCurrentIndex(controls['mission_type_name'].findData('代理人技能'))
    assert controls['mission_name'].currentData() == '刚性测试'
    controls['mission_name'].setCurrentIndex(controls['mission_name'].findData('共鸣测试'))
    controls['predefined_team_idx'].setCurrentIndex(controls['predefined_team_idx'].findData(2))
    saved = json.loads(task.config['plan_list'])[0]
    assert saved['mission_name'] == '共鸣测试' and saved['predefined_team_idx'] == 2
    assert ChargePlanConfig.validate_item(ctx, ChargePlanItem(**saved)) is None
    controls['category_name'].setCurrentIndex(controls['category_name'].findData('合成电池'))
    saved = json.loads(task.config['plan_list'])[0]
    assert saved['mission_type_name'] == '' and saved['mission_name'] is None
    assert not controls['mission_type_name'].isEnabled() and not controls['mission_name'].isEnabled()
    assert ChargePlanConfig.validate_item(ctx, ChargePlanItem(**saved)) is None
    card.close()


def test_many_charge_plans_keep_small_dialog_actions_reachable(editor):
    task, card = editor(App_ChargePlan)
    dialog = AppSettingsDialog(task)
    dialog.resize(760, 420)
    dialog.show()
    widget = dialog.form.config_widget_by_key['plan_list']
    for _ in range(8):
        widget.add_button.click()
    _APP.processEvents()
    assert widget.scroll.verticalScrollBar().maximum() > 0
    widget.scroll.ensureWidgetVisible(widget.editors[-1]['plan_times'])
    _APP.processEvents()
    widget.editors[-1]['plan_times'].setValue(7)
    assert json.loads(dialog.draft['plan_list'])[-1]['plan_times'] == 7
    widget.remove_plan(0)
    _APP.processEvents()
    assert len(json.loads(dialog.draft['plan_list'])) == 7
    assert widget.scroll.geometry().bottom() < widget.add_button.geometry().top()
    outer_scroll = next(scroll for scroll in dialog.findChildren(QScrollArea)
                        if scroll.widget() is dialog.form)
    outer_scroll.ensureWidgetVisible(dialog.form.reset_config)
    _APP.processEvents()
    reset = dialog.form.reset_config
    assert outer_scroll.viewport().rect().contains(
        reset.mapTo(outer_scroll.viewport(), reset.rect().center()))
    save = next(button for button in dialog.findChildren(PushButton)
                if button.text() == '保存设置')
    assert dialog.rect().contains(save.mapTo(dialog, save.rect().center()))
    dialog.reject()
    dialog.close()
    card.close()


@pytest.mark.skipif(bool(os.environ.get('CI')), reason=(
    'Hosted CI runners intermittently keep the populated card height after deferred row deletion; '
    'passes on desktop sessions, where it is still checked.'))
def test_charge_card_refreshes_height_after_empty_plan_add_and_remove(editor):
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    task, card = editor(App_ChargePlan)
    window = QScrollArea()
    window.setWidgetResizable(True)
    window.setWidget(card)
    window.resize(760, 420)
    window.show()
    card.setExpand(True)
    QTest.qWait(250)
    widget = card.config_widget_by_key['plan_list']
    empty_height = card.height()
    for _ in range(8):
        widget.add_button.click()
    _APP.processEvents()
    assert card.height() > empty_height
    assert widget.scroll.verticalScrollBar().maximum() > 0
    widget.editors[-1]['plan_times'].setValue(9)
    assert json.loads(task.config['plan_list'])[-1]['plan_times'] == 9
    assert widget.scroll.geometry().bottom() < widget.add_button.geometry().top()
    reset = card.reset_config
    window.ensureWidgetVisible(reset)
    _APP.processEvents()
    assert window.viewport().rect().contains(
        reset.mapTo(window.viewport(), reset.rect().center()))
    assert reset.mapTo(card.view, QPoint(0, reset.height())).y() <= card.view.height()
    while widget.rows:
        widget.remove_plan(0)
    # The card animates back; a slow runner needs more than one event pass.
    for _ in range(40):
        _APP.processEvents()
        if card.height() < empty_height + 20:
            break
        QTest.qWait(50)
    assert card.height() < empty_height + 20
    assert json.loads(task.config['plan_list']) == []
    window.close()
    card.close()


def test_charge_plan_save_reloads_engine_list_and_keeps_run_counts(editor,tmp_path,monkeypatch,ctx):
    from onedragon.utils import os_utils
    from zzz_od.application.charge_plan.charge_plan_config import ChargePlanConfig,ChargePlanItem
    task,card=editor(App_ChargePlan)
    compendium=ctx.compendium_service
    monkeypatch.setattr(os_utils,'get_work_dir',lambda:str(tmp_path))
    engine=ChargePlanConfig(0,'one_dragon')
    original=ChargePlanItem(category_name='专业挑战室',mission_type_name='「征服者」',mission_name=None,plan_times=5,run_times=2)
    engine.add_plan(original)
    edited=original.to_dict()
    edited.update(run_times=0, double_times=3, single_times=3)
    task.config['plan_list']=json.dumps([edited],ensure_ascii=False)
    fake=SimpleNamespace(current_instance_idx=0,compendium_service=compendium,
        run_context=SimpleNamespace(get_config=lambda *a,**k:engine))
    monkeypatch.setattr(og,'my_app',SimpleNamespace(context=fake))
    task.apply_options()
    reloaded=ChargePlanConfig(0,'one_dragon')
    assert len(reloaded.plan_list)==1
    assert reloaded.plan_list[0].plan_id==original.plan_id
    plan = reloaded.plan_list[0]
    assert plan.plan_times == 6 and plan.run_times == 2
    assert (plan.double_times, plan.single_times) == (3, 3)
    assert plan.use_double_reward
    engine.add_plan_run_times(engine.plan_list[0])
    task.apply_options()
    reloaded = ChargePlanConfig(0, 'one_dragon')
    assert reloaded.plan_list[0].run_times == 3
    assert not reloaded.plan_list[0].use_double_reward
    card.close()


def test_cancel_settings_does_not_modify_saved_task_config(editor):
    task,card=editor(App_ChargePlan)
    original=dict(task.config)
    dialog=AppSettingsDialog(task)
    dialog.form.config_widget_by_key['plan_list'].add_button.click()
    assert dialog.draft['plan_list']!=original['plan_list']
    dialog.reject()
    assert dict(task.config)==original
    dialog.close()
    card.close()


@pytest.mark.parametrize('value', ['bad json', '[null]', '[{"plan_times":0}]',
    '[{"predefined_team_idx":20}]', '[{"card_num":"8"}]', '[{"unknown_key":1}]'])
def test_invalid_plan_never_reaches_engine(value):
    with pytest.raises((ValueError,TypeError)):
        parse_charge_plans(value)


@pytest.mark.parametrize('cls', [App_ChargePlan, App_NotoriousHunt])
def test_edited_plans_survive_config_reload(editor, cls):
    task, card = editor(cls)
    assert task.config['plan_list'] == ''  # not yet loaded from the engine: apply keeps engine plans
    widget = card.config_widget_by_key['plan_list']
    widget.add_button.click()
    if cls is App_ChargePlan:
        category = widget.editors[0]['category_name']
        category.setCurrentIndex(category.findData('专业挑战室'))
        _APP.processEvents()
        controls = widget.editors[0]
        controls['double_times'].setValue(2)
        controls['single_times'].setValue(4)
    saved = task.config['plan_list']
    assert len(json.loads(saved)) == 1
    card.close()
    reloaded, card = editor(cls)
    assert reloaded.config['plan_list'] == saved
    if cls is App_ChargePlan:
        controls = card.config_widget_by_key['plan_list'].editors[0]
        assert (controls['double_times'].value(), controls['single_times'].value()) == (2, 4)
        assert json.loads(saved)[0]['plan_times'] == 6
    card.close()


def test_notorious_hunt_plans_use_hunt_targets_without_mission_names(editor):
    task, card = editor(App_NotoriousHunt)
    widget = card.config_widget_by_key['plan_list']
    assert isinstance(widget, ChargePlanWidget) and widget.hunt
    assert widget.title.text() == '狩猎计划' and widget.add_button.text() == '添加狩猎计划'
    widget.add_button.click()
    row = json.loads(task.config['plan_list'])[0]
    assert (row['tab_name'], row['category_name'], row['mission_name']) == ('训练', '恶名狩猎', None)
    controls = widget.editors[0]
    assert 'category_name' not in controls and 'mission_name' not in controls
    assert controls['mission_type_name'].findData('代理人方案培养') >= 0
    controls['mission_type_name'].setCurrentIndex(controls['mission_type_name'].findData('彷徨猎手'))
    controls['level'].setCurrentIndex(controls['level'].findData('等级Lv.65'))
    controls['notorious_hunt_buff_num'].setValue(3)
    saved = json.loads(task.config['plan_list'])[0]
    assert saved['mission_type_name'] == '彷徨猎手' and saved['mission_name'] is None
    assert saved['level'] == '等级Lv.65' and saved['notorious_hunt_buff_num'] == 3
    assert saved['plan_id'] == row['plan_id']
    card.close()


def test_notorious_hunt_save_reaches_engine_and_keeps_run_counts(editor, tmp_path, monkeypatch, ctx):
    from onedragon.utils import os_utils
    from zzz_od.application.charge_plan.charge_plan_config import ChargePlanItem
    from zzz_od.application.notorious_hunt.notorious_hunt_config import NotoriousHuntConfig
    task, card = editor(App_NotoriousHunt)
    monkeypatch.setattr(os_utils, 'get_work_dir', lambda: str(tmp_path))
    engine = NotoriousHuntConfig(0, 'one_dragon')
    original = ChargePlanItem(category_name='恶名狩猎', mission_type_name='初生死路屠夫', mission_name=None,
                              plan_times=3, run_times=2)
    engine.add_plan(original)
    edited = original.to_dict()
    edited.update(plan_times=4, run_times=0, notorious_hunt_buff_num=2)
    fake = SimpleNamespace(current_instance_idx=0, compendium_service=ctx.compendium_service,
                           run_context=SimpleNamespace(get_config=lambda *a, **k: engine))
    monkeypatch.setattr(og, 'my_app', SimpleNamespace(context=fake))
    task.config['plan_list'] = json.dumps([edited], ensure_ascii=False)
    task.apply_options()
    reloaded = NotoriousHuntConfig(0, 'one_dragon')
    assert [plan.plan_id for plan in reloaded.plan_list] == [original.plan_id]
    plan = reloaded.plan_list[0]
    assert (plan.plan_times, plan.run_times, plan.notorious_hunt_buff_num) == (4, 2, 2)
    for bad in ({'category_name': '实战模拟室'}, {'mission_type_name': '不存在的目标'}):
        task.config['plan_list'] = json.dumps([{**edited, **bad}], ensure_ascii=False)
        with pytest.raises(ValueError):
            task.apply_options()
    assert NotoriousHuntConfig(0, 'one_dragon').plan_list[0].plan_times == 4
    card.close()


def test_private_overlay_dll_can_coexist_with_window_and_cursor_readers():
    import win32gui
    import pyautogui
    from pygetwindow import Win32Window
    from src.controls.win32_compat import install_win32_compat
    install_win32_compat()
    from ok.ui.overlay import win32_gdi
    assert win32_gdi.user32 is not ctypes.windll.user32
    from onedragon.base.controller.pc_game_window import PcGameWindow
    hwnd=win32gui.GetDesktopWindow()
    window=PcGameWindow()
    window.window_provider=lambda:hwnd
    for _ in range(5):
        assert Win32Window(hwnd)._hWnd==hwnd
        assert window.win_rect is not None
        assert isinstance(window.is_win_active,bool)
        assert len(pyautogui.position())==2


def test_engine_progress_reaches_framework_log(caplog):
    import logging
    from onedragon.utils.log_utils import log
    from src.runtime.logging_bridge import install_runtime_logging
    install_runtime_logging()
    with caplog.at_level(logging.INFO,logger='ok'):
        log.info('测试路线节点完成 %s','编辑器回归')
    assert any(record.name=='ok' and '测试路线节点完成 编辑器回归' in record.message for record in caplog.records)


def test_unlimited_recording_does_not_stop_after_old_limit(tmp_path):
    from src.diagnostics.recorder import DiagnosticRecorder
    rec=DiagnosticRecorder()
    rec.start(tmp_path,mode='截图',duration=0)
    try:
        with rec._lock:
            rec._session['start']-=601
        time.sleep(.08)
        assert rec.active and rec.status['duration']==0 and rec.status['elapsed']>600
    finally:
        rec.stop(wait=True)
    assert rec.status['state']=='已保存'


def test_large_recording_rotates_video_without_stopping(tmp_path,monkeypatch):
    import cv2
    from src.diagnostics import recorder as diagnostics
    monkeypatch.setattr(diagnostics,'MAX_VIDEO_BYTES',20)
    rec=diagnostics.DiagnosticRecorder()
    folder=Path(rec.start(tmp_path,duration=0,mode='视频'))
    try:
        limit=time.monotonic()+5
        while len(rec._session['videos'])<2 and time.monotonic()<limit:
            time.sleep(.02)
        assert len(rec._session['videos'])>=2 and rec.active
    finally:
        rec.stop(wait=True)
    metadata=json.loads((folder/'session.json').read_text(encoding='utf-8'))
    timeline=[json.loads(line) for line in (folder/'video-timeline.jsonl').read_text(encoding='utf-8').splitlines()]
    assert metadata['requested_duration']==0 and metadata['reason']=='手动停止'
    assert set(frame['video'] for frame in timeline)==set(metadata['videos'])
    count=0
    for name in metadata['videos']:
        capture=cv2.VideoCapture(str(folder/name))
        assert capture.isOpened()
        count+=int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        capture.release()
    assert count==metadata['video_frames']


def test_selected_background_gamepad_never_falls_back_to_foreground():
    from zzz_od.controller.zzz_pc_controller import ZPcController
    controller=ZPcController.__new__(ZPcController)
    controller.background_mode=False
    controller.enable_background_mode=Mock()
    controller.enable_foreground_mode=Mock()
    controller.active_window=Mock()
    configuration=SimpleNamespace(background_mode=False,_framework_background_mode=True,
        background_gamepad_type='xbox')
    with pytest.raises(RuntimeError,match='ViGEmBus'):
        controller.sync_game_config(configuration,activate=True)
    controller.enable_foreground_mode.assert_not_called()
    controller.active_window.assert_not_called()
