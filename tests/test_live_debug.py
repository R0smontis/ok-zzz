import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.request import Request
from urllib.error import HTTPError

import pytest
from PySide6.QtWidgets import QApplication

from src.live.service import LiveDebugService, LiveError
from src.live.check import SubstituteGame, wait_for_frame, check_live_debug
from src.live.client import LiveClient


@pytest.fixture
def live(tmp_path):
    game = SubstituteGame()
    service = LiveDebugService(game, tmp_path/'live', interval=.05)
    game.service = service
    service.start()
    wait_for_frame(service)
    client = LiveClient(service.folder/'session.json')
    yield service, client, game
    service.stop()


def test_protocol_frozen_smoke(tmp_path):
    assert check_live_debug(tmp_path)['game_input'] == 'none'


def test_jpeg_stream_and_repeated_frame_encoding_cache(live, monkeypatch):
    import cv2
    import numpy as np
    service, client, _ = live
    frame = service.frame()
    data, _ = client.request('/frame.jpg?id='+str(frame['id']), binary=True)
    assert cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR).shape == (1080, 1920, 3)
    encoded, frame_id = service.screenshot(frame['id'])
    monkeypatch.setattr(cv2, 'imencode', lambda *args: pytest.fail('Repeated encoding'))
    assert service.screenshot(frame_id) == (encoded, frame_id)


def test_authentication_and_browser_origin(live):
    service, client, game = live
    for headers in ({}, {'Authorization': 'Bearer wrong'},
                    {'Authorization': 'Bearer '+client.token, 'Origin': 'http://hostile.example'},
                    {'Authorization': 'Bearer '+client.token, 'Host': 'hostile.example'}):
        with pytest.raises(HTTPError) as error:
            client.opener.open(Request(client.url+'/status', headers=headers))
        assert error.value.code == 403
    assert not game.inputs


def test_thread_stacks_are_authenticated_read_only_without_control_lease(live):
    service, client, game = live
    result = client.request('/threads')
    assert result['threads'] and result['captured_at'] > 0
    assert any(row['name'] == threading.current_thread().name for row in result['threads'])
    assert all(isinstance(row['stack'], list) and len(row['stack']) <= 32 for row in result['threads'])
    assert all(isinstance(row['native_id'], int) and row['native_id'] > 0 for row in result['threads'])
    assert service.token not in json.dumps(result)
    assert not service.owned and not game.inputs
    with pytest.raises(HTTPError) as error:
        client.opener.open(Request(client.url+'/threads'))
    assert error.value.code == 403


@pytest.mark.parametrize('command', [
    {'op':'shell', 'cmd':'anything'}, {'op':'click', 'x':-1, 'y':0},
    {'op':'click', 'x':1, 'y':1, 'duration':10}, {'op':'key', 'key':'invalid-key'},
    {'op':'action', 'action':'invalid'}, {'op':'acquire', 'mode':'foreground'},
    {'op':'analyze', 'roi':[0,0,99999,1]}, {'op':'click','x':float('nan'),'y':1},
    {'op':'click','x':True,'y':1}, {'op':'click','x':1920,'y':1080}])
def test_reject_invalid_without_input(live, command):
    service, client, game = live
    command = {'hwnd':101, 'frame_id':1, **command}
    with pytest.raises(LiveError):
        service.submit(command)
    assert game.inputs == [] and not service.owned


def test_requires_control_and_fresh_matching_frame(live):
    service, client, game = live
    command = {'op':'key','key':'w','duration':.01}
    with pytest.raises(ValueError, match='接管'):
        client.command(command)
    client.command({'op':'acquire'})
    with pytest.raises(ValueError, match='过期|改变'):
        client.command({**command, 'hwnd':202})
    game.capture_enabled = False
    time.sleep(.1)
    with service.lock:
        service.frames[-1]['captured_at'] = time.time()-10
    with pytest.raises(ValueError, match='过期'):
        client.command(command)
    assert not game.inputs


def test_resolution_change_releases_and_invalidates_queue(live):
    service, client, game = live
    client.command({'op':'acquire'})
    old = service.status()['frame']
    game.geometry = [0,0,2560,1440]
    deadline = time.monotonic()+2
    while service.owned and time.monotonic()<deadline:
        time.sleep(.01)
    assert not service.owned and game.control_target is None
    with pytest.raises(ValueError):
        client.command({'op':'click','x':1,'y':1,'frame_id':old['id'],'hwnd':101})
    assert not game.inputs


