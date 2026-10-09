"""Interaction choices shown on the start page and what each means for this program.

ok-script's built-in click/key implementations are not used for game input: every
task and assistant sends input through ZzzController. The selected class only picks
the controller mode, so the list offers exactly the modes that behave differently.
Capture is independent of input focus for resident game assistants.
"""
from ok.device.interaction import PynputInteraction, PostMessageInteraction


class PassiveCapture:
    def should_capture(self):
        return True


class Pynput(PassiveCapture, PynputInteraction):
    label = '前台键鼠 - 切到前台操作，兼容性最好'


class PostMessage(PassiveCapture, PostMessageInteraction):
    label = '窗口消息后台 - 不抢前台，部分游戏界面不接受'


class BackgroundGamepad(PassiveCapture, PostMessageInteraction):
    """Menus use window messages; battle actions use the guarded virtual gamepad."""
    background_gamepad = True
    label = '手柄后台 - 虚拟手柄，后台功能最完整（需 ViGEmBus）'


INTERACTIONS = [Pynput, PostMessage, BackgroundGamepad]


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


def selected_gamepad_mode(manager=None):
    if manager is None:
        from ok import og
        manager = getattr(og, 'device_manager', None)
    interaction = getattr(manager, 'interaction', None)
    return bool(getattr(interaction, 'background_gamepad', False))


def selected_message_mode(manager=None):
    if manager is None:
        from ok import og
        manager = getattr(og, 'device_manager', None)
    return type(getattr(manager, 'interaction', None)) is PostMessage
