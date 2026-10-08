"""Capture selection and controller binding; no real windows or input."""
from types import SimpleNamespace
from unittest.mock import Mock
import pytest

from ok import og
from src.globals import Globals
from onedragon.base.controller import pc_game_window as windows


def test_frame_bridge_returns_actual_new_frame_and_capture_time(monkeypatch):
    fresh, stale = object(), object()
    executor = SimpleNamespace(next_frame=Mock(return_value=fresh), frame=stale, _last_frame_time=123.5)
    monkeypatch.setattr(og, 'executor', executor)
    bridge = Globals.__new__(Globals)
    assert bridge._frame_provider() == (123.5, fresh)
    executor.next_frame.assert_called_once_with(time_out=12)


def test_capture_timeout_never_returns_cached_frame_and_releases_input(monkeypatch):
    executor = SimpleNamespace(next_frame=Mock(return_value=None), frame=object(), _last_frame_time=123.5)
    monkeypatch.setattr(og, 'executor', executor)
    bridge = Globals.__new__(Globals)
    bridge._context = SimpleNamespace(auto_battle_context=SimpleNamespace(stop_auto_battle=Mock()),
                                    controller=SimpleNamespace(cancel_inputs=Mock()))
    with pytest.raises(RuntimeError, match='连续12秒'):
        bridge._frame_provider()
    bridge._context.auto_battle_context.stop_auto_battle.assert_called_once()
    bridge._context.controller.cancel_inputs.assert_called_once()


def test_controller_uses_selected_handle_without_title_and_tracks_restart(monkeypatch):
    selected = [101]
    monkeypatch.setattr(windows.ctypes.windll.user32, 'IsWindow', lambda hwnd: hwnd in (101, 202))
    wrapped = Mock(side_effect=lambda hwnd: SimpleNamespace(_hWnd=hwnd, isActive=True))
    monkeypatch.setattr(windows, 'Win32Window', wrapped)
    lookup = Mock()
    monkeypatch.setattr(windows.pyautogui, 'getWindowsWithTitle', lookup)
    window = windows.PcGameWindow()
    window.window_provider = lambda: selected[0]
    assert window.win_title is None
    assert window.get_hwnd() == 101 and window.is_win_valid
    selected[0] = 202
    assert window.get_win()._hWnd == 202
    selected[0] = 0
    assert window.get_hwnd() is None and not window.is_win_valid
    lookup.assert_not_called()
    assert wrapped.call_count == 2


def test_bridge_rejects_unselected_and_mismatched_capture(monkeypatch):
    device = {'device': 'windows', 'real_hwnd': 101}
    manager = SimpleNamespace(get_preferred_device=lambda: device,
                              hwnd_window=SimpleNamespace(hwnd=101))
    monkeypatch.setattr(og, 'device_manager', manager)
    bridge = Globals.__new__(Globals)
    assert bridge._window_provider() == 101
    manager.hwnd_window.hwnd = 202
    assert bridge._window_provider() == 0
    device['real_hwnd'] = 202
    assert bridge._window_provider() == 202
    device['device'] = 'adb'
    assert bridge._window_provider() == 0


def test_capture_does_not_require_foreground_with_persisted_backend_names():
    from src.config import config
    classes = config['windows']['interaction']
    assert [cls.__name__ for cls in classes] == ['Pynput', 'PostMessage', 'ForegroundPostMessage', 'PyDirect', 'BackgroundGamepad']
    for cls in classes:
        backend = cls.__new__(cls)
        assert backend.should_capture()


def test_missing_gamepad_never_falls_back_to_foreground_input(monkeypatch):
    from zzz_od.application.battle_assistant import battle_assistant_input_mode as mode
    monkeypatch.setattr(mode.pc_button_utils, 'is_vgamepad_installed', lambda: False)
    controller = SimpleNamespace(enable_foreground_mode=Mock(), enable_background_mode=Mock())
    ctx = SimpleNamespace(controller=controller, battle_assistant_config=object(),
                          game_config=SimpleNamespace(background_gamepad_type='xbox'))
    success, message = mode.apply_battle_assistant_input_mode(ctx, background_mode=True, activate=False)
    assert not success and 'ViGEmBus' in message
    controller.enable_foreground_mode.assert_not_called()
    controller.enable_background_mode.assert_not_called()


