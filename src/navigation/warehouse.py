"""Verified warehouse tab navigation; never treats a posted mouse click as success."""
from onedragon.base.geometry.rectangle import Rect
from src.controls.gamepad import press as pad
from src.navigation.common import norm_text, ocr_rows

TABS = ('仓库-音擎仓库', '仓库-驱动仓库', '仓库-材料道具')
TITLES = ('音擎仓库', '驱动仓库', '材料道具')


def warehouse_tab(op, screen, target):
    # Only intercept plain warehouse destinations. Dismantle has a separate,
    # destructive confirmation flow and must not be inferred from the tab title.
    if target not in TABS:
        return None
    rows = ocr_rows(op, screen, Rect(40, 100, 650, 180))
    selected = [title for title in TITLES if any(norm_text(r.data).startswith(title) for r in rows)]
    if len(selected) != 1:
        return op.round_retry('未核验仓库标题，未操作', wait=.6)
    current = TABS[TITLES.index(selected[0])]
    if current == target:
        return op.round_success(f'已核验{selected[0]}')
    prior, unchanged, total = getattr(op, '_warehouse_tab_steps', (None, 0, 0))
    unchanged = unchanged + 1 if current == prior else 0
    if unchanged >= 3 or total >= 5:
        return op.round_fail(f'手柄切换仓库未生效：{selected[0]} → {target}')
    pad(op.ctx, 'rb' if TABS.index(current) < TABS.index(target) else 'lb')
    op._warehouse_tab_steps = (current, unchanged, total + 1)
    return op.round_wait(f'手柄切换仓库：{selected[0]} → {target}', wait=1)
