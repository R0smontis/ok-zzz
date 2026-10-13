"""Read-only Windows game discovery; all candidates must contain the actual game exe."""
import logging
import os
import threading

log = logging.getLogger(__name__)
GAME_EXE = 'ZenlessZoneZero.exe'
OPTION_NAME = '游戏安装设置'
PATH_KEY = '游戏路径'


def normalize_game_path(value):
    if not isinstance(value, str) or not value.strip():
        return ''
    path = os.path.normpath(os.path.expandvars(value.strip().strip('"')))
    if os.path.isdir(path):
        path = os.path.join(path, GAME_EXE)
    if os.path.basename(path).casefold() != GAME_EXE.casefold():
        return ''
    return os.path.abspath(path) if os.path.isfile(path) else ''


def discover_game_paths(registry=None):
    """Enumerate launcher channels instead of assuming CN/global channel identifiers.

    HoYoPlay's GameInstallPath is observed under HKCU\\Software\\miHoYo\\HYP\\1_2\\nap_cn.
    Uninstall InstallLocation may point at the launcher, so it is never trusted
    without the game executable. No registry writes or disk-wide scans occur.
    """
    if registry is None:
        try:
            import winreg as registry
        except ImportError:
            return []
    found = {}

    def add(value):
        path = normalize_game_path(value)
        if path:
            found.setdefault(os.path.normcase(path).casefold(), path)

    def values(root, path, view):
        try:
            with registry.OpenKey(root, path, 0, registry.KEY_READ | view) as key:
                result = {}
                index = 0
                while True:
                    try:
                        name, value, _ = registry.EnumValue(key, index)
                    except OSError:
                        break
                    result[name.casefold()] = value
                    index += 1
                return result
        except OSError:
            return {}

    def children(root, path, view):
        try:
            with registry.OpenKey(root, path, 0, registry.KEY_READ | view) as key:
                result = []
                index = 0
                while True:
                    try:
                        result.append(registry.EnumKey(key, index))
                    except OSError:
                        break
                    index += 1
                return sorted(result, key=str.casefold)
        except OSError:
            return []

    for root in (registry.HKEY_CURRENT_USER, registry.HKEY_LOCAL_MACHINE):
        for view in (registry.KEY_WOW64_64KEY, registry.KEY_WOW64_32KEY):
            for vendor in children(root, 'SOFTWARE', view):
                if vendor.casefold() not in ('mihoyo', 'hoyoverse', 'cognosphere'):
                    continue
                hyp = 'SOFTWARE\\' + vendor + '\\HYP'
                for channel in children(root, hyp, view):
                    channel_path = hyp + '\\' + channel
                    for game in children(root, channel_path, view):
                        data = values(root, channel_path + '\\' + game, view)
                        biz = str(data.get('gamebiz', game)).casefold()
                        if biz.startswith('nap_'):
                            add(data.get('gameinstallpath'))
            uninstall = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'
            for entry in children(root, uninstall, view):
                data = values(root, uninstall + '\\' + entry, view)
                name = str(data.get('displayname', '')).casefold()
                if entry.casefold().startswith('nap_') or 'zenless' in name or '绝区零' in name:
                    add(data.get('installlocation'))
    return list(found.values())


def _set_manager_path(manager, path):
    if manager is None:
        return
    manager.config['pc_full_path'] = path
    # Existing disconnected entries otherwise retain the stale cached full_path
    # until the next device refresh; the Start Game button reads that entry.
    for device in getattr(manager, 'device_dict', {}).values():
        if device.get('device') == 'windows':
            device['full_path'] = path


def configure_game_path(manager, account=None, selected_path='', discovered_paths=None):
    """Adopt only an unset path. Explicit UI edits use apply_selected_game_path."""
    if account is not None and account.game_path:
        return account.game_path
    path = normalize_game_path(selected_path)
    configured = manager.config.get('pc_full_path', '') if manager is not None else ''
    if not path and configured:
        path = normalize_game_path(configured)
        if not path:
            return ''  # Even a stale user configuration must not be overwritten.
    if not path and manager is not None:
        try:
            device = manager.get_preferred_device()
            if device and device.get('device') == 'windows':
                path = normalize_game_path(manager.get_exe_path(device))
        except (OSError, AttributeError, TypeError, KeyError):
            pass
    if not path:
        candidates = discover_game_paths() if discovered_paths is None else discovered_paths
        valid = {normalize_game_path(candidate) for candidate in candidates}
        valid.discard('')
        if len(valid) != 1:
            return ''  # Multiple clients require an explicit user choice.
        path = valid.pop()
    if not configured:
        _set_manager_path(manager, path)
    if account is not None:
        account.game_path = path
    return path


def apply_selected_game_path(path):
    """Explicit user selection takes effect immediately for closed-game startup."""
    from ok import og
    _set_manager_path(getattr(og, 'device_manager', None), path)
    context = getattr(getattr(og, 'my_app', None), '_context', None)
    if context is not None:
        context.game_account_config.game_path = path


def validate_game_path(key, value):
    if key != PATH_KEY or not value:
        return True, None
    path = normalize_game_path(value)
    if not path:
        return False, '请选择包含 ZenlessZoneZero.exe 的目录或游戏程序本身'
    apply_selected_game_path(path)
    return True, None


def install_game_discovery():
    """Defer until the Qt loop and device manager exist; scan on a worker once.

    Return the timer to keep it owned by Globals. Registry results are applied on
    the GUI thread, and recheck user configuration after scanning to avoid races.
    """
    from PySide6.QtCore import QCoreApplication, QTimer
    from ok import og
    timer = QTimer(QCoreApplication.instance())
    timer.setInterval(100)
    result = []
    finished = threading.Event()
    started = False

    def scan():
        try:
            result.extend(discover_game_paths())
        except Exception:
            log.exception('游戏目录发现失败，请在全局设置中手动选择游戏路径')
        finally:
            finished.set()

    def tick():
        nonlocal started
        manager = getattr(og, 'device_manager', None)
        if manager is None:
            return
        settings = og.global_config.get_config(OPTION_NAME)
        selected = settings.get(PATH_KEY, '')
        if selected:
            path = normalize_game_path(selected)
            if path:
                _set_manager_path(manager, path)
            timer.stop()
            return
        context = getattr(getattr(og, 'my_app', None), '_context', None)
        account = getattr(context, 'game_account_config', None)
        if account is not None and account.game_path:
            timer.stop()
            return
        if manager.config.get('pc_full_path'):
            timer.stop()
            return
        if not started:
            started = True
            threading.Thread(target=scan, name='GameDirectoryDiscovery', daemon=True).start()
        if finished.is_set():
            timer.stop()
            path = configure_game_path(manager, discovered_paths=result)
            if path:
                settings[PATH_KEY] = path
                log.info('已发现并保存游戏路径：%s', path)
            else:
                log.info('未发现唯一游戏目录，请在全局设置 → 游戏安装设置 → 游戏路径中选择')

    timer.timeout.connect(tick)
    timer.start()
    return timer
