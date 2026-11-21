"""Read live challenge energy before considering a selected refill source."""
import re

from onedragon.base.geometry.rectangle import Rect


_CHARGE_PAIR = re.compile(r'([0-9]+)\s*[/／]\s*([0-9]+)')


def read_battle_charge(operation, screen_name, remaining_area, required_area=None):
    loader = operation.ctx.screen_loader
    rect = loader.get_area(screen_name, remaining_area).rect
    if required_area is not None:
        cost_rect = loader.get_area(screen_name, required_area).rect
        # The footer centres the whole ratio; its two numbers move with digit count.
        rect = Rect(rect.x1 - 30, rect.y1, cost_rect.x2 + 75, cost_rect.y2)
    rows = operation.ctx.ocr_service.get_ocr_result_list(
        image=operation.last_screenshot, rect=rect)
    pairs = set()
    for row in rows:
        match = _CHARGE_PAIR.fullmatch(row.data.strip())
        if match is not None:
            remaining, required = map(int, match.groups())
            if required > 0:
                pairs.add((remaining, required))
    return next(iter(pairs)) if len(pairs) == 1 else None


def remember_battle_charge(operation, screen_name, remaining_area, required_area=None,
                           *, default_required: int) -> int:
    required = getattr(operation, '_battle_charge_cost', None) or default_required
    reading = read_battle_charge(operation, screen_name, remaining_area, required_area)
    if reading is not None:
        remaining, cost = reading
        operation.charge_plan_app.battery_charge = remaining
        if required_area is not None:
            required = cost
    operation._battle_charge_cost = required
    return required


def consume_battle_charge(operation):
    app = getattr(operation, 'charge_plan_app', None)
    cost = getattr(operation, '_battle_charge_cost', None)
    if app is not None and cost is not None:
        app.record_battle_charge(cost)
