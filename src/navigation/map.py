"""Closed-loop navigation of the current controller map; no desktop pointer input."""
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
import cv2
import numpy as np
from onedragon.base.geometry.rectangle import Rect
from onedragon.utils import os_utils


def _text(value):
    return str(value).replace(' ', '').replace('「', '').replace('」', '')


def _rows(op, screen, rect):
    rows = op.ctx.ocr_service.get_ocr_result_list(image=screen, rect=rect)
    return rows if isinstance(rows, (list, tuple)) else []


def map_state(op, screen):
    if not isinstance(screen, np.ndarray) or screen.shape[:2] != (1080, 1920):
        return None
    rows = _rows(op, screen, Rect(1390, 15, 1870, 965))
    words = [_text(row.data) for row in rows]
    if '快捷导航' not in words:
        return None
    info = '区域信息' in words and '区域切换' in words
    detail = '前往' in words or '追踪' in words
    if not info and not detail:
        return None
    title_rows = _rows(op, screen, Rect(170, 20, 550, 78))
    title = min((r for r in title_rows if any('\u4e00' <= c <= '\u9fff' for c in str(r.data))),
                key=lambda r: abs(r.center.x - 225) + abs(r.center.y - 50), default=None)
    # Read the name separately so the adjacent icon cannot become part of OCR.
    point_rows = _rows(op, screen, Rect(1480, 125, 1800, 180)) if detail else []
    point = ''.join(_text(r.data) for r in point_rows if r.center.y < 180)
    selected = None
    part = screen[330:955, 1395:1850]
    color = ((part[:, :, 0] > 125) & (part[:, :, 1] > 150) & (part[:, :, 2] < 105)).astype(np.uint8)
    contours, _ = cv2.findContours(color, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = [cv2.boundingRect(c) for c in contours]
    boxes = [b for b in boxes if b[2] > 370 and 40 < b[3] < 105]
    if info and len(boxes) == 1:
        y = 330 + boxes[0][1] + boxes[0][3] / 2
        selected = next((_text(r.data) for r in rows if abs(r.center.y-y) < 24 and r.center.x < 1720), None)
    title_text = _text(title.data).replace('绿像店', '录像店') if title else ''
    return dict(info=info, detail=detail, title=title_text,
                point=point, can_go='前往' in words, selected=selected, rows=rows)


def _press(op, button, duration=.12):
    ds4 = op.ctx.game_config.background_gamepad_type == 'ds4'
    names = {'back': 'ds4_circle' if ds4 else 'xbox_b',
             'confirm': 'ds4_cross' if ds4 else 'xbox_a'}
    key = names.get(button) or ('ds4_' if ds4 else 'xbox_') + button
    op.ctx.controller.btn_press(key, press_time=duration)


def _match(value, target):
    return _text(value) == _text(target) or SequenceMatcher(None, _text(value), _text(target)).ratio() >= .85


def _area_match(state, target):
    if state['info'] and state['selected'] and _match(state['selected'], target):
        return True
    title = state['title']
    # Small stylized three-character area titles regularly lose one glyph.
    # Destination identity is still independently verified before pressing A.
    return _match(title, target) or (len(title) == len(target) == 3
                                    and SequenceMatcher(None, title, target).ratio() >= 2/3)


def choose_area(op, screen):
    state = map_state(op, screen)
    if state is None:
        return op.round_retry('未核验新版区域地图，未操作', wait=.5)
    current = state['selected'] or state['title']
    if _match(current, op.area_name):
        return op.round_success(f'已核验地图区域：{op.area_name}')
    if state['detail']:
        _press(op, 'back')
        return op.round_retry('关闭传送点详情，等待区域列表', wait=.8)
    visible = [(r.center.y, _text(r.data)) for r in state['rows'] if 380 < r.center.y < 950]
    target_y = next((y for y, name in visible if _match(name, op.area_name)), None)
    current_y = next((y for y, name in visible if _match(name, current)), None)
    if target_y is not None and current_y is not None:
        direction = 'up' if target_y < current_y else 'down'
    else:
        # Current controller map groups/ordering differ from the old horizontal
        # map data. Keep one search direction until the target is visible.
        direction = getattr(op, '_background_region_direction', 'up')
    prior, unchanged, total = getattr(op, '_background_region_search', (None, 0, 0))
    unchanged = unchanged + 1 if current == prior else 0
    if unchanged >= 3 and target_y is None and not getattr(op, '_background_region_reversed', False):
        direction = 'down' if direction == 'up' else 'up'
        op._background_region_reversed = True
        unchanged = 0
    elif unchanged >= 3 or total >= 45:
        return op.round_fail(f'后台区域切换未生效或未找到目标：{current} → {op.area_name}')
    _press(op, 'dpad_' + direction)
    op._background_region_search = (current, unchanged, total + 1)
    op._background_region_direction = direction
    return op.round_retry(f'手柄查找地图区域：{current} → {op.area_name}', wait=.6)


@lru_cache(maxsize=12)
def _template(name):
    base = Path(os_utils.get_work_dir()) / 'assets/template/map' / name
    if not (base/'raw.png').exists():
        base = Path(__file__).resolve().parents[2] / 'assets/template/map' / name
    raw = cv2.imread(str(base/'raw.png'))
    mask = cv2.imread(str(base/'mask.png'), cv2.IMREAD_GRAYSCALE)
    if raw is None or mask is None:
        return None
    return cv2.cvtColor(raw, cv2.COLOR_BGR2RGB), mask


def _candidates_for_template(screen, name, point):
    loaded = _template(name)
    if loaded is None:
        return []
    raw, mask = loaded
    roi = screen[100:955, 40:1370]
    candidates = []
    scales = ((.65, .75, .85, .95, 1., 1.05, 1.15, 1.25, 1.35, 1.45, 1.55, 1.65, 1.75)
              if point == '咖啡店' else (.85, .95, 1., 1.05, 1.15))
    for scale in scales:
        template = cv2.resize(raw, None, fx=scale, fy=scale)
        scaled_mask = cv2.resize(mask, (template.shape[1], template.shape[0]), interpolation=cv2.INTER_NEAREST)
        values = cv2.matchTemplate(roi, template, cv2.TM_SQDIFF_NORMED, mask=scaled_mask)
        values = np.nan_to_num(values, nan=10, posinf=10, neginf=10)
        for _ in range(12 if point in ('柜台', '房间') else 1):
            minimum, _, pos, _ = cv2.minMaxLoc(values)
            if minimum > (.05 if point == '吼吼饼铺' else .1):
                break
            x, y = pos[0]+40+template.shape[1]/2, pos[1]+100+template.shape[0]/2
            if not any(abs(x-c[0]) < 40 and abs(y-c[1]) < 40 for c in candidates):
                candidates.append((x, y, 1-minimum))
            values[max(0,pos[1]-35):pos[1]+35, max(0,pos[0]-35):pos[0]+35] = 10
    return candidates


def point_candidates(screen, point):
    names = {'吼吼饼铺': 'daily_bakery', '咖啡店': 'daily_coffee',
             '柜台': '3d_map_tp_icon_1', '房间': '3d_map_tp_icon_1'}
    name = names.get(point)
    if name is None:
        return []
    candidates = _candidates_for_template(screen, name, point)
    if point == '吼吼饼铺':
        # The idle chef-head symbol and the focused illustrated symbol differ.
        # A small structural template avoids including neighboring cafe icons.
        loaded=_template('daily_bakery_idle')
        if loaded is not None:
            raw,_=loaded
            roi=cv2.cvtColor(screen[80:955,40:1370],cv2.COLOR_RGB2GRAY)
            for scale in (.85,.95,1.,1.05,1.15):
                raw_gray=cv2.cvtColor(cv2.resize(raw,None,fx=scale,fy=scale),cv2.COLOR_RGB2GRAY)
                values=cv2.matchTemplate(roi,raw_gray,cv2.TM_CCOEFF_NORMED)
                _,score,_,pos=cv2.minMaxLoc(values)
                if score>=.72:
                    candidates.append((pos[0]+40+raw_gray.shape[1]/2,pos[1]+80+raw_gray.shape[0]/2,score))
    return candidates


def _coffee_occlusion_candidates(screen, focused_ramen=False):
    loaded = _template('daily_coffee_ramen_anchor')
    if loaded is None:
        return []
    raw, _ = loaded
    gray = cv2.cvtColor(screen[100:955, 40:1370], cv2.COLOR_RGB2GRAY)
    best = None
    for scale in (.65, .75, .85, .95, 1., 1.05, 1.15, 1.25, 1.35, 1.45, 1.55):
        template = cv2.cvtColor(cv2.resize(raw, None, fx=scale, fy=scale), cv2.COLOR_RGB2GRAY)
        _, score, _, pos = cv2.minMaxLoc(cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED))
        if score >= .82 and (best is None or score > best[2]):
            best = (pos[0] + 40 + template.shape[1]/2 - 150*scale,
                    pos[1] + 100 + template.shape[0]/2 - 12*scale, score,
                    pos[0] + 40 + template.shape[1]/2,
                    pos[1] + 100 + template.shape[0]/2)
    if focused_ramen:
        best = (545., 528., 1., 695., 540.)
    if best is None:
        return []
    # Map zoom changes landmark spacing while icons keep nearly constant size.
    # Locate the occluding circular portrait itself instead of scaling spacing
    # from the ramen icon's dimensions.
    x1, x2 = max(40, int(best[3]-600)), min(1370, int(best[3]-80))
    y1, y2 = max(100, int(best[4]-140)), min(955, int(best[4]+100))
    part = cv2.cvtColor(screen[y1:y2, x1:x2], cv2.COLOR_RGB2GRAY)
    circles = cv2.HoughCircles(part, cv2.HOUGH_GRADIENT, 1, 50,
                               param1=100, param2=27, minRadius=25, maxRadius=70)
    rims = []
    if circles is not None:
        angles = np.linspace(0, 2*np.pi, 128)
        for x, y, radius in circles[0]:
            rim = []
            for offset in (-2, 0, 2):
                xs = np.clip((x+(radius+offset)*np.cos(angles)).astype(int), 0, part.shape[1]-1)
                ys = np.clip((y+(radius+offset)*np.sin(angles)).astype(int), 0, part.shape[0]-1)
                pixels = screen[y1+ys, x1+xs].astype(np.int16)
                rim.extend((pixels.min(axis=1)>100) & (pixels.max(axis=1)-pixels.min(axis=1)<50))
            if np.mean(rim) > .35:
                rims.append((x1+float(x), y1+float(y), float(radius)))
    # The portrait and its speech bubble form two overlapping rims; overlapping
    # rims are one occluder. Separate occluders remain ambiguous.
    if not rims or any(np.hypot(a[0]-b[0], a[1]-b[1]) >= a[2]+b[2]
                       for i, a in enumerate(rims) for b in rims[i+1:]):
        return []
    # The event portrait sits below and covers the lower cup. Aim at its upper
    # edge, where the cafe marker remains selectable; the destination name is
    # still verified on a fresh frame before any confirm.
    return [(float(np.mean([x for x, _, _ in rims])),
             float(np.mean([y-r*.8 for _, y, r in rims])), best[2])]


