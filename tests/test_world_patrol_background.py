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


def frame(name, cls=MapTransport):
    op = operation(cls)
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
    op.last_screenshot = screen
    return op, screen


def test_only_unlocked_fans_count_as_teleports():
    _, screen = frame('wp-map-emp')
    icons = teleport_icons(screen)
    assert len(icons) == 1 and abs(icons[0][0] - 362) < 3 and abs(icons[0][1] - 404) < 3


def test_search_starts_with_the_nearest_fan_and_bounds_itself():
    op, screen = frame('wp-map-emp')
    result = choose_patrol_point(op, screen)
    assert result.result == R.RETRY and op._patrol_aim['name'] is None
    assert op.ctx.controller.btn_press.call_args.args[0].startswith('xbox_ls_')
    op._patrol_steps = 40
    assert choose_patrol_point(op, screen).is_fail


def test_other_icon_detail_panel_is_a_map_and_the_search_moves_on():
    # Live 2026-10-17: the cursor stopped on a 「物资收集点」; its panel shows 已完成, not 前往/追踪.
    # Treating that as an unknown screen froze the search until the 180 s stall guard.
    from src.navigation.map import map_state
    op, screen = frame('wp-collection-detail')
    op.area_name, op.tp_name = '[空洞]中央制造区', '中央制造区入口'
    state = map_state(op, screen)
    assert state is not None and state['detail'] and not state['info'] and not state['can_go']
    assert state['point'] == '物资收集点' and state['title'] == '[空洞]中央制造区'
    result = choose_patrol_point(op, screen)
    assert result.result == R.RETRY and result.status != '未核验地图，暂停传送点搜索'
    assert op.ctx.controller.btn_press.call_args.args[0].startswith('xbox_ls_')
    assert any(k['name'] == '物资收集点' for k in op._patrol_known)


def test_area_info_panel_is_not_mistaken_for_an_icon_detail():
    from src.navigation.map import map_state
    op, screen = frame('central-map')
    state = map_state(op, screen)
    assert state['info'] and not state['detail']


def with_sub_area(op, name='大楼西侧'):
    names = ('物流仓储区', '顶楼', '大楼西侧', '大楼东侧')
    parent = SimpleNamespace(sub_area_list=[SimpleNamespace(area_name=n) for n in names])
    op.area_name = '[空洞]中央制造区'
    op.target_area = SimpleNamespace(area_name=name, parent_area=parent)
    return op


def test_ls_opens_sub_area_list_on_verified_parent_map():
    from src.navigation.patrol import open_sub_area
    op, screen = frame('central-map')
    with_sub_area(op)
    assert open_sub_area(op, screen).result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_l_thumb', press_time=.12)
    op, screen = frame('wp-map-emp')
    with_sub_area(op)
    assert open_sub_area(op, screen).result == R.RETRY
    op.ctx.controller.btn_press.assert_not_called()


def test_sub_area_list_moves_then_confirms_without_assuming_success():
    from src.navigation.patrol import choose_sub_area, open_sub_area, sub_area_state
    op, screen = frame('central-subareas')
    with_sub_area(op)
    state = sub_area_state(op, screen)
    assert state['current'] == '大楼东侧'
    assert [name for name, _ in state['choices']] == ['物流仓储区', '顶楼', '大楼西侧', '大楼东侧']
    assert [name for name, _ in state['focused']] == ['大楼东侧']
    assert open_sub_area(op, screen).is_success
    assert choose_sub_area(op, screen).result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_dpad_up', press_time=.12)
    op, screen = frame('central-west-focus')
    with_sub_area(op)
    assert choose_sub_area(op, screen).result == R.WAIT
    op.ctx.controller.btn_press.assert_called_once_with('xbox_a', press_time=.12)
    op, screen = frame('central-west-arrived')
    with_sub_area(op)
    assert choose_sub_area(op, screen).is_success
    assert open_sub_area(op, screen).status == '无需选择'
    op.ctx.controller.btn_press.assert_not_called()


