"""实机矩阵截图：页签、焦点和主战槽必须同时可信，未知角色不能当作空队伍。"""
import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import pytest

from onedragon.base.geometry.rectangle import Rect
from onedragon.base.screen.template_loader import TemplateLoader
from src.navigation.common import in_rect
from zzz_od.application.hollow_zero.lost_void.matrix_screen import (
    detail_visible, main_agents, read_team_page,
)

FIXTURES = Path(__file__).parent / 'fixtures' / 'lost_void'
TEMPLATES = TemplateLoader()


def frame(name):
    screen = cv2.cvtColor(cv2.imread(str(FIXTURES / f'{name}.png')), cv2.COLOR_BGR2RGB)
    data = json.loads((FIXTURES / f'{name}.json').read_text(encoding='utf-8'))
    rows = [SimpleNamespace(data=row['text'], center=Rect(
        row['rect'][0], row['rect'][1], row['rect'][0] + row['rect'][2],
        row['rect'][1] + row['rect'][3]).center) for row in data['result']['ocr']]
    op = SimpleNamespace(last_screenshot=screen, rows=rows)
    op.ctx = SimpleNamespace(template_loader=TEMPLATES, ocr_service=SimpleNamespace(
        get_ocr_result_list=lambda image, rect: [row for row in op.rows if in_rect(row.center, rect)]))
    return op


@pytest.mark.parametrize(('name', 'mode', 'focused_point'), [
    ('matrix-team-empty', 'agents', None),
    ('matrix-preset-tab', 'preset', None),
    ('matrix-preset-focused', 'preset', (260, 300)),
    ('matrix-preset-selected', 'preset', (260, 300)),
    ('matrix-support-panel', 'support', None),
    ('matrix-support-focused', 'support', (260, 190)),
    ('matrix-support-selected', 'support', (260, 190)),
    ('matrix-agent-focused', 'agents', (415, 456)),
    ('matrix-three-agents', 'agents', (570, 256)),
    ('matrix-agent-scroll', 'agents', (570, 950)),
    ('matrix-agent-deep', 'agents', (570, 950)),
])
def test_actual_page_and_unique_card_focus(name, mode, focused_point):
    op = frame(name)
    page = read_team_page(op)
    assert page.mode == mode
    if focused_point is None:
        assert page.focus is None  # Yellow hair, slot circles and active tabs are not list focus.
    else:
        from onedragon.base.geometry.point import Point
        assert page.focus is not None and in_rect(Point(*focused_point), page.focus)


@pytest.mark.parametrize(('name', 'expected'), [
    ('matrix-team-empty', []),
    ('matrix-preset-selected', ['claret', 'roxy', 'rina']),
    ('matrix-support-selected', ['claret', 'roxy', 'rina']),
    ('matrix-main-empty', []),
    ('matrix-two-agents', ['rina', 'manato']),
    ('matrix-three-agents', ['rina', 'manato', 'caesar_king']),
    ('matrix-agent-scroll', ['rina', 'manato', 'caesar_king']),
    ('matrix-agent-deep', ['rina', 'manato', 'caesar_king']),
])
def test_main_slots_use_real_avatar_templates_in_slot_order(name, expected):
    op = frame(name)
    assert main_agents(op, read_team_page(op)) == expected


def test_unrecognized_or_misread_main_slots_are_not_an_empty_team():
    op = frame('matrix-three-agents')
    op.rows = [row for row in op.rows if row.data != '主战']
    assert main_agents(op, read_team_page(op)) is None
    op = frame('matrix-three-agents')
    op.last_screenshot[170:300, 1030:1430] = 0
    assert main_agents(op, read_team_page(op)) is None


def test_detail_accepts_actual_split_next_step_ocr_but_not_periodic_or_team_page():
    assert detail_visible(frame('matrix-detail'))
    for name in ('matrix-periodic', 'matrix-team-empty', 'matrix-support-selected'):
        op = frame(name)
        assert not detail_visible(op)
    for name in ('matrix-periodic', 'matrix-detail'):
        assert read_team_page(frame(name)) is None
