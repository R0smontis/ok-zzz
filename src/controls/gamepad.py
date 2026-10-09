"""One place that turns an Xbox button name into the configured virtual pad's key.

Callers name buttons by their Xbox label ('a', 'b', 'start', 'dpad_up', 'ls_slow_left' ...);
DS4 uses a fixed renaming of the face/shoulder/system buttons and the same names otherwise.
"""
_DS4_NAMES = {'a': 'cross', 'b': 'circle', 'x': 'square', 'y': 'triangle',
              'lb': 'l1', 'rb': 'r1', 'lt': 'l2', 'rt': 'r2',
              'start': 'options', 'back': 'share'}


def is_ds4(ctx) -> bool:
    return ctx.game_config.background_gamepad_type == 'ds4'


def pad_key(ctx, button: str) -> str:
    """'b' -> 'xbox_b' or 'ds4_circle' for the account's configured pad type."""
    if is_ds4(ctx):
        return 'ds4_' + _DS4_NAMES.get(button, button)
    return 'xbox_' + button


def press(ctx, button: str, duration: float = .12) -> None:
    ctx.controller.btn_press(pad_key(ctx, button), press_time=duration)