def choose_point(op, screen):
    state = map_state(op, screen)
    if state is None:
        return op.round_retry('未核验地图，暂停传送点搜索', wait=.5)
    if not _area_match(state, op.area_name):
        return op.round_fail(f'搜索传送点时地图区域未核验：{state["title"]} / {state["selected"]}')
    if state['detail'] and _match(state['point'], op.tp_name) and state['can_go']:
        return op.round_success(f'已核验目标传送点：{op.area_name} / {op.tp_name}')
    count = getattr(op, '_background_point_steps', 0)
    if count >= 22:
        return op.round_fail(f'后台未找到目标传送点：{op.tp_name}；当前：{state["point"]}')
    op._background_point_steps = count + 1
    candidates = point_candidates(screen, op.tp_name)
    if not candidates and op.tp_name == '咖啡店' and op.area_name == '六分街':
        # A trust-event portrait can completely cover the cafe cup. The ramen
        # shop is a separate, visible landmark on the same street. Use it only
        # to uncover the nearby destination; its exact name and go button must
        # still be read on a fresh frame before any transport confirmation.
        anchors = _coffee_occlusion_candidates(screen, state['point'] == '拉面店')
        if anchors:
            candidates = anchors
    if not candidates and op.tp_name=='吼吼饼铺' and op.area_name=='布亚斯特城区':
        anchors=_candidates_for_template(screen,'daily_random_play_anchor','anchor')
        if anchors:
            x,y,score=max(anchors,key=lambda c:c[2])
            candidates=[(x+35,y+35,score)]
    if op.tp_name == '吼吼饼铺' and state['point'] == '片刻闲':
        # The cafe's focused icon covers the bakery directly above it. Use the
        # verified adjacent destination for a short adjustment, then re-read
        # the destination name; never confirm the cafe for a bakery request.
        candidates = [(695.,495.,1.)]
    elif op.tp_name=='吼吼饼铺' and state['point']=='录像店营业点':
        # These overlapping symbols share the same block on this map. The
        # bakery head sits just right of the focused Random Play icon.
        candidates=[(730.,555.,1.)]
    if not candidates:
        # Map symbols can overlap and fade. Increase map spacing only after
        # verifying the map's zoom control, then inspect a fresh frame.
        zooms = getattr(op, '_background_map_zooms', 0)
        footer = _rows(op, screen, Rect(650, 980, 1250, 1060))
        zoom_button = _template('daily_map_zoom')
        zoom_visible = any(_text(r.data) in ('RT', 'R2') for r in footer)
        if not zoom_visible and zoom_button is not None:
            raw, mask = zoom_button
            values = cv2.matchTemplate(screen[975:1060, 1150:1250], raw, cv2.TM_SQDIFF_NORMED, mask=mask)
            zoom_visible = cv2.minMaxLoc(np.nan_to_num(values, nan=10, posinf=10, neginf=10))[0] < .18
        if (op.tp_name in ('吼吼饼铺', '咖啡店', '柜台', '房间') and zooms < 3 and zoom_visible):
            _press(op, 'r2' if op.ctx.game_config.background_gamepad_type == 'ds4' else 'rt', .2)
            op._background_map_zooms = zooms + 1
            return op.round_retry(f'目标图标被遮挡，放大地图后重新识别：{op.tp_name}', wait=.8)
        return op.round_retry(f'未识别 {op.tp_name} 图标，未发送移动', wait=.6)
    if op.tp_name in ('柜台', '房间'):
        candidate = sorted(candidates, key=lambda c:c[1], reverse=op.tp_name == '柜台')[0]
    else:
        candidate = max(candidates, key=lambda c:c[2])
    x, y, _ = candidate
    dx, dy = 695-x, 540-y
    axis = 'x' if abs(dx) >= abs(dy) else 'y'
    velocity = getattr(op, '_background_map_velocity', {'x': 600. if op.area_name=='录像店' else 2800.,
                                                       'y': 500. if op.area_name=='录像店' else 1400.})
    previous = getattr(op, '_background_map_motion', None)
    if previous:
        old_axis, old_pos, duration, *scales = previous
        moved = abs((x, y)[old_axis=='y']-old_pos)
        op._background_map_stalls = (getattr(op, '_background_map_stalls', 0) + 1
                                    if moved < 3 else 0)
        observed = moved / duration / (scales[0] if scales else 1)
        if 80 < observed < 6000:
            velocity[old_axis] = .4*velocity[old_axis]+.6*observed
    op._background_map_velocity = velocity
    delta = dx if axis=='x' else dy
    slow=(abs(delta)<100 and op.area_name!='录像店'
          and getattr(op, '_background_map_stalls', 0) < 2)
    duration = min(.24, max(.08 if slow else .025, abs(delta)/(velocity[axis]*(.35 if slow else 1))*.75))
    if getattr(op, '_background_map_stalls', 0) >= 2:
        duration = max(.10, duration)
    action = ('move_a' if delta>0 else 'move_d') if axis=='x' else ('move_w' if delta>0 else 'move_s')
    op._background_map_motion = (axis, x if axis=='x' else y, duration, .35 if slow else 1)
    keys = op.ctx.game_config.get_action_keys('ds4' if op.ctx.game_config.background_gamepad_type=='ds4' else 'xbox')
    key=keys[action]
    if slow:
        direction={'move_a':'left','move_d':'right','move_w':'up','move_s':'down'}[action]
        key=('ds4_' if op.ctx.game_config.background_gamepad_type=='ds4' else 'xbox_')+'ls_slow_'+direction
    op.ctx.controller.btn_press(key, press_time=duration)
    return op.round_retry(f'手柄定位 {op.tp_name}：图标 ({int(x)}, {int(y)})，当前详情 {state["point"] or "无"}', wait=.65)


