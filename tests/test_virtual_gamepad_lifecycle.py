"""ViGEm pads must be unplugged explicitly; vgamepad's __del__ never runs on kill or session end."""
import gc
from types import SimpleNamespace
from unittest.mock import Mock

from onedragon.base.controller.pc_button import pc_button_utils
from onedragon.base.controller.pc_controller_base import PcControllerBase


class FakePad:
    removed = []

    def __init__(self, name):
        self.name = name

    def reset(self):
        pass

    def update(self):
        pass

    def __del__(self):
        FakePad.removed.append(self.name)


def controller_with_pads():
    controller = PcControllerBase.__new__(PcControllerBase)
    controller.keyboard_controller = Mock()
    controller.xbox_controller = SimpleNamespace(pad=FakePad('xbox'), reset=Mock())
    controller.ds4_controller = SimpleNamespace(pad=FakePad('ds4'), reset=Mock())
    controller.btn_controller = controller.xbox_controller
    controller.background_mode = True
    return controller


def test_release_unplugs_each_pad_once_and_falls_back_to_keyboard():
    FakePad.removed = []
    controller = controller_with_pads()
    xbox, ds4 = controller.xbox_controller, controller.ds4_controller
    controller.release_virtual_gamepads()
    assert sorted(FakePad.removed) == ['ds4', 'xbox']
    xbox.reset.assert_called_once()
    ds4.reset.assert_called_once()
    assert controller.btn_controller is controller.keyboard_controller
    assert controller.xbox_controller is None and controller.ds4_controller is None
    assert not controller.background_mode
    gc.collect()
    assert sorted(FakePad.removed) == ['ds4', 'xbox']  # Not removed a second time by the collector.
    controller.release_virtual_gamepads()  # Idempotent.
    assert len(FakePad.removed) == 2


def test_vgamepad_is_not_imported_until_a_gamepad_mode_asks(monkeypatch):
    imported = []
    import builtins
    real_import = builtins.__import__

    def tracking_import(name, *args, **kwargs):
        if name == 'vgamepad':
            imported.append(name)
            raise ImportError('VIGEM_ERROR_BUS_NOT_FOUND')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(pc_button_utils, '_VGAMEPAD_INSTALLED', None)
    monkeypatch.setattr(builtins, '__import__', tracking_import)
    assert imported == []
    assert pc_button_utils.is_vgamepad_installed() is False
    assert pc_button_utils.is_vgamepad_installed() is False
    assert imported == ['vgamepad']  # Probed once, cached.


def test_app_stop_unplugs_pads_and_session_end_triggers_stop(monkeypatch):
    from src.globals import Globals
    app = Globals.__new__(Globals)
    app._shutdown_lock = __import__('threading').Lock()
    app._stopped = False
    controller = Mock()
    app._context = SimpleNamespace(run_context=Mock(), after_app_shutdown=Mock(), controller=controller)
    monkeypatch.setattr('src.diagnostics.recorder.recorder.stop', lambda reason: None)
    monkeypatch.setattr('ok.og.executor', SimpleNamespace(trigger_tasks=[]), raising=False)
    app._session_ending()
    controller.disconnect_virtual_gamepad_bus.assert_called_once()
    app.stop()
    controller.disconnect_virtual_gamepad_bus.assert_called_once()


def test_bus_handle_is_closed_once_after_pads_and_not_again_at_interpreter_exit(monkeypatch):
    import sys
    calls = []

    class VBus:
        def __del__(self):
            calls.append('disconnect')

    module = SimpleNamespace(VBUS=VBus())
    monkeypatch.setitem(sys.modules, 'vgamepad.win.virtual_gamepad', module)
    FakePad.removed = []
    controller = controller_with_pads()
    controller.disconnect_virtual_gamepad_bus()
    assert sorted(FakePad.removed) == ['ds4', 'xbox'] and calls == ['disconnect']
    controller.disconnect_virtual_gamepad_bus()
    module.VBUS = None
    gc.collect()
    assert calls == ['disconnect']


def test_bus_is_never_opened_just_to_close_it(monkeypatch):
    import sys
    monkeypatch.delitem(sys.modules, 'vgamepad.win.virtual_gamepad', raising=False)
    controller = controller_with_pads()
    controller.disconnect_virtual_gamepad_bus()
    assert 'vgamepad.win.virtual_gamepad' not in sys.modules


def test_context_adopts_detected_game_exe_only_when_unset(tmp_path, monkeypatch):
    from src.globals import Globals
    exe = tmp_path/'ZenlessZoneZero.exe'; exe.write_bytes(b'')
    manager = SimpleNamespace(get_preferred_device=lambda: {'device': 'windows'}, get_exe_path=lambda device: str(exe))
    monkeypatch.setattr('ok.og.device_manager', manager, raising=False)
    account = SimpleNamespace(game_path='')
    Globals._adopt_game_path(SimpleNamespace(game_account_config=account))
    assert account.game_path == str(exe)
    account.game_path = 'D:/custom/game.exe'
    Globals._adopt_game_path(SimpleNamespace(game_account_config=account))
    assert account.game_path == 'D:/custom/game.exe'
