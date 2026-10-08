"""Capture is independent of input focus for resident game assistants.

Keep the framework's persisted backend names and foreground input checks.
Battle input is delivered by ZzzController, whose guard pauses keyboard/mouse
when the game loses focus. Virtual gamepad input still needs fresh captures.
"""
from ok.device.interaction import (
    PynputInteraction, PostMessageInteraction, ForegroundPostMessageInteraction,
    PyDirectInteraction,
)


class PassiveCapture:
    def should_capture(self):
        return True


class Pynput(PassiveCapture, PynputInteraction):
    pass


class PostMessage(PassiveCapture, PostMessageInteraction):
    pass


class ForegroundPostMessage(PassiveCapture, ForegroundPostMessageInteraction):
    pass


class PyDirect(PassiveCapture, PyDirectInteraction):
    pass


class BackgroundGamepad(PassiveCapture, PostMessageInteraction):
    """Menus use window messages; battle actions use the guarded virtual gamepad."""
    background_gamepad = True


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