@pytest.mark.parametrize('preferred', ['pc', 'pc_99'])
def test_selected_game_rebinds_after_window_restart(monkeypatch, preferred):
    from ok.device.DeviceManager import DeviceManager
    from src.capture_compat import install_device_selection_compat
    monkeypatch.setattr(DeviceManager, '_replace_pc_devices',
                        lambda manager, devices: manager.device_dict.update(devices))
    install_device_selection_compat()
    manager = SimpleNamespace(config={'preferred': preferred, 'selected_hwnd': 99},
                              windows_capture_config={'exe': ['ZenlessZoneZero.exe']}, device_dict={})
    device = {'imei': 'pc_101', 'device': 'windows', 'connected': True, 'real_hwnd': 101}
    DeviceManager._replace_pc_devices(manager, {'pc_101': device})
    assert manager.config == {'preferred': 'pc_101', 'selected_hwnd': 101}


@pytest.mark.parametrize('preferred,exe,devices', [
    ('adb_serial', ['game.exe'], {'pc_101': {'imei': 'pc_101', 'device': 'windows', 'connected': True, 'real_hwnd': 101}}),
    ('pc_99', None, {'pc_101': {'imei': 'pc_101', 'device': 'windows', 'connected': True, 'real_hwnd': 101}}),
    ('pc_99', ['game.exe'], {'pc': {'imei': 'pc', 'device': 'windows', 'connected': False, 'real_hwnd': 0}}),
])
def test_window_rebind_never_selects_unrelated_or_disconnected_device(monkeypatch, preferred, exe, devices):
    from ok.device.DeviceManager import DeviceManager
    from src.capture_compat import install_device_selection_compat
    monkeypatch.setattr(DeviceManager, '_replace_pc_devices',
                        lambda manager, devices: manager.device_dict.update(devices))
    install_device_selection_compat()
    manager = SimpleNamespace(config={'preferred': preferred}, windows_capture_config={'exe': exe}, device_dict={})
    DeviceManager._replace_pc_devices(manager, devices)
    assert manager.config['preferred'] == preferred


def test_window_restart_schedules_throttled_device_refresh(monkeypatch):
    import win32gui
    from src.capture_compat import refresh_restarted_window
    monkeypatch.setattr(win32gui,'IsWindow',lambda hwnd:hwnd==202)
    manager=SimpleNamespace(windows_capture_config={'exe':['ZenlessZoneZero.exe']},
        get_preferred_device=lambda:{'device':'windows','real_hwnd':101},refresh=Mock())
    window=SimpleNamespace(device_manager=manager,hwnd=202,width=2560,height=1440)
    refresh_restarted_window(window);refresh_restarted_window(window)
    manager.refresh.assert_called_once()


@pytest.mark.parametrize('device,old_valid,size', [('adb',False,(2560,1440)),
    ('windows',True,(2560,1440)),('windows',False,(320,240))])
def test_window_refresh_preserves_other_selection_and_ignores_splash(monkeypatch,device,old_valid,size):
    import win32gui
    from src.capture_compat import refresh_restarted_window
    monkeypatch.setattr(win32gui,'IsWindow',lambda hwnd:old_valid)
    manager=SimpleNamespace(windows_capture_config={'exe':['ZenlessZoneZero.exe']},
        get_preferred_device=lambda:{'device':device,'real_hwnd':101},refresh=Mock())
    refresh_restarted_window(SimpleNamespace(device_manager=manager,hwnd=202,width=size[0],height=size[1]))
    manager.refresh.assert_not_called()