def test_request_id_prevents_duplicate_input(live):
    service, client, game = live
    client.command({'op':'acquire'})
    frame = service.status()['frame']
    c = {'op':'key', 'key':'w', 'duration':.01, 'hwnd':101, 'frame_id':frame['id'], 'request_id':'same'}
    first = client.command(c)
    second = client.command(c)
    assert first['id'] == second['id'] and len(game.inputs) == 1
    with pytest.raises(ValueError, match='另一条'):
        client.command({**c,'key':'s'})


def test_release_cancels_running_and_queued_inputs(live):
    service, client, game = live
    client.command({'op':'acquire'})
    frame = service.status()['frame']
    c = {'op':'key', 'key':'w', 'duration':2, 'hwnd':101, 'frame_id':frame['id']}
    first = service.submit(c)
    deadline = time.monotonic()+2
    while not game.inputs and time.monotonic()<deadline:
        time.sleep(.01)
    second = service.submit({**c, 'key':'s'})
    client.request('/release', {})
    time.sleep(.2)
    assert len(game.inputs) == 1 and not service.owned
    assert not service.job(first['id'])['result']['delivered']
    assert service.job(second['id'])['state'] == 'cancelled'


def test_read_only_analysis_and_event_ring(live):
    service, client, game = live
    result = client.command({'op':'analyze'})['result']
    assert result['enemy_detection_skipped'] and not game.inputs
    for i in range(1000):
        service.event('synthetic', i=i)
    events = client.request('/events?after=900')
    assert len(service.events) == 600
    assert all(e['seq']>900 for e in events['events'])


def test_lease_expiry_releases(live):
    service, client, game = live
    client.command({'op':'acquire'})
    service.lease_until = time.monotonic()-1
    time.sleep(.15)
    assert not service.owned and game.control_target is None


def test_disconnected_game_still_reports_runtime(live):
    service, client, game = live
    game.hwnd = 0
    time.sleep(.15)
    status = client.request('/status')
    assert status['frame'] is None and status['capture_error']
    assert status['runtime']['window']['hwnd'] == 0
    assert 'tasks' in status['runtime'] and status['runtime']['observed_at'] > 0


def test_readonly_battle_context_stops_without_controller():
    from zzz_od.auto_battle.auto_battle_context import AutoBattleContext
    battle = AutoBattleContext.__new__(AutoBattleContext)
    battle.ctx = SimpleNamespace(controller=None)
    battle.dodge_context = SimpleNamespace(stop_context=Mock())
    battle.stop_context()
    battle.dodge_context.stop_context.assert_called_once_with()


def test_debug_ownership_blocks_automatic_inputs_and_allows_release():
    from onedragon.base.controller.input_guard import debug_control_owned, execution_input_allowed
    from onedragon.base.controller.pc_controller_base import PcControllerBase
    controller = PcControllerBase.__new__(PcControllerBase)
    controller.btn_controller = Mock()
    debug_control_owned.set()
    try:
        assert not execution_input_allowed()
        assert controller.btn_tap('w') is False
        assert controller.btn_press('w', .1) is False
        assert controller.click() is False
        assert controller.drag_to(None) is False
        assert controller.scroll(1) is False
        assert controller.input_str('anything') is False
        assert controller.mouse_move(None) is False
        assert controller.keyboard_tap('w') is False
        controller.btn_release('w')
        controller.btn_controller.release.assert_called_once_with('w')
    finally:
        debug_control_owned.clear()


def test_gui_calls_run_on_gui_thread():
    qt = QApplication.instance() or QApplication([])
    from src.live.runtime import GuiCalls
    gui = GuiCalls()
    result = []
    thread = threading.Thread(target=lambda: result.append(gui.call(threading.get_ident)))
    thread.start()
    deadline = time.monotonic()+3
    while thread.is_alive() and time.monotonic()<deadline:
        qt.processEvents()
        time.sleep(.01)
    thread.join(timeout=.1)
    assert result == [threading.get_ident()]


