"""Passive enemy evidence in a normalized 1920x1080 RGB frame.

The attack button alone is also present while exploring. Require an
enemy health panel or the chain-attack UI before handing over input. An orange
circle alone can be a Bangboo, scenery, or an objective marker.
"""
import cv2
import math
import numpy as np
from functools import lru_cache


@lru_cache(maxsize=1)
def _health_shapes():
    """Color-free left edge of the L-shaped health/daze panel (no badge)."""
    from onedragon.utils import os_utils
    image = cv2.imread(os_utils.get_path_under_work_dir('assets', 'template', 'target_state',
                                                      'enemy_health_panel_shape', 'raw.png'))
    if image is None:
        return []
    outline = (image.max(axis=2) < 55).astype(np.float32)
    empty = outline.copy()
    # Empty daze is grey, filled daze is bright. Both share the same outline.
    empty[14:23, 25:] = np.where(empty[14:23, 25:] > 0, 1, 0.65)
    empty_health = outline.copy()
    empty_health[5:20, 4:25] = np.where(empty_health[5:20, 4:25] > 0, 1, .55)
    patterns = [outline, empty, empty_health]
    empty_image = cv2.imread(os_utils.get_path_under_work_dir('assets', 'template', 'target_state',
                                                            'enemy_health_panel_shape', 'empty.png'))
    if empty_image is not None:
        empty_hsv = cv2.cvtColor(empty_image, cv2.COLOR_BGR2HSV)
        pattern = (empty_hsv[:, :, 2] < 55).astype(np.float32)
        grey = (empty_hsv[:, :, 1] < 85) & (empty_hsv[:, :, 2] >= 55)
        pattern[grey] = .6
        patterns.append(pattern)
        # Partly depleted health has a short bright fill followed by grey.
        # Preserve the outline while varying only the fill, never the badge.
        for fill_width in (10, 16, 22):
            partial = pattern.copy()
            fill = partial[5:20, 4:fill_width]
            fill[fill == .6] = 0
            patterns.append(partial)
    return [(scale, cv2.resize(pattern, None, fx=scale, fy=scale,
                              # Tiny distant panels have anti-aliased edges.
                              # Match their greyscale geometry without lowering
                              # the confidence threshold or reading the badge.
                              interpolation=cv2.INTER_LINEAR if scale < 1 else cv2.INTER_NEAREST))
            for pattern in patterns
            for scale in (.45, .5, .55, .6, .65, .7, .75, .8, .85,
                          .9, .95, 1, 1.05, 1.1, 1.2)]


@lru_cache(maxsize=1)
def _filled_health_shapes():
    """A filled daze row uses lighter borders; retain only luminance geometry."""
    from onedragon.utils import os_utils
    image = cv2.imread(os_utils.get_path_under_work_dir('assets', 'template', 'target_state',
                                                      'enemy_health_panel_shape', 'filled.png'))
    if image is None:
        return []
    pattern = (255-image.max(axis=2)).astype(np.float32)/255
    return [(scale, cv2.resize(pattern, None, fx=scale, fy=scale,
                              interpolation=cv2.INTER_LINEAR if scale < 1 else cv2.INTER_NEAREST))
            for scale in (.45,.5,.55,.6,.65,.7,.75,.8,.85,.9,.95,1,1.05,1.1,1.2)]


def _bars(mask, min_width, max_height):
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    result = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w >= min_width and 2 <= h <= max_height and w / h >= 6:
            if cv2.countNonZero(mask[y:y+h, x:x+w]) / (w*h) >= 0.65:
                result.append((x, y, w, h))
    return result


def has_target_reticle(screen):
    # Lock marker uses the existing pipeline's ROI/geometry. Keep the thin
    # anti-aliased ring: erosion can erase it or merge it into bright effects.
    hsv = cv2.cvtColor(screen[274:852, 432:1490], cv2.COLOR_RGB2HSV)
    mask = cv2.inRange(hsv, (10, 80, 100), (35, 255, 255))
    contours, hierarchy = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return False
    for index, contour in enumerate(contours):
        area = cv2.contourArea(contour)
        _, _, w, h = cv2.boundingRect(contour)
        if hierarchy[0][index][3] < 0:
            continue
        if 60 <= area <= 1200 and 0.8 <= w / max(h, 1) <= 1.2:
            hull = cv2.convexHull(contour)
            hull_area = cv2.contourArea(hull)
            perimeter = cv2.arcLength(hull, True)
            if (perimeter and area / max(hull_area, 1) >= 0.55
                    and 4*math.pi*hull_area / (perimeter*perimeter) >= 0.88):
                return True
    return False


