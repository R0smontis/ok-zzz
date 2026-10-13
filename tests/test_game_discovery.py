"""Registry fixtures use the observed HoYoPlay schema; never touch real registry."""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from src.runtime import game_discovery as discovery


class Registry:
    HKEY_CURRENT_USER = 'user'
    HKEY_LOCAL_MACHINE = 'machine'
    KEY_READ = 1
    KEY_WOW64_64KEY = 256
    KEY_WOW64_32KEY = 512

    def __init__(self, entries):
        self.entries = entries
        self.accesses = []

    @contextmanager
    def OpenKey(self, root, path, reserved, access):
        self.accesses.append(access)
        key = (root, access & ~self.KEY_READ, path)
        if key not in self.entries and not any(
                item[:2] == key[:2] and item[2].startswith(path + '\\') for item in self.entries):
            raise FileNotFoundError(path)
        yield key

    def EnumKey(self, key, index):
        prefix = key[2] + '\\'
        names = sorted({entry[2][len(prefix):].split('\\')[0] for entry in self.entries
                        if entry[:2] == key[:2] and entry[2].startswith(prefix)})
        if index >= len(names):
            raise OSError('end')
        return names[index]

    def EnumValue(self, key, index):
        items = list(self.entries.get(key, {}).items())
        if index >= len(items):
            raise OSError('end')
        name, value = items[index]
        return name, value, 1


def game(tmp_path, folder):
    directory = tmp_path / folder
    directory.mkdir()
    exe = directory / discovery.GAME_EXE
    exe.write_bytes(b'game fixture')
    return exe


def manager(path=''):
    device = {'device': 'windows', 'full_path': path, 'connected': False}
    return SimpleNamespace(config={'pc_full_path': path}, device_dict={'pc': device},
                           get_preferred_device=lambda: device,
                           get_exe_path=lambda selected: selected.get('full_path'))


def test_cn_global_channels_and_views_are_enumerated_and_deduplicated(tmp_path):
    cn = game(tmp_path, '国服')
    global_exe = game(tmp_path, 'Global')
    registry = Registry({
        ('user', 256, r'SOFTWARE\miHoYo\HYP\1_2\nap_cn'): {'GameInstallPath': str(cn.parent)},
        ('user', 512, r'SOFTWARE\miHoYo\HYP\1_2\nap_cn'): {'GameInstallPath': str(cn.parent)},
        ('machine', 512, r'SOFTWARE\HoYoverse\HYP\different_channel\nap_global'):
            {'GameInstallPath': str(global_exe.parent), 'GameBiz': 'nap_global'},
        ('user', 256, r'SOFTWARE\miHoYo\HYP\1_2\hk4e_cn'): {'GameInstallPath': str(cn.parent)},
    })
    assert discovery.discover_game_paths(registry) == [str(cn), str(global_exe)]
    assert set(registry.accesses) == {257, 513}


def test_uninstall_launcher_stale_path_and_nonstring_values_are_rejected(tmp_path):
    exe = game(tmp_path, 'valid')
    launcher = tmp_path / 'launcher'
    launcher.mkdir()
    (launcher / 'launcher.exe').write_bytes(b'launcher')
    uninstall = 'SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\'
    registry = Registry({
        ('machine', 256, uninstall + 'nap_cn_launcher'): {'InstallLocation': str(launcher)},
        ('machine', 256, uninstall + 'legacy'): {'DisplayName': 'Zenless Zone Zero', 'InstallLocation': str(exe.parent)},
        ('user', 256, r'SOFTWARE\miHoYo\HYP\1_2\nap_cn'): {'GameInstallPath': str(tmp_path / 'gone')},
        ('user', 256, r'SOFTWARE\miHoYo\HYP\1_2\nap_global'): {'GameInstallPath': 123},
    })
    assert discovery.discover_game_paths(registry) == [str(exe)]


def test_missing_and_denied_registry_keys_do_not_abort_discovery():
    registry = Registry({})
    assert discovery.discover_game_paths(registry) == []
    registry.OpenKey = lambda *args: (_ for _ in ()).throw(PermissionError('denied'))
    assert discovery.discover_game_paths(registry) == []


def test_unique_discovery_saves_device_and_account_paths(tmp_path):
    exe = game(tmp_path, 'game')
    device_manager = manager()
    account = SimpleNamespace(game_path='')
    assert discovery.configure_game_path(device_manager, account, discovered_paths=[str(exe)]) == str(exe)
    assert device_manager.config['pc_full_path'] == str(exe)
    assert device_manager.device_dict['pc']['full_path'] == str(exe)
    assert account.game_path == str(exe)


@pytest.mark.parametrize('existing', ['D:/custom/ZenlessZoneZero.exe', 'D:/missing/user-choice.exe'])
def test_existing_user_settings_are_never_overwritten(tmp_path, existing):
    exe = game(tmp_path, 'game')
    device_manager = manager(existing)
    account = SimpleNamespace(game_path='')
    discovery.configure_game_path(device_manager, account, discovered_paths=[str(exe)])
    assert device_manager.config['pc_full_path'] == existing
    assert account.game_path == ''
    account.game_path = existing
    assert discovery.configure_game_path(manager(), account, discovered_paths=[str(exe)]) == existing


def test_multiple_clients_require_manual_choice(tmp_path):
    cn = game(tmp_path, 'cn')
    global_exe = game(tmp_path, 'global')
    device_manager = manager()
    assert discovery.configure_game_path(device_manager, discovered_paths=[str(cn), str(global_exe)]) == ''
    assert device_manager.config['pc_full_path'] == ''


def test_explicit_manual_selection_immediately_updates_existing_device_and_account(tmp_path, monkeypatch):
    from ok import og
    exe = game(tmp_path, 'manual')
    device_manager = manager('D:/previous/ZenlessZoneZero.exe')
    account = SimpleNamespace(game_path='D:/previous/ZenlessZoneZero.exe')
    monkeypatch.setattr(og, 'device_manager', device_manager)
    monkeypatch.setattr(og, 'my_app', SimpleNamespace(_context=SimpleNamespace(game_account_config=account)))
    assert discovery.validate_game_path(discovery.PATH_KEY, str(exe)) == (True, None)
    assert device_manager.config['pc_full_path'] == str(exe)
    assert device_manager.device_dict['pc']['full_path'] == str(exe)
    assert account.game_path == str(exe)


def test_invalid_manual_selection_keeps_current_path(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(discovery, 'apply_selected_game_path', calls.append)
    assert discovery.validate_game_path(discovery.PATH_KEY, str(tmp_path / 'launcher.exe'))[0] is False
    assert calls == []


def test_manual_selection_precedes_unique_registry_result(tmp_path):
    manual = game(tmp_path, 'manual')
    discovered = game(tmp_path, 'discovered')
    device_manager = manager()
    assert discovery.configure_game_path(device_manager, selected_path=str(manual),
        discovered_paths=[str(discovered)]) == str(manual)
    assert device_manager.config['pc_full_path'] == str(manual)