def test_sub_area_open_and_confirm_are_bounded():
    from src.navigation.patrol import choose_sub_area, open_sub_area
    for name, action in (('central-map', open_sub_area), ('central-west-focus', choose_sub_area)):
        op, screen = frame(name)
        with_sub_area(op)
        for _ in range(3):
            assert action(op, screen).result == R.WAIT
        assert action(op, screen).is_fail
        assert op.ctx.controller.btn_press.call_count == 3


def test_unknown_sub_area_or_missing_focus_sends_no_input():
    from src.navigation.patrol import choose_sub_area
    op, screen = frame('central-subareas')
    with_sub_area(op, '不存在的楼层')
    assert choose_sub_area(op, screen).is_fail
    op.ctx.controller.btn_press.assert_not_called()
    with_sub_area(op)
    screen[600:975, 50:415] = 0
    assert choose_sub_area(op, screen).result == R.RETRY
    op.ctx.controller.btn_press.assert_not_called()


def test_teleport_confirm_rechecks_sub_area(monkeypatch):
    from unittest.mock import Mock
    import src.navigation.map as nav
    from zzz_od.application.world_patrol.operation.transport_by_3d_map import TransportBy3dMap
    confirm = Mock(return_value='verified')
    monkeypatch.setattr(nav, 'confirm_point', confirm)
    op, screen = frame('central-west-arrived', TransportBy3dMap)
    with_sub_area(op, '大楼东侧')
    assert op.click_go().is_fail
    confirm.assert_not_called()
    with_sub_area(op)
    assert op.click_go() == 'verified'
    confirm.assert_called_once_with(op, screen)


def test_region_search_uses_its_own_step_budget(monkeypatch):
    import src.navigation.map as nav
    from unittest.mock import Mock
    from zzz_od.application.world_patrol.operation.transport_by_3d_map import TransportBy3dMap
    op, screen = frame('wp-map-emp', TransportBy3dMap)
    choose = Mock(return_value=op.round_retry('手柄滚动区域', wait=.6))
    monkeypatch.setattr(nav, 'choose_area', choose)
    assert op.choose_area().result == R.WAIT
    choose.assert_called_once_with(op, screen)


def test_sub_area_does_not_accept_selected_region_before_map_title_updates(monkeypatch):
    import src.navigation.patrol as nav
    from unittest.mock import Mock
    op, screen = frame('central-map')
    with_sub_area(op)
    monkeypatch.setattr(nav, 'map_state', Mock(return_value={
        'title': '[空洞]辉瓷加工基地', 'selected': op.area_name, 'info': True}))
    assert nav.open_sub_area(op, screen).result == R.RETRY
    op.ctx.controller.btn_press.assert_not_called()


def test_sub_area_check_does_not_reject_verified_teleport_transition():
    from zzz_od.application.world_patrol.operation.transport_by_3d_map import TransportBy3dMap
    op, screen = frame('central-west-arrived', TransportBy3dMap)
    with_sub_area(op)
    op._background_go_requests = 1
    op.last_screenshot = screen * 0  # Loading after a verified destination confirmation.
    op.ctx.ocr_service.get_ocr_result_list = lambda image, rect: []
    assert op.click_go().is_success
    op.ctx.controller.btn_press.assert_not_called()


def test_missing_map_before_first_confirmation_sends_no_input():
    from zzz_od.application.world_patrol.operation.transport_by_3d_map import TransportBy3dMap
    op, screen = frame('central-map', TransportBy3dMap)
    with_sub_area(op)
    op.last_screenshot = None
    assert op.click_go().is_fail
    op.ctx.controller.btn_press.assert_not_called()


