"""Deliver OneDragon story actions with physical mouse input only."""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from onedragon.base.controller.input_guard import execution_input_allowed
from src.diagnostics.recorder import record_event
from src.navigation.common import norm_text

if TYPE_CHECKING:
    from zzz_od.application.commission_assistant.story_dialogue import StoryAction


SENSITIVE_OPTIONS = ('购买', '支付', '消耗', '充值', '解锁', '拆解', '销毁', '兑换')


def send_story_action(ctx, screen, action: StoryAction, *, expected_hwnd: int,
                      input_allowed: Callable[[], bool]) -> bool:
    """Click a verified story target, irrespective of the global input mode."""
    if action is None or screen is None:
        return False
    if action.kind not in ('advance', 'option', 'skip', 'confirm_skip', 'menu', 'auto'):
        return False
    point = action.point
    if not (0 <= point.x < 1920 and 0 <= point.y < 1080):
        return False
    if action.kind == 'option' and any(word in norm_text(action.text) for word in SENSITIVE_OPTIONS):
        return False
    controller = ctx.controller
    if controller is None or not expected_hwnd:
        return False

    def delivery_allowed():
        return (ctx.controller is controller and execution_input_allowed() and input_allowed()
                and controller.game_win.get_hwnd() == expected_hwnd
                and controller.game_win.is_win_valid)

    if not delivery_allowed():
        return False
    delivered = controller.click_dialogue_event(
        point, expected_hwnd=expected_hwnd, input_allowed=delivery_allowed) is True
    record_event('dialogue_input', action='click', story_action=action.kind,
                 x=point.x, y=point.y, delivered=delivered)
    return delivered