def find_enemy_health_bar(screen):
    # Boss HUD: green health with a dark outline, in the asset's top-right ROI.
    boss = screen[25:100, 1050:1888]
    hsv = cv2.cvtColor(boss, cv2.COLOR_RGB2HSV)
    green = cv2.inRange(hsv, (35, 90, 90), (90, 255, 255))
    for x, y, w, h in _bars(green, 70, 16):
        if y > 0 and y+h < boss.shape[0]:
            edges = np.concatenate((boss[y-1, x:x+w], boss[y+h, x:x+w]))
            if np.mean(np.max(edges, axis=1) < 100) >= 0.7:
                return {'panel_kind': 'boss', 'rect': [1050+x, 25+y, w, h]}
    # Use the left cap, stepped divider and two rows inside the panel. The
    # attribute badge is deliberately outside this template and is never read.
    # Correlation tolerates the panel's transparency/brightness changing with
    # distance; filled width is not a minimum-health requirement.
    roi = screen[180:852, 90:1850]
    hsv = cv2.cvtColor(roi, cv2.COLOR_RGB2HSV)
    red = cv2.inRange(hsv, (0, 90, 90), (10, 255, 255))
    red |= cv2.inRange(hsv, (170, 90, 90), (179, 255, 255))
    health = red | cv2.inRange(hsv, (35, 60, 80), (90, 255, 255))
    daze = cv2.inRange(hsv, (10, 100, 100), (35, 255, 255))
    candidates = []
    for mask, seed_kind in ((health, 'health'), (daze, 'daze')):
        contours = _world_panel_contours(mask, 7)
        candidates.append((contours, seed_kind))
        panel = _find_world_panel(hsv, contours, seed_kind)
        if panel is not None:
            return panel
    # Preserve the previous robust wide-bar path. A separate small-fill pass
    # avoids connecting distant panels to nearby colored effects.
    panel = _find_world_panel(hsv, _world_panel_contours(health, 3), 'health', small_only=True)
    if panel is not None:
        return panel
    # Filled pink/white daze can erase the dark divider used by the older
    # template. This variant still requires the complete two-row cap geometry,
    # uses a stricter confidence, and never includes the attribute badge.
    # Reuse this frame's contours; preserve template and candidate priority.
    for contours, seed_kind in candidates:
        panel = _find_world_panel(hsv, contours, seed_kind, shapes=_filled_health_shapes(), threshold=.84)
        if panel is not None:
            return panel
    return None