def confirm_point(op, screen):
    state = map_state(op, screen)
    attempts = getattr(op, '_background_go_requests', 0)
    if attempts and state is None:
        # A confirmed destination has left the map. Transport's next node still
        # verifies the actual world; unrelated map pages are not accepted here.
        rows = _rows(op, screen, Rect(1390, 15, 1870, 100))
        if any(_text(r.data)=='快捷导航' for r in rows):
            return op.round_fail('确认后地图层级改变，未核验传送')
        return op.round_success('已离开已核验目标的地图，等待加载')
    if not state or not state['detail'] or not state['can_go'] or not _match(state['point'], op.tp_name) or not _area_match(state, op.area_name):
        return op.round_fail('传送目标或前往按钮未通过核验，未操作')
    if attempts >= 3:
        return op.round_fail(f'目标 {op.tp_name} 的传送确认未生效')
    _press(op, 'confirm')
    op._background_go_requests = attempts + 1
    return op.round_wait(f'手柄确认传送至 {op.area_name} / {op.tp_name}，等待实际画面', wait=2)


def return_from_map(op, screen):
    if map_state(op, screen) is None:
        return None
    attempts = getattr(op, '_background_map_back', 0)
    if attempts >= 4:
        return op.round_fail('后台关闭地图未生效')
    _press(op, 'back')
    op._background_map_back = attempts + 1
    return op.round_retry('手柄关闭地图，等待实际大世界画面', wait=1)
