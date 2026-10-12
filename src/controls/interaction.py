"""The single foreground/background switch shown on the start page.

ok-script's built-in click/key implementations are not used for game input: every
task and assistant sends input through ZzzController. The selected class is the only
input setting: applications, 一条龙 and all resident assistants follow it.
Capture is independent of input focus for resident game assistants.
"""
from ok.device.interaction import PynputInteraction, PostMessageInteraction


class PassiveCapture:
    def should_capture(self):
        return True


class BackgroundGamepad(PassiveCapture, PostMessageInteraction):
    """Menus use window messages; game input uses the guarded virtual gamepad."""
    background_gamepad = True
    label = '后台模式 - 虚拟手柄，不抢前台、不移动鼠标（需 ViGEmBus）'


class Pynput(PassiveCapture, PynputInteraction):
    label = '前台模式 - 键鼠操作，运行时切到游戏前台'


# The first entry is also where saved choices that no longer exist (窗口消息后台,
# ForegroundPostMessage, PyDirect) fall back to: background never takes over the mouse.
INTERACTIONS = [BackgroundGamepad, Pynput]

BACKGROUND_UNAVAILABLE = '后台模式需要虚拟手柄：请安装 ViGEmBus 驱动，或在首页切换到前台模式'

# Bumped when the meaning of the saved start page choice changes.
INTERACTION_SCHEME = 2


def migrate_saved_interaction(folder='configs'):
    """Once per scheme change, start in 后台模式 whatever the old start page choice was.

    Before scheme 2 the start page only steered the resident assistants: tasks and 一条龙
    ran in the background whatever it said, so many saved configs still hold 'Pynput'.
    Read unchanged, that would now move every task to the foreground. ok-script drops
    unknown keys from devices.json, so the marker lives in its own file; a choice made
    after the migration is kept.
    """
    import json
    import os
    marker = os.path.join(folder, 'interaction_scheme.json')
    try:
        with open(marker, encoding='utf-8') as fp:
            if json.load(fp).get('scheme', 0) >= INTERACTION_SCHEME:
                return False
    except (OSError, ValueError, AttributeError):
        pass
    devices = os.path.join(folder, 'devices.json')
    changed = False
    try:
        with open(devices, encoding='utf-8') as fp:
            data = json.load(fp)
        if isinstance(data, dict) and data.get('interaction') != BackgroundGamepad.__name__:
            data['interaction'] = BackgroundGamepad.__name__
            with open(devices, 'w', encoding='utf-8') as fp:
                json.dump(data, fp, ensure_ascii=False, indent=4)
            changed = True
    except (OSError, ValueError):
        pass  # No saved choice yet: the first entry of INTERACTIONS is the default.
    os.makedirs(folder, exist_ok=True)
    with open(marker, 'w', encoding='utf-8') as fp:
        json.dump({'scheme': INTERACTION_SCHEME}, fp)
    return changed


def install_interaction_labels():
    """Show this program's meaning for each choice instead of ok-script's generic text."""
    from ok.ui.qt.start.SelectInteractionListView import SelectInteractionListView
    if getattr(SelectInteractionListView, '_zzz_labels', False):
        return
    labels = {cls.__name__: cls.label for cls in INTERACTIONS}

    def tr(self, text, *args):
        # QObject.tr is bound per instance by PySide; call it on the instance for other texts.
        return labels.get(text) or super(SelectInteractionListView, self).tr(text, *args)

    SelectInteractionListView.tr = tr
    SelectInteractionListView._zzz_labels = True


def background_mode_selected(manager=None):
    """Whether the start page switch is set to 后台模式."""
    if manager is None:
        from ok import og
        manager = getattr(og, 'device_manager', None)
    # The class follows the start page at once; the instance is only replaced on reconnect.
    selected = getattr(manager, 'win_interaction_class', None) or getattr(manager, 'interaction', None)
    return bool(getattr(selected, 'background_gamepad', False))
