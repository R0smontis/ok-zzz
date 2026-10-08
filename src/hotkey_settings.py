"""Bridge visible combat hotkeys to the account's controller configuration."""
HOTKEYS = {
    'Dodge Key': ('key_dodge', 'shift'),
    'Normal Attack Key': ('key_normal_attack', 'mouse_left'),
    'Special Attack Key': ('key_special_attack', 'e'),
    'Ultimate Key': ('key_ultimate', 'q'),
    'Switch Agent Key': ('key_switch_next', 'space'),
}


def validate_hotkey(key, value):
    if key.startswith('_'):
        return True, None
    from pynput import keyboard
    if isinstance(value, str) and value == value.strip() and value:
        valid = (len(value) == 1 or value in keyboard.Key.__members__
                 or value.startswith('mouse_') and value[6:] in {'left', 'right', 'middle', 'x1', 'x2'}
                 or value.startswith('numpad_') and len(value) == 8 and value[-1].isdigit())
        if valid:
            return True, None
    return False, '按键无效，请使用单个字符、shift、space、mouse_left 等按键名称'


def sync_hotkeys(settings, game_config):
    """Migrate account keys once, then apply the visible settings at task startup."""
    first_sync = not game_config.get('hotkeys_ui_migrated', False)
    for key, (attribute, default) in HOTKEYS.items():
        value = settings.get(key, default)
        if not validate_hotkey(key, value)[0]:
            raise ValueError(f'{key}：按键无效')
        current = getattr(game_config, attribute)
        if first_sync and value == default and current != default:
            settings[key] = current
            value = current
        if current != value:
            setattr(game_config, attribute, value)
    if first_sync:
        game_config.update('hotkeys_ui_migrated', True)
