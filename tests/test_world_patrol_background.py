"""锄大地 start teleports on the controller map (real frame of 职工社区旧址)."""
import json
from pathlib import Path
from types import SimpleNamespace

import cv2

from onedragon.base.geometry.rectangle import Rect
from onedragon.base.operation.operation_round_result import OperationRoundResultEnum as R
from src.navigation.patrol import choose_patrol_point, teleport_icons
from zzz_od.operation.map_transport import MapTransport
from test_lost_void_background_menus import operation

BASE = Path(__file__).parent / 'fixtures/world_patrol'


def frame(name):
    op = operation(MapTransport)
    op.area_name, op.tp_name = '[空洞]职工社区旧址', '职工宿舍西区'
    screen = cv2.cvtColor(cv2.imread(str(BASE / f'{name}.png')), cv2.COLOR_BGR2RGB)
    payload = json.loads((BASE / f'{name}.json').read_text(encoding='utf-8'))
    rows = [SimpleNamespace(data=r['text'], confidence=1, center=Rect(r['rect'][0], r['rect'][1], r['rect'][0] + r['rect'][2],
                                                                      r['rect'][1] + r['rect'][3]).center)
            for r in payload['result']['ocr']]
    op.ctx.ocr_service = SimpleNamespace(get_ocr_result_list=lambda image, rect: [
        r for r in rows if rect.x1 <= r.center.x < rect.x2 and rect.y1 <= r.center.y < rect.y2])
    op.ctx.game_config.get_action_keys = lambda mode: {'move_' + a: 'xbox_ls_' + b for a, b in
                                                       [('a', 'left'), ('d', 'right'), ('w', 'up'), ('s', 'down')]}
    return op, screen


def test_only_unlocked_fans_count_as_teleports():
    _, screen = frame('wp-map-emp')
    icons = teleport_icons(screen)
    assert len(icons) == 1 and abs(icons[0][0] - 362) < 3 and abs(icons[0][1] - 404) < 3


def test_search_starts_with_the_nearest_fan_and_bounds_itself():
    op, screen = frame('wp-map-emp')
    result = choose_patrol_point(op, screen)
    assert result.result == R.RETRY and op._patrol_target_rel == (0., 0.)
    assert op.ctx.controller.btn_press.call_args.args[0].startswith('xbox_ls_')
    op._patrol_steps = 40
    assert choose_patrol_point(op, screen).is_fail
