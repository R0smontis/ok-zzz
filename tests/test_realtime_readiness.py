"""Model, window and hotkey boundaries; all window messages are fake."""
import io
import zipfile
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from src.controls.hotkey_settings import HOTKEYS, sync_hotkeys, validate_hotkey


class MemoryGameConfig(SimpleNamespace):
    def __init__(self, **kwargs):
        super().__init__(**{attr: default for attr, default in HOTKEYS.values()}, **kwargs)
        self.flags = {}

    def get(self, key, default=None):
        return self.flags.get(key, default)

    def update(self, key, value):
        self.flags[key] = value


def test_visible_keys_migrate_existing_account_then_drive_controller():
    game = MemoryGameConfig()
    game.key_dodge = 'ctrl'
    settings = {key: default for key, (_, default) in HOTKEYS.items()}
    settings['Special Attack Key'] = 'v'
    sync_hotkeys(settings, game)
    assert settings['Dodge Key'] == 'ctrl' and game.key_dodge == 'ctrl'
    assert game.key_special_attack == 'v'
    settings['Dodge Key'] = 'shift'  # Explicitly reset after migration.
    sync_hotkeys(settings, game)
    assert game.key_dodge == 'shift'


@pytest.mark.parametrize('value', ['', ' shift', 'mouse_unknown', 'banana', None, 3])
def test_invalid_hotkeys_are_rejected(value):
    assert not validate_hotkey('Dodge Key', value)[0]


def test_global_bridge_passes_visible_keys(monkeypatch):
    from ok import og
    from src.globals import Globals
    game = MemoryGameConfig()
    settings = {key: default for key, (_, default) in HOTKEYS.items()}
    settings['Ultimate Key'] = 'z'
    monkeypatch.setattr(og, 'global_config', SimpleNamespace(get_config=lambda _: settings))
    Globals.__new__(Globals)._sync_game_hotkeys(game)
    assert game.key_ultimate == 'z'


def test_context_syncs_keys_before_creating_and_reusing_controller(monkeypatch):
    from zzz_od.context import zzz_context as context_module
    game = MemoryGameConfig()
    settings = {'Dodge Key': 'ctrl'}
    context = context_module.ZContext.__new__(context_module.ZContext)
    context.__dict__.update(game_config=game, env_config=SimpleNamespace(screenshot_method='auto'),
                            controller=None, _frame_provider=None, _window_provider=lambda: 101,
                            _game_config_sync=lambda config: sync_hotkeys(settings, config))
    fake = SimpleNamespace(game_win=SimpleNamespace(), sync_game_config=Mock())
    constructor = Mock(side_effect=lambda config, **_: fake if config.key_dodge == 'ctrl' else None)
    monkeypatch.setattr(context_module, 'ZzzController', constructor)
    context.init_controller(activate=False)
    assert context.controller is fake
    settings['Dodge Key'] = 'shift'
    context.init_controller(activate=False)
    assert game.key_dodge == 'shift'
    assert fake.sync_game_config.call_count == 2
    fake.sync_game_config.assert_called_with(game, activate=False)


def test_story_controller_creation_does_not_require_or_switch_to_gamepad(monkeypatch):
    from zzz_od.context import zzz_context as module
    context = module.ZContext.__new__(module.ZContext)
    window_provider = lambda: 101
    context.__dict__.update(game_config=MemoryGameConfig(), env_config=SimpleNamespace(screenshot_method='auto'),
                            controller=None, _frame_provider=None, _window_provider=window_provider,
                            _game_config_sync=None)
    controller = SimpleNamespace(game_win=SimpleNamespace(), sync_game_config=Mock())
    constructor = Mock(return_value=controller)
    monkeypatch.setattr(module, 'ZzzController', constructor)
    context.init_controller(activate=False, sync_input=False)
    assert context.controller is controller and controller.game_win.window_provider is window_provider
    controller.sync_game_config.assert_not_called()
    context.init_controller(activate=False)
    constructor.assert_called_once()
    controller.sync_game_config.assert_called_once_with(context.game_config, activate=False)


def test_classifier_keeps_current_results_and_evicts_old_frames():
    from onedragon.yolo.yolov8_onnx_cls import Yolov8Classifier, ClassificationResult, RunContext
    model = Yolov8Classifier.__new__(Yolov8Classifier)
    model.keep_result_seconds = 2
    model.run_result_history = []
    frame = np.zeros((16, 16, 3), np.uint8)
    for timestamp in (100.0, 100.5, 103.0):
        latest = ClassificationResult(frame, 0, timestamp)
        model.record_result(RunContext(frame, timestamp), latest)
        assert model.last_run_result is latest
    assert len(model.run_result_history) == 1


def test_selected_flash_model_is_reloaded_when_its_name_changes(monkeypatch):
    from zzz_od.auto_battle import auto_battle_dodge_context as module
    config = SimpleNamespace(flash_classifier='first', flash_classifier_gpu=False,
                             flash_classifier_backup='backup',
                             get_model_download_base_url=lambda category: 'unused')
    context = module.AutoBattleDodgeContext.__new__(module.AutoBattleDodgeContext)
    context.ctx = SimpleNamespace(model_config=config, env_config=SimpleNamespace(
        is_gh_proxy=False, is_personal_proxy=False))
    context._flash_model = None
    loader = Mock()
    monkeypatch.setattr(module, 'FlashClassifier', loader)
    op = SimpleNamespace(check_dodge_interval=0.02)
    context.init_auto_op(op)
    context.init_auto_op(op)
    assert loader.call_count == 1
    config.flash_classifier = 'second'
    context.init_auto_op(op)
    assert loader.call_count == 2
    assert loader.call_args.kwargs['model_name'] == 'second'


def test_loader_rejects_incomplete_download_and_downloads_missing_backup(tmp_path, monkeypatch):
    from zzz_od.yolo.flash_classifier import FlashClassifier
    attempts = []

    def download(self):
        attempts.append(self.model_name)
        directory = tmp_path / self.model_name
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'model.onnx').write_bytes(b'model')
        if self.model_name == 'backup':
            (directory / 'labels.csv').write_text('0,none', encoding='utf-8')
        return True  # Even a downloader success must be checked for required files.

    monkeypatch.setattr(FlashClassifier, 'download_model', download)
    monkeypatch.setattr(FlashClassifier, 'load_model', Mock())
    model = FlashClassifier(model_download_url='unused', model_name='missing',
                            backup_model_name='backup', model_parent_dir_path=str(tmp_path))
    assert attempts == ['missing', 'backup'] and model.model_name == 'backup'


def test_download_utility_uses_repository_sources(tmp_path, monkeypatch):
    from tools import download_models
    import urllib.request
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('model.onnx', b'model')
        archive.writestr('labels.csv', b'labels')
    called = []

    def open_url(url, **kwargs):
        called.append(url)
        return io.BytesIO(stream.getvalue())

    monkeypatch.setattr(urllib.request, 'urlopen', open_url)
    monkeypatch.setattr(download_models, 'model_dir', lambda category: str(tmp_path / category))
    assert download_models.download('flash_classifier', 'test-model', 'cnb')
    assert called == ['https://cnb.cool/OneDragon-Anything/OneDragon-YOLO/-/releases/download/zzz_model/test-model.zip']