def _research_center_op():
    import yaml
    from onedragon.base.geometry.point import Point
    rows = yaml.safe_load((Path(__file__).parents[1] / 'assets/game_data/world_patrol/lemnian_hollow/'
                           'former_research_center/icon.yml').read_text(encoding='utf-8'))
    icons = [SimpleNamespace(icon_name=r['icon_name'], lm_pos=Point(*r['lm_pos'])) for r in rows]
    op = SimpleNamespace(large_map=SimpleNamespace(icon_list=icons))
    op.target_icon = next(i for i in icons if i.icon_name == '科研院东侧')
    return op


def test_large_map_positions_predict_the_target_from_identified_fans():
    from src.navigation.patrol import predict_target
    op = _research_center_op()
    # Live: 二楼平台 (0,0), 一楼广场 (224,-202), 科研院东侧 found at (284,-395).
    goal = predict_target(op, {'二楼平台': (0., 0.), '一楼广场': (224., -202.)})
    assert abs(goal[0] - 284) < 60 and abs(goal[1] + 395) < 120
    assert predict_target(op, {}) is None


class PatrolMap:
    """A simulated 3D map: fans at fixed map positions, pans follow the stick (imprecisely)."""

    def __init__(self, fans, offset=(0., 0.), gain=.85, bounds=((-2000, 2000), (-2000, 2000))):
        self.fans, self.offset, self.gain, self.bounds = fans, list(offset), gain, bounds

    def screen(self):
        return [(x + self.offset[0], y + self.offset[1], name) for name, (x, y) in self.fans.items()]

    def icons(self, _):
        return [(x, y) for x, y, _ in self.screen() if 120 < x < 1380 and 100 < y < 980]

    def state(self, op, _):
        under = next((n for x, y, n in self.screen() if abs(x - 695) < 25 and abs(y - 540) < 25), None)
        return dict(info=False, detail=under is not None, title=op.area_name, point=under or '',
                    can_go=True, selected=None, rows=[])

    def pan(self, op):
        expected = op._background_expected_point
        x, y = op._background_steered
        for axis, (low, high) in enumerate(self.bounds):
            moved = (expected[axis] - (x, y)[axis]) * self.gain
            self.offset[axis] = min(high, max(low, self.offset[axis] + moved))


def simulate(monkeypatch, sim, target, lm=None, rounds=40):
    from src.navigation import patrol
    real_steer = patrol.steer_to

    def steer(op, state, x, y):
        result = real_steer(op, state, x, y)
        op._background_steered = (x, y)
        sim.pan(op)
        return result

    monkeypatch.setattr(patrol, 'steer_to', steer)
    monkeypatch.setattr(patrol, 'teleport_icons', sim.icons)
    monkeypatch.setattr(patrol, 'map_state', sim.state)
    op, screen = frame('wp-map-emp')
    op.tp_name = target
    if lm is not None:
        from onedragon.base.geometry.point import Point
        icons = [SimpleNamespace(icon_name=n, lm_pos=Point(*pos)) for n, pos in lm.items()]
        op.large_map = SimpleNamespace(icon_list=icons)
        op.target_icon = next(i for i in icons if i.icon_name == target)
    for _ in range(rounds):
        result = choose_patrol_point(op, screen)
        if result.result != R.RETRY and result.result != R.WAIT:
            return op, result
    return op, result


def test_large_map_guidance_reaches_a_target_beyond_the_view(monkeypatch):
    # Map positions = large-map positions scaled like the live 3D map; the target is 1500 px away.
    lm = {'A': (0, 0), 'B': (200, -150), 'C': (700, -400), 'D': (1100, -700), '目标': (1400, -1000)}
    fans = {n: (695 + 1.13 * x, 540 + .75 * y) for n, (x, y) in lm.items()}
    op, result = simulate(monkeypatch, PatrolMap(fans), '目标', lm)
    assert result.is_success, result.status


