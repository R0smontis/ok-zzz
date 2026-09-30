# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: one_dragon_qt/overlay/panels/state_panel.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from __future__ import annotations

import html

from onedragon.qt.overlay.panels.resizable_panel import ResizablePanel
from onedragon.qt.widgets.overlay_text_widget import OverlayTextWidget


class StatePanel(ResizablePanel):
    """Overlay run-state panel."""

    def __init__(self, parent=None):
        super().__init__(
            title="Overlay State", panel_name="state_panel",
            min_width=220, min_height=90, parent=parent,
        )
        self.set_title_visible(False)
        self._text_color = "#f2f2f2"

        self._text_widget = OverlayTextWidget(self)
        self._edit_text_widget = self._text_widget
        self.body_layout.addWidget(self._text_widget, 1)
        self._text_widget.set_text_color(self._text_color)
        self._build_edit_toolbar()

    def set_text_color(self, color: str) -> None:
        self._text_color = str(color or "").strip() or "#f2f2f2"
        self._text_widget.set_text_color(self._text_color)

    def update_snapshot(self, items: list[tuple[str, str]]) -> None:
        if self._edit_mode:
            return
        rows: list[str] = []
        for key, value in items:
            safe_key = html.escape(key)
            safe_value = html.escape(value)
            rows.append(
                f"<span style='color:#9ecfff;font-weight:600'>{safe_key}</span>"
                f"<span style='color:#9f9f9f'>: </span>"
                f"<span style='color:{self._text_color}'>{safe_value}</span>"
            )
        self._text_widget.setHtml("<br>".join(rows))