def test_live_panel_controls_without_game(tmp_path, monkeypatch):
    qt = QApplication.instance() or QApplication([])
    from ok import og
    from src.tasks.live_debug_panel import LiveDebugPanel
    monkeypatch.setattr(og, 'my_app', SimpleNamespace())
    panel = LiveDebugPanel()
    service = LiveDebugService(SubstituteGame(), tmp_path/'ui', interval=.05)
    panel.service = service
    try:
        service.start()
        panel.refresh()
        assert panel.stop_button.isEnabled() and panel.acquire_button.isEnabled()
        panel.acquire_button.click()
        deadline = time.monotonic()+2
        while not service.owned and time.monotonic()<deadline:
            time.sleep(.01)
        panel.refresh()
        assert panel.release_button.isEnabled() and not panel.acquire_button.isEnabled()
        panel.release_button.click()
        assert not service.owned
        panel.stop_button.click()
        assert panel.start_button.isEnabled() and not (tmp_path/'ui/session.json').exists()
    finally:
        service.stop()
        panel.timer.stop()
        panel.deleteLater()
        qt.processEvents()


def test_hidden_preview_resumes_latest_frame_without_stopping_monitor(live):
    qt = QApplication.instance() or QApplication([])
    from src.tasks.live_debug_panel import LiveDebugPanel
    from ok import og
    original_app = og.my_app
    og.my_app = SimpleNamespace()
    panel = LiveDebugPanel()
    og.my_app = original_app
    service, client, game = live
    panel.service = service
    panel.timer.stop()
    try:
        panel.refresh()
        assert panel.last_frame == 0
        assert panel.preview.pixmap() is None or panel.preview.pixmap().isNull()
        assert client.request('/status')['monitoring']
        panel.show()
        qt.processEvents()
        panel.refresh()
        assert panel.last_frame > 0 and not panel.preview.pixmap().isNull()
        previous = panel.last_frame
        panel.hide()
        qt.processEvents()
        with service.lock:
            service.publish(game.image, game.hwnd, service.frames[-1]['captured_at'] + 1, game.geometry)
        panel.refresh()
        assert panel.last_frame == previous
        data, latest = service.screenshot(preview=True)
        assert latest > previous
        panel.show()
        qt.processEvents()
        panel.refresh()
        assert panel.last_frame == latest and not panel.preview.pixmap().isNull()
        assert not service.owned and game.inputs == []
    finally:
        panel.close()
        panel.deleteLater()
        qt.processEvents()


def test_publish_resizes_without_blocking_events(live, monkeypatch):
    import cv2
    import numpy as np
    from src.live import service as live_debug
    service, _, game = live
    real_resize = cv2.resize
    acquired = []

    def resize(*args, **kwargs):
        probe = threading.Thread(target=lambda: acquired.append(service.lock.acquire(timeout=1)
                                                                and service.lock.release() is None))
        probe.start()
        probe.join()
        return real_resize(*args, **kwargs)

    game.capture_enabled = False  # stop _monitor from publishing (and resizing) concurrently
    monkeypatch.setattr(live_debug.cv2, 'resize', resize)
    before = service.frame()['id']
    service.publish(np.full((1440, 2560, 3), 7, np.uint8), game.hwnd,
                    service.frame()['captured_at'] + 1, game.geometry)
    item = service.frame()
    assert acquired == [True]
    assert item['id'] > before and item['image'].shape == (1080, 1920, 3)
    assert item['source_size'] == [2560, 1440] and int(item['image'][0, 0, 0]) == 7


def test_publish_strided_bgra_frame_matches_contiguous_resize(tmp_path):
    import cv2
    import numpy as np
    bgra = np.random.default_rng(5).integers(0, 256, (1480, 2576, 4), np.uint8)
    view = bgra[32:1472, 8:2568, :3]
    service = LiveDebugService(SubstituteGame(), tmp_path / 'live')
    service.publish(view, 101, 1.0, None)
    expected = cv2.resize(np.ascontiguousarray(view), (1920, 1080), interpolation=cv2.INTER_AREA)
    assert np.array_equal(service.frame()['image'], expected)


def test_dry_run_stops_before_named_node_without_running_it():
    from types import SimpleNamespace
    from onedragon.base.operation import dry_run
    from onedragon.base.operation.operation import Operation
    from onedragon.base.operation.operation_edge import node_from
    from onedragon.base.operation.operation_node import operation_node
    ran = []

    class Probe(Operation):
        @operation_node(name='入口', is_start_node=True)
        def entry(self):
            ran.append('入口')
            return self.round_success()

        @node_from(from_name='入口')
        @operation_node(name='拆解确认')
        def spend(self):
            ran.append('拆解确认')
            return self.round_success()

    stopped = Mock()
    run_context = SimpleNamespace(is_context_stop=False, is_context_pause=False, is_context_running=True,
                                  stop_running=stopped, event_bus=Mock())
    ctx = SimpleNamespace(run_context=run_context, unlisten_all_event=Mock(), controller=None,
                          is_game_window_ready=True)
    op = Probe(ctx, op_name='演练')
    op.screenshot = lambda: None
    dry_run.set_stop_before(['拆解确认'])
    try:
        result = op.execute()
    finally:
        hits = dry_run.hits()
        dry_run.set_stop_before(())
    assert ran == ['入口']
    assert not result.success and '拆解确认' in result.status
    stopped.assert_called_once()
    assert hits == [{'operation': '演练', 'node': '拆解确认'}]


