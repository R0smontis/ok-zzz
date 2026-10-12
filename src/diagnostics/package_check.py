"""供 --check-package 使用的离线打包验证，不初始化游戏设备。"""
import os
import sys
import json
import tempfile
import importlib
import time
from pathlib import Path
from types import SimpleNamespace


def run_package_check():
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from src.controls.win32_compat import install_win32_compat
    install_win32_compat()
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt, QPointF
    from PySide6.QtGui import QDropEvent
    from qfluentwidgets import FluentIcon
    from ok import og
    from ok.util.config import Config
    from ok.ui.qt.tasks.ConfigCard import ConfigCard
    from ok.ui.qt.tasks.TaskCard import TaskCard
    from src.config import config
    from src.tasks import app_tasks
    from src.tasks.app_option_ui import OPTION_LABELS
    from zzz_od.application.app_options_data import APP_OPTIONS
    from onedragon.utils import os_utils
    import gettext

    for name in ('cv2', 'onnxruntime', 'onnxocr.onnx_paddleocr', 'scipy.signal',
                 'librosa', 'soundcard', 'win32api', 'win32timezone'):
        importlib.import_module(name)
    root = Path(os_utils.get_work_dir())
    from src.diagnostics.model_check import check_realtime_models
    model_check = check_realtime_models(root)
    from src.controls.background_input_check import check_background_input
    background_input_check = check_background_input()
    from src.diagnostics.lost_void_check import check_lost_void_runtime
    lost_void_check = check_lost_void_runtime(root)
    from src.live.check import check_live_debug
    live_debug_check = check_live_debug(root)
    for relative in ('assets/game_data/compendium_data.yml',
                     'assets/template/target_state/enemy_attribute_icon/raw.png',
                     'assets/template/target_state/enemy_health_panel_shape/empty.png',
                     'assets/template/target_state/enemy_health_panel_shape/filled.png',
                     'config/auto_battle/通用操作.sample.yml',
                     'assets/game_data/screen_info/matrix_action_team_select.yml',
                     'icons/icon.png', 'i18n/zh_CN/LC_MESSAGES/ok.mo'):
        assert (root / relative).is_file(), f'缺少资源：{relative}'
    translations = gettext.translation('ok', str(root / 'i18n'), languages=['zh_CN'])
    assert translations.gettext('matrix_team_mode') == '矩阵行动编队方式'
    from src.controls.interaction import INTERACTIONS, install_interaction_labels
    install_interaction_labels()
    assert [cls.__name__ for cls in INTERACTIONS] == ['BackgroundGamepad', 'Pynput']

    qt = QApplication.instance() or QApplication([])
    app = SimpleNamespace(tr=translations.gettext)
    og.app = app
    og.config = config
    from onedragon.base.controller.pc_game_window import PcGameWindow
    from src.globals import Globals
    from src.tasks.option_widgets import install_option_widgets
    from src.runtime.gpu_ocr import install_gpu_ocr
    install_option_widgets()
    install_gpu_ocr()
    assert callable(Globals._window_provider)
    assert hasattr(PcGameWindow(), 'window_provider')
    for cls in config['windows']['interaction']:
        assert cls.__new__(cls).should_capture()
    checked = []
    recording_controls = []
    ui_executor = SimpleNamespace(scene=None, current_task=None, onetime_tasks=[], trigger_tasks=[],
        waiting_for_task=lambda task: None)
    ui_executor.get_all_tasks = lambda: ui_executor.onetime_tasks+ui_executor.trigger_tasks
    og.executor = ui_executor
    with tempfile.TemporaryDirectory(prefix='.package-check-', dir=str(root)) as folder:
        from ok.ui.qt.settings.GlobalConfigCard import GlobalConfigCard
        for option in config['global_configs']:
            settings = Config(option.name, option.default_config, folder=folder)
            card = GlobalConfigCard(settings, option)
            if option.name == '识别计算设置':
                box = card.config_widget_by_key['识别帧率上限'].combo_box
                box.setCurrentText('20 帧/秒')
                assert settings['识别帧率上限'] == 20
                box.setCurrentText('30 帧/秒')
                assert settings['识别帧率上限'] == 30
            card.close()
            card.deleteLater()
            qt.processEvents()
        for metadata in APP_OPTIONS:
            if metadata['app_id'] == 'one_dragon' or 'error' in metadata:
                continue
            cls = next(cls for cls in vars(app_tasks).values()
                       if isinstance(cls, type) and getattr(cls, 'app_id', None) == metadata['app_id'])
            task = cls(executor=SimpleNamespace(scene=None), app=app)
            task.config = Config(cls.__name__, task.default_config, folder=folder, validator=task.validate)
            task.post_init()
            ui_executor.onetime_tasks.append(task)
            card = ConfigCard(task, task.name, task.config, task.description, task.default_config,
                              task.config_description, task.config_type, FluentIcon.INFO)
            for option in metadata.get('options', []):
                widget = card.config_widget_by_key[option['key']]
                assert widget.title.text() == OPTION_LABELS[option['key']]
            if task.app_id == 'lost_void':
                card.config_widget_by_key['mission_name'].combo_box.setCurrentText('矩阵行动')
                card.config_widget_by_key['matrix_team_mode'].combo_box.setCurrentText('自定义编队')
                role = card.config_widget_by_key['matrix_agent_1']
                assert not role.isHidden()
                role.combo_box.setCurrentText('安比')
                assert task.config['matrix_agent_1'] == 'anby'
            if task.app_id == 'charge_plan':
                plans = card.config_widget_by_key['plan_list']
                plans.add_plan()
                plans.editors[-1]['plan_times'].setValue(3)
                assert json.loads(task.config['plan_list'])[-1]['plan_times'] == 3
                category = plans.editors[0]['category_name']
                category.setCurrentIndex(category.findData('区域巡防'))
                row = json.loads(task.config['plan_list'])[0]
                assert row['mission_type_name'] == '怪兽与怪客' and row['mission_name'] is None
                for _ in range(3):
                    plans.add_plan()
                assert len(plans.editors) == 4 and plans.scroll.height() == 320
            card.close()
            card.deleteLater()
            qt.processEvents()
            checked.append(task.app_id)
        for module, name in config['trigger_tasks']:
            task = getattr(importlib.import_module(module), name)(executor=SimpleNamespace(scene=None), app=app)
            assert task.name
            task.config = Config(name, task.default_config, folder=folder, validator=task.validate)
            ui_executor.trigger_tasks.append(task)
            card = ConfigCard(task, task.name, task.config, task.description, task.default_config,
                              task.config_description, task.config_type, FluentIcon.INFO)
            if name == 'AutoCombatTask':
                assert hasattr(card.config_widget_by_key['优先实时闪避'], 'switch_button')
                assert '通用操作' in task.config_type['战斗配置']['options']
            if name == 'DiagnosticRecordingTask':
                card.config_widget_by_key['录制方式'].combo_box.setCurrentText('视频')
                card.config_widget_by_key['视频帧率'].combo_box.setCurrentText('60 帧/秒')
                card.config_widget_by_key['视频分辨率'].combo_box.setCurrentText('1080P（1920×1080）')
                assert task.config['录制方式'] == '视频' and task.config['视频帧率'] == 60
                assert task.config['视频分辨率'] == '1080P'
                assert task.config['录制时长秒'] == 0
                recording_card = TaskCard(task, False)
                controls = recording_card.recording_controls
                recording_controls = [button.text() for button in (
                    controls.start_button, controls.pause_button, controls.stop_button)]
                assert recording_controls == ['开始录制', '暂停录制', '停止录制']
                assert recording_card.enable_button is None
                assert controls.start_button.isEnabled() and not controls.pause_button.isEnabled()
                recording_card.dispose()
                recording_card.close()
                recording_card.deleteLater()
            card.close()
            card.deleteLater()
            qt.processEvents()
        from src.tasks.daily_task import OneDragonDailyTask
        daily=OneDragonDailyTask(executor=ui_executor,app=app)
        daily.config=Config('OneDragonDailyTask',daily.default_config,folder=folder,validator=daily.validate)
        daily_card=TaskCard(daily,True)
        assert daily_card.isExpand
        assert daily.group_name == '一条龙日常' and '执行顺序' not in daily_card.config_widget_by_key
        editor=daily_card.config_widget_by_key['启用应用']
        first=editor.order[0]
        editor.table.resize(700,440)
        qt.processEvents()
        rect=editor.table.visualRect(editor.table.model().index(2,0))
        daily_mime=editor.table.row_mime(0)
        drop=QDropEvent(QPointF(rect.center().x(),rect.bottom()-1),Qt.MoveAction,
                       daily_mime,Qt.LeftButton,Qt.NoModifier)
        editor.table.dropEvent(drop)
        assert drop.isAccepted() and daily.config['执行顺序'][2] == first
        daily_card.dispose()
        daily_card.close()
        daily_card.deleteLater()
        from src.tasks.debug_tab import DebugToolsTab
        debug_page=DebugToolsTab()
        assert debug_page.card_widgets[0].task.recording_controls
        assert not debug_page.card_widgets[0].task.visible
        assert debug_page.live_debug_panel.start_button.text() == '开始监控'
        debug_page.live_debug_panel.timer.stop()
        for card in debug_page.card_widgets:
            card.dispose()
        debug_page.timer.stop()
        debug_page.close()
        debug_page.deleteLater()
        from pygetwindow import Win32Window
        import win32gui
        import pyautogui
        assert Win32Window(win32gui.GetDesktopWindow())._hWnd
        assert len(pyautogui.position()) == 2
        from src.diagnostics.recorder import DiagnosticRecorder
        import cv2
        import numpy as np
        from zzz_od.controller.zzz_controller import ZzzController
        controller = ZzzController.__new__(ZzzController)
        controller.standard_width, controller.standard_height = 1920, 1080
        capture_bgr = np.full((1080, 1920, 3), (10, 40, 230), np.uint8)
        assert tuple(controller.normalize_frame(capture_bgr)[0, 0]) == (230, 40, 10)
        assert tuple(capture_bgr[0, 0]) == (10, 40, 230)
        diagnostic = DiagnosticRecorder()
        recording = Path(diagnostic.start(folder, fps=60, resolution='1080P'))
        try:
            diagnostic.observe(np.full((1080, 1920, 3), 80, np.uint8))
            limit = time.monotonic() + 3
            while diagnostic.status['images'] == 0 and time.monotonic() < limit:
                time.sleep(0.01)
            time.sleep(0.2)
            assert diagnostic.pause() and diagnostic.paused and not diagnostic.active
            paused_elapsed = diagnostic.status['elapsed']
            diagnostic.record('must_not_record_while_paused')
            time.sleep(0.15)
            assert diagnostic.status['elapsed'] == paused_elapsed
            assert diagnostic.resume() and diagnostic.active
            diagnostic.observe(np.full((1080, 1920, 3), 140, np.uint8))
            time.sleep(0.2)
        finally:
            diagnostic.stop(wait=True)
        status = diagnostic.status
        assert status['state'] == '已保存' and not status['error'], status
        assert status['images'] > 0 and status['video_frames'] > 1, status
        recording_info = json.loads((recording / 'session.json').read_text(encoding='utf-8'))
        assert recording_info['requested_duration'] == 0
        assert recording_info['fps'] == 60 and recording_info['video_size'] == [1920,1080]
        assert recording_info['paused_duration'] >= 0.1
        recording_events = [json.loads(line)['type'] for line in
                            (recording / 'events.jsonl').read_text(encoding='utf-8').splitlines()]
        assert recording_events == ['recording_pause', 'recording_resume']
        video = cv2.VideoCapture(str(recording / recording_info['video']))
        try:
            assert video.isOpened() and video.read()[0], '诊断视频无法回读'
            assert video.get(cv2.CAP_PROP_FPS) == 60
            assert video.get(cv2.CAP_PROP_FRAME_WIDTH) == 1920 and video.get(cv2.CAP_PROP_FRAME_HEIGHT) == 1080
        finally:
            video.release()
        from src.controls.user_input_trace import GameInputTrace
        input_trace = GameInputTrace(lambda: 0, lambda *args, **kwargs: None)
        try:
            input_trace.start()
            time.sleep(0.1)
            assert all(listener.is_alive() for listener in input_trace.listeners), '用户输入监听未启动'
        finally:
            input_trace.stop()
        from zzz_od.application.hollow_zero.lost_void.matrix_team import resolve_agent_ids
        assert resolve_agent_ids(['安比', '妮可']) == ['anby', 'nicole']
        from onedragon.base.controller.input_guard import execution_input_allowed
        assert callable(execution_input_allowed)
        from zzz_od.auto_battle.atomic_op.generic_combat import AtomicGenericCombat
        from zzz_od.auto_battle.generic_handlers import normal_handler, event_handlers
        assert AtomicGenericCombat.OP_NAME == '通用战斗'
        assert normal_handler().operations[0].op_name == '通用战斗'
        assert len(event_handlers(['闪避识别-红光', '按键可用-连携技'])) == 2
        from zzz_od.auto_battle.atomic_op.realtime_response import AtomicRealtimeResponse, WARNING_CODES
        from zzz_od.auto_battle.auto_battle_state_record_service import AutoBattleStateRecordService
        from onedragon.base.conditional_operation.state_recorder import StateRecord
        warning_service = AutoBattleStateRecordService()
        dry_actions = []
        warning_context = SimpleNamespace(state_record_service=warning_service,
            agent_context=SimpleNamespace(team_info=SimpleNamespace(agent_list=[None]*3)),
            switch_next=lambda: dry_actions.append('switch_next'),
            dodge=lambda: dry_actions.append('dodge'),
            normal_attack=lambda: dry_actions.append('normal_attack'))
        for warning, code in WARNING_CODES.items():
            now = time.time()
            warning_service.batch_update_states([StateRecord('按键可用-普通攻击', now),
                StateRecord('自定义-实时闪避事件', now, value=code)])
            AtomicRealtimeResponse(warning_context).execute()
        assert dry_actions == ['dodge', 'normal_attack', 'switch_next', 'normal_attack',
                               'dodge', 'normal_attack']
        yellow_handler = event_handlers(['闪避识别-黄光'])[0]
        assert yellow_handler.operations[0].op_name == AtomicRealtimeResponse.OP_NAME
        assert yellow_handler.operations[0].data == ['闪避识别-黄光']
        from src.runtime.frame_geometry import FrameGeometry
        geometry_sizes = [(1280,720),(1600,900),(1920,1080),(2560,1440),(3840,2160)]
        for width,height in geometry_sizes:
            source=np.full((height,width,3),(10,40,230),np.uint8)
            normalized=controller.normalize_frame(source)
            assert normalized.shape == (1080,1920,3) and tuple(normalized[0,0]) == (230,40,10)
            assert controller.frame_geometry['source'] == [width,height]
            assert FrameGeometry(width,height).to_client(960,540) == (width/2,height/2)
        assert (3840,2160) in config['supported_resolution']['resize_to']
    print('PACKAGE_CHECK=' + json.dumps({'status': 'ok', 'frozen': bool(getattr(sys, 'frozen', False)),
                                        'root': str(root), 'applications': checked,
                                        'models': model_check,
                                        'background_input': background_input_check,
                                        'live_debug': live_debug_check,
                                        'lost_void': lost_void_check,
                                        'realtime_warning_response': 'yellow assist, red/audio dodge: dry-run passed',
                                        'engine_frame_color': 'RGB',
                                        'ui': {'daily_order_editor':'passed', 'charge_plan_editor':'passed',
                                               'daily_drag_order':'passed', 'daily_default_expanded':'passed',
                                               'charge_plan_dropdowns':'passed', 'charge_plan_scroll':'passed',
                                               'video_quality_controls':'passed',
                                               'debug_sidebar':'passed', 'gamepad_interaction':'passed',
                                               'win32_overlay_compat':'passed'},
                                        'window_resolutions': geometry_sizes,
                                        'diagnostics': {'video': recording_info['video'],
                                                        'default_duration': recording_info['requested_duration'],
                                                        'recording_controls': recording_controls,
                                                        'pause_resume': 'passed',
                                                        'user_input_backend': 'pynput',
                                                        'images': status['images'],
                                                        'fps': recording_info['fps'],
                                                        'video_size': recording_info['video_size'],
                                                        'video_frames': status['video_frames']},
                                        'trigger_count': len(config['trigger_tasks'])}))
    return 0