def _world_panel_contours(mask, kernel_size):
    horizontal = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((1, kernel_size), np.uint8))
    contours, _ = cv2.findContours(horizontal, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return contours


def _find_world_panel(hsv, contours, seed_kind, small_only=False, shapes=None, threshold=.74):
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        min_width = 3 if small_only else 18
        if small_only and w >= 18:
            continue
        if not (min_width <= w <= 350 and 2 <= h <= 28 and (w/h >= 1.3 or small_only)):
            continue
        is_health = seed_kind == 'health'
        x0, y0 = max(0, x-(16 if is_health else 40)), max(0, y-(12 if is_health else 24))
        patch = (255-hsv[y0:y+h+16, x0:min(x+90, hsv.shape[1]), 2]).astype(np.float32)
        for scale, template in (_health_shapes() if shapes is None else shapes):
            if not .7 <= h / ((17 if is_health else 7)*scale) <= 1.35:
                continue
            th, tw = template.shape
            if patch.shape[0] < th or patch.shape[1] < tw:
                continue
            # The color seed must start in the cap, rather than elsewhere in
            # scenery beside a vaguely similar edge.
            sx, sy = x-x0-(4 if is_health else 32)*scale, y-y0-(5 if is_health else 14)*scale
            lx, rx = max(0, int(sx-4)), min(patch.shape[1]-tw+1, int(sx+5))
            ty, by = max(0, int(sy-3)), min(patch.shape[0]-th+1, int(sy+4))
            if lx >= rx or ty >= by:
                continue
            scores = cv2.matchTemplate(patch[ty:by+th-1, lx:rx+tw-1], template,
                                       cv2.TM_CCOEFF_NORMED)
            _, confidence, _, point = cv2.minMaxLoc(scores)
            if confidence >= threshold:
                return {'panel_kind': 'world', 'seed_kind': seed_kind, 'confidence': round(confidence, 3),
                        'rect': [90+x0+lx+point[0], 180+y0+ty+point[1], tw, th]}
    return None


def has_enemy_health_bar(screen):
    return find_enemy_health_bar(screen) is not None


def find_enemy_direction_arrow(screen):
    """Peripheral red triangular enemy indicators, excluding objective/HUD zones.

    A compact filled triangle, dark outline and outward pointing tip are all
    required. The assistant also requires multiple frames before activation.
    """
    roi = screen[160:880]
    hsv = cv2.cvtColor(roi, cv2.COLOR_RGB2HSV)
    red = cv2.inRange(hsv, (0, 135, 150), (9, 255, 255))
    red |= cv2.inRange(hsv, (172, 135, 150), (179, 255, 255))
    contours, _ = cv2.findContours(red, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        cy, cx = y+160+h/2, x+w/2
        # Ignore central hit effects, top/bottom controls and the objective box.
        if not (8 <= w <= 45 and 8 <= h <= 45 and .45 <= w/h <= 2.2
                and (cx < 320 or cx > 1600 or cy > 760)):
            continue
        if cx > 1550 and cy < 360:
            continue
        perimeter = cv2.arcLength(contour, True)
        vertices = cv2.approxPolyDP(contour, .07*perimeter, True).reshape(-1, 2)
        if len(vertices) != 3 or not cv2.isContourConvex(vertices):
            continue
        area = cv2.contourArea(contour)
        if not .32 <= area/(w*h) <= .72:
            continue
        # NPC route badges (e.g. crossed swords) contain disconnected red
        # triangle fragments. Join nearby strokes locally before accepting a
        # fragment as a standalone offscreen arrow.
        sx,sy=max(0,x-8),max(0,y-8)
        ex,ey=min(roi.shape[1],x+w+8),min(roi.shape[0],y+h+8)
        joined=cv2.dilate(red[sy:ey,sx:ex],np.ones((5,5),np.uint8))
        joined_contours,_=cv2.findContours(joined,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        seed=tuple(float(v) for v in contour[0,0]-np.array([sx,sy]))
        fragment=False
        for joined_contour in joined_contours:
            if cv2.pointPolygonTest(joined_contour,seed,False)<0:
                continue
            _,_,jw,jh=cv2.boundingRect(joined_contour)
            fragment=jw-4>w*1.6 or jh-4>h*1.6
            break
        if fragment:
            continue
        x0,y0,x1,y1=max(0,x-3),max(0,y-3),min(1920,x+w+3),min(roi.shape[0],y+h+3)
        shape = np.zeros((y1-y0,x1-x0), np.uint8)
        cv2.drawContours(shape, [contour-np.array([[[x0,y0]]])], -1, 255, -1)
        edge = cv2.dilate(shape, np.ones((5, 5), np.uint8)) > shape
        if np.mean(hsv[y0:y1, x0:x1, 2][edge] < 100) < .65:
            continue
        center = np.array([cx, cy-160])
        direction = center-np.array([960, 540-160])
        direction /= max(np.linalg.norm(direction), 1)
        offsets = vertices-center
        projections = offsets@direction
        tip = offsets[np.argmax(projections)]
        if (np.max(projections) < .3*max(w, h)
                or np.dot(tip, direction)/max(np.linalg.norm(tip), 1) < .85):
            continue
        return {'rect': [x, y+160, w, h], 'confidence': 'geometry'}
    return None


def has_chain_timer(screen):
    """The outlined bottom-center timer, including current pink/red fills."""
    bar = screen[873:903, 607:1314]
    hsv = cv2.cvtColor(bar, cv2.COLOR_RGB2HSV)
    dark = hsv[:, :, 2] < 95
    if (np.max(np.mean(dark[:6, 25:-25], axis=1)) < .7
            or np.max(np.mean(dark[-6:, 25:-25], axis=1)) < .7):
        return False
    fill = cv2.inRange(hsv, (0, 110, 100), (179, 255, 255))
    fill = cv2.morphologyEx(fill, cv2.MORPH_CLOSE, np.ones((1, 13), np.uint8))
    if any(w >= 30 and 6 <= h <= 23 for x, y, w, h in _bars(fill, 30, 23)):
        return True
    # Near expiry the fill disappears, while the grey track and portraits stay.
    grey = (hsv[8:22, 25:-25, 1] < 80) & (hsv[8:22, 25:-25, 2] >= 45)
    return bool(np.max(np.mean(grey, axis=1)) >= .7)


def detect_battle_presence(screen, battle_ctx):
    if screen is None or screen.shape[:2] != (1080, 1920):
        return None
    if battle_ctx.is_normal_attack_btn_available(screen):
        panel = find_enemy_health_bar(screen)
        if panel:
            from src.diagnostics import record_event
            record_event('enemy_panel', **panel, throttle='enemy_panel')
            return '敌人血条'
        arrow = find_enemy_direction_arrow(screen)
        if arrow:
            from src.diagnostics import record_event
            record_event('enemy_direction_arrow', **arrow, throttle='enemy_direction_arrow')
            return '敌人方向箭头'
        return None
    return detect_chain_presence(screen, battle_ctx)


def detect_chain_presence(screen, battle_ctx, timer_confirmed=False):
    """Separate UI-only probe; never scans enemies when attack HUD is absent."""
    timer = timer_confirmed or has_chain_timer(screen)
    if not timer:
        result = battle_ctx.ctx.cv_service.run_pipeline(
            '战斗-连携条', screen, debug_mode=False, timeout=0.1)
        timer = bool(result is not None and result.is_success and result.contours)
    if timer:
        agents = battle_ctx.agent_context.get_possible_agent_list()
        for chain_area in (battle_ctx.area_chain_1, battle_ctx.area_chain_2):
            area = chain_area.rect
            avatar = screen[area.y1:area.y2, area.x1:area.x2]
            if battle_ctx._match_chain_agent_in(avatar, agents) is not None:
                return '连携技'
    return None