def test_dry_run_gate_does_not_leak_into_next_normal_run():
    from types import SimpleNamespace
    from onedragon.base.operation import dry_run
    from onedragon.base.operation.application.application_run_context import ApplicationRunContext
    from onedragon.base.operation.operation import Operation
    from onedragon.base.operation.operation_edge import node_from
    from onedragon.base.operation.operation_node import operation_node
    ran = []
    ctx = SimpleNamespace(controller=None, current_instance_idx=0, unlisten_all_event=Mock(),
                          is_game_window_ready=True)
    ctx.run_context = ApplicationRunContext(ctx)

    class Charge(Operation):
        @operation_node(name='选择预备编队', is_start_node=True)
        def team(self):
            return self.round_success()

        @node_from(from_name='选择预备编队')
        @operation_node(name='出战')
        def deploy(self):
            ran.append('出战')
            return self.round_success()

    def create(*_):
        op = Charge(ctx, op_name='体力刷本')
        op.screenshot = lambda: None
        return op
    ctx.run_context.get_application = create
    dry_run.set_stop_before(['出战'])
    try:
        ctx.run_context.run_application('charge_plan')
        assert ran == [] and dry_run.hits() == [{'operation': '体力刷本', 'node': '出战'}]
        ctx.run_context.run_application('charge_plan')
    finally:
        dry_run.set_stop_before(())
    assert ran == ['出战']
    assert ctx.run_context.last_application_result.success


def test_dry_run_list_is_only_accepted_on_task_start(tmp_path):
    service = LiveDebugService(SubstituteGame(), tmp_path / 'live')
    for bad in ({'op': 'task_stop', 'task': 'X', 'stop_before': ['a']},
                {'op': 'task_start', 'task': 'X', 'stop_before': 'a'},
                {'op': 'task_start', 'task': 'X', 'stop_before': [1]}):
        with pytest.raises(LiveError):
            service._validate(bad)
    service._validate({'op': 'task_start', 'task': 'X', 'stop_before': ['点击拆解确认']})


def test_single_application_id_is_only_accepted_on_task_start(tmp_path):
    service = LiveDebugService(SubstituteGame(), tmp_path / 'live')
    for bad in ({'op': 'task_stop', 'task': 'X', 'app': 'scratch_card'},
                {'op': 'task_start', 'task': 'X', 'app': 'Scratch Card'},
                {'op': 'task_start', 'task': 'X', 'app': 3}):
        with pytest.raises(LiveError):
            service._validate(bad)
    service._validate({'op': 'task_start', 'task': 'OneDragonDailyTask', 'app': 'scratch_card'})
    assert service._execute({'op': 'task_start', 'task': 'OneDragonDailyTask', 'app': 'scratch_card'},
                            service.generation) == {'task': 'OneDragonDailyTask', 'action': 'start', 'app': 'scratch_card'}


class _FakeLeasePad:
    pad = object()
    combo_press_time = .05

    def reset(self):
        pass


class _FakeLeaseController:
    """前台模式（键盘）账号：enable_xbox() 会替换 btn_controller 与按键映射。"""

    def __init__(self):
        self.keyboard = object()
        self.btn_controller = self.keyboard
        self.action_keys = {'dodge': 'shift'}
        self.gamepad_action_keys = None
        self.xbox_controller = None

    def enable_xbox(self):
        self.xbox_controller = _FakeLeasePad()
        self.btn_controller = self.xbox_controller
        self.action_keys = {'dodge': 'xbox_b'}
        self.gamepad_action_keys = {'dodge': 'xbox_b'}


def _lease_runtime():
    from src.live.runtime import GameRuntime
    from types import SimpleNamespace
    controller = _FakeLeaseController()
    context = SimpleNamespace(controller=controller, init_controller=lambda **_: None)
    return GameRuntime(SimpleNamespace(), None), context, controller