def test_map_edge_does_not_drift_into_endless_rereads(monkeypatch):
    # Live: the map stopped at its edge and the same fan was read nine times, each 280 px "further".
    fans = {'物流通道': (695, 540), '远处': (695, -900)}
    sim = PatrolMap(fans, bounds=((-50, 50), (-60, 60)))
    op, result = simulate(monkeypatch, sim, '不存在')
    assert result.is_fail
    assert sum(1 for k in op._patrol_known if k['name'] == '物流通道') == 1


def test_foreshortened_map_still_converges_with_fitted_scale(monkeypatch):
    lm = {'A': (0, 0), 'B': (300, 200), 'C': (-250, 500), 'D': (400, 900), '目标': (600, 1300)}
    fans = {n: (695 + 1.1 * x, 540 + .58 * y) for n, (x, y) in lm.items()}
    _, result = simulate(monkeypatch, PatrolMap(fans, gain=1.1), '目标', lm)
    assert result.is_success, result.status


def test_without_large_map_visits_visible_fans_nearest_first(monkeypatch):
    fans = {'A': (700, 545), 'B': (900, 500), 'C': (300, 800), '目标': (1200, 300)}
    _, result = simulate(monkeypatch, PatrolMap(fans), '目标')
    assert result.is_success, result.status


def test_a_fan_that_never_opens_its_panel_is_dropped_with_its_duplicates(monkeypatch):
    # Live: a template match near the cursor never opened a panel; the search circled it 30 times.
    class Ghost(PatrolMap):
        def state(self, op, screen):
            result = super().state(op, screen)
            if result['point'] == '幽灵':
                result.update(detail=False, point='')
            return result

    fans = {'幽灵': (720, 560), '目标': (1100, 300)}
    _, result = simulate(monkeypatch, Ghost(fans), '目标')
    assert result.is_success, result.status


def test_visible_fan_measurement_wins_over_drifting_prediction(monkeypatch):
    from unittest.mock import Mock
    from src.navigation import patrol
    op, screen = frame('wp-map-emp')
    aim = dict(rel=(730., 580.), name=None, tries=0)
    op._patrol_aim = aim
    measured = (750., 550.)
    monkeypatch.setattr(patrol, 'map_state', lambda *_: dict(
        info=False, detail=False, title=op.area_name, point='', can_go=False, selected=None))
    monkeypatch.setattr(patrol, 'teleport_icons', lambda _: [measured])
    monkeypatch.setattr(patrol, '_track', lambda *_: ((0., 0.), [aim]))
    steer = Mock(return_value=op.round_retry('steering'))
    monkeypatch.setattr(patrol, '_steer', steer)
    choose_patrol_point(op, screen)
    assert steer.call_args.args[2:] == measured


class StickMap(PatrolMap):
    """Pans by the real press: distance = press time × stick speed (live: slow ≈ 210 / 180 px/s)."""

    SPEED = {'x': 2800., 'y': 1400., 'x_slow': 210., 'y_slow': 180.}
    SIGN = {'left': (1, 'x'), 'right': (-1, 'x'), 'up': (1, 'y'), 'down': (-1, 'y')}

    def pan(self, op):
        call = op.ctx.controller.btn_press.call_args
        key, seconds = call.args[0], call.kwargs['press_time']
        sign, axis = self.SIGN[key.rsplit('_', 1)[1]]
        speed = self.SPEED[axis + ('_slow' if '_slow_' in key else '')]
        index = 0 if axis == 'x' else 1
        self.offset[index] += sign * speed * seconds


def test_weak_slow_stick_still_brings_a_near_fan_under_the_cursor(monkeypatch):
    # Live 2026-10-17: fans stalled ~35 px from the cursor because slow presses were sized for a
    # stick five times faster; each fan was dropped after six steers and no panel ever opened.
    fans = {'目标': (775, 610)}
    op, result = simulate(monkeypatch, StickMap(fans), '目标')
    assert result.is_success, result.status
    assert op._background_map_velocity['x_slow'] < 260 and op._background_map_velocity['y_slow'] < 220