def test_gamepad_lease_restores_the_account_controller_mode():
    """接管切到 Xbox 手柄后，释放控制要还原账号原本的控制器与按键映射（前台模式/DS4 账号）。"""
    runtime, context, controller = _lease_runtime()
    pad = runtime._acquire_gamepad(context)
    assert pad is controller.xbox_controller and controller.btn_controller is pad
    assert controller.action_keys == {'dodge': 'xbox_b'}
    runtime.release()
    assert controller.btn_controller is controller.keyboard
    assert controller.action_keys == {'dodge': 'shift'}
    assert controller.gamepad_action_keys is None


def test_release_keeps_a_controller_the_task_already_switched():
    runtime, context, controller = _lease_runtime()
    runtime._acquire_gamepad(context)
    controller.btn_controller = controller.keyboard  # 任务自行切回前台模式
    runtime.release()
    assert controller.action_keys == {'dodge': 'xbox_b'}  # 不覆盖任务当前的模式


@pytest.fixture
def opt_in_panel(tmp_path, monkeypatch):
    """A panel inside the app (my_app has window_hwnd) whose start() only records the call."""
    qt = QApplication.instance() or QApplication([])
    from ok import og
    from onedragon.utils import os_utils
    from src.tasks.live_debug_panel import LiveDebugPanel
    monkeypatch.setattr(og, 'my_app', SimpleNamespace(window_hwnd=lambda: 0))
    monkeypatch.setattr(os_utils, 'get_work_dir', lambda: str(tmp_path))
    monkeypatch.delenv('OK_ZZZ_LIVE_DEBUG', raising=False)
    monkeypatch.setattr('sys.argv', ['main.py'])
    starts = []
    monkeypatch.setattr(LiveDebugPanel, 'start', lambda self: starts.append(self))
    panels = []

    def build():
        panel = LiveDebugPanel()
        panel.timer.stop()
        panels.append(panel)
        return panel
    yield build, starts, tmp_path/'debug/live'
    for panel in panels:
        panel.deleteLater()
    qt.processEvents()


def test_live_debug_is_off_until_requested(opt_in_panel):
    build, starts, _ = opt_in_panel
    panel = build()
    panel.refresh()
    assert starts == [] and panel.start_button.isEnabled()
    assert '默认关闭' in panel.status_label.text()


@pytest.mark.parametrize('how', ['flag', 'env'])
def test_agent_launch_switch_starts_live_debug(opt_in_panel, monkeypatch, how):
    build, starts, _ = opt_in_panel
    if how == 'flag':
        monkeypatch.setattr('sys.argv', ['main.py', '--live-debug'])
    else:
        monkeypatch.setenv('OK_ZZZ_LIVE_DEBUG', '1')
    panel = build()
    assert starts == [panel]


def test_agent_request_file_starts_a_running_app_once(opt_in_panel):
    from src.live.request import write_request
    build, starts, folder = opt_in_panel
    panel = build()
    panel.refresh()
    assert starts == []
    write_request(folder)
    panel.refresh()
    assert starts == [panel] and not (folder/'request').exists()  # Consumed: not repeated.
    panel.refresh()
    assert starts == [panel]


def test_client_enable_waits_for_the_requested_session(tmp_path):
    from src.live.client import enable_session
    folder = tmp_path/'debug/live'
    services = []

    def app():  # Stands in for the running ok-zzz noticing the request file.
        deadline = time.monotonic()+5
        while not (folder/'request').exists() and time.monotonic() < deadline:
            time.sleep(.05)
        (folder/'request').unlink()
        service = LiveDebugService(SubstituteGame(), folder, interval=.05)
        services.append(service)
        service.start()
    thread = threading.Thread(target=app)
    thread.start()
    try:
        session = enable_session(tmp_path, timeout=10)
        assert session == folder/'session.json'
        assert LiveClient(session).request('/status')['monitoring']
        assert enable_session(tmp_path, timeout=1) == session  # Already on: no new request.
        assert not (folder/'request').exists()
    finally:
        thread.join(timeout=6)
        for service in services:
            service.stop()


def test_client_enable_reports_and_cleans_up_when_no_app_answers(tmp_path):
    from src.live.client import enable_session
    with pytest.raises(ValueError, match='未开启实时调试'):
        enable_session(tmp_path, timeout=1)
    assert not (tmp_path/'debug/live/request').exists()
