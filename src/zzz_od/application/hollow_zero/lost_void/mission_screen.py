"""从当前帧识别入口标题和详情模式，不使用点击后预填的画面名称。"""
import re
import sys
import time
from pathlib import Path
import cv2
import numpy as np

from onedragon.base.geometry.rectangle import Rect
from src.controls.gamepad import press as pad

MISSION_NAMES = ('战线肃清', '特遣调查')
ENTRY_TITLES = Rect(700, 280, 1850, 430)
DETAIL_TITLE = Rect(700, 120, 1820, 300)
DETAIL_ACTIONS = Rect(1250, 970, 1860, 1070)


def lottery_counts(ctx, screen):
    """Recognize the controller lottery menu from its preview and counted start button."""
    service = getattr(ctx, 'ocr_service', None)
    if service is None or not isinstance(screen, np.ndarray):
        return None
    rows = service.get_ocr_result_list(image=screen, rect=Rect(760,20,1830,990))
    if not isinstance(rows, (list, tuple)):
        return None
    preview = any(str(row.data).replace(' ', '') == '奖励预览'
                  and 1600 < row.center.x < 1830 and 20 < row.center.y < 90 for row in rows)
    button = ''.join(str(row.data).replace(' ', '') for row in rows
                     if 800 < row.center.x < 1130 and 885 < row.center.y < 985)
    count = re.fullmatch(r'开始(\d+)/(\d+)', button)
    if not preview or count is None:
        return None
    remaining, total = map(int, count.groups())
    if total <= 0 or remaining > total:
        return None
    part = screen[885:985,804:1120]
    if not part.size or np.mean((part[:, :, 0] > 170) & (part[:, :, 1] > 120)
                                & (part[:, :, 2] < 100)) < .2:
        return None
    return remaining, total


def recover_connection(op):
    """Continue only a verified timeout dialog; never select re-login or count a clear."""
    screen = op.last_screenshot
    service = getattr(op.ctx, 'ocr_service', None)
    if not isinstance(screen, np.ndarray) or service is None:
        return None
    focus = screen[550:665, 965:1255]
    if not focus.size or np.mean((focus[:, :, 0] > 150) & (focus[:, :, 1] > 140)
                                & (focus[:, :, 2] < 100)) < .2:
        op._connection_requests = 0
        return None
    rows = service.get_ocr_result_list(image=screen, rect=Rect(600,460,1300,730))
    if not isinstance(rows, (list, tuple)):
        return None
    title = ''.join(str(row.data).replace(' ', '') for row in rows if 480 < row.center.y < 555)
    retry = any(str(row.data).replace(' ', '') == '继续连接' and 1000 < row.center.x < 1250
                and 580 < row.center.y < 670 for row in rows)
    login = any(str(row.data).replace(' ', '') == '重新登录' and 670 < row.center.x < 940
                and 580 < row.center.y < 670 for row in rows)
    if '服务器连接超时' not in title or not retry or not login:
        op._connection_requests = 0
        return None
    requests = getattr(op, '_connection_requests', 0)
    if requests >= 3:
        return op.round_fail('服务器连接超时，继续连接未恢复')
    op._connection_requests = requests + 1
    op._connection_wait_until = time.time() + 30
    if getattr(op.ctx.controller, 'background_mode', False):
        pad(op.ctx, 'a')
    else:
        op.ctx.controller.click(next(row.center for row in rows if str(row.data).replace(' ', '') == '继续连接'))
    return op.round_wait('服务器连接超时，确认继续连接并等待恢复', wait=2)


def failed_grade(ctx, screen):
    loader = getattr(ctx, 'template_loader', None)
    if loader is None or screen is None:
        return False
    part = screen[300:850,600:1300]
    for name in ('failed_grade', 'failed_grade_alt', 'failed_grade_front'):
        template = loader.get_template('lost_void', name)
        raw = getattr(template, 'raw', None)
        if raw is None and not getattr(sys, 'frozen', False):
            path = Path(__file__).resolve().parents[5]/f'assets/template/lost_void/{name}/raw.png'
            image = cv2.imread(str(path))
            if image is not None:
                raw = cv2.cvtColor(image,cv2.COLOR_BGR2RGB)
        if not isinstance(raw, np.ndarray) or raw.shape[0] > part.shape[0] or raw.shape[1] > part.shape[1]:
            continue
        result = cv2.matchTemplate(cv2.cvtColor(part,cv2.COLOR_RGB2GRAY),
            cv2.cvtColor(raw,cv2.COLOR_RGB2GRAY),cv2.TM_CCOEFF_NORMED)
        # The 3D X rotates during settlement; retain the observed silhouettes.
        if result.max() >= .8:
            return True
    return False


def battle_result(ctx, screen):
    service = getattr(ctx, 'ocr_service', None)
    if service is None:
        return None
    matches = service.get_ocr_result_list(image=screen, rect=Rect(480,20,1900,1070))
    if not isinstance(matches, (list, tuple)):
        return None
    body = ''.join(str(m.data).replace(' ', '') for m in matches if m.center.y < 850)
    if not ('挑战结果' in body or ('完成关卡' in body and '总计用时' in body)):
        return None
    actions = {str(m.data).strip() for m in matches if m.center.y > 870} & {'确定', '完成'}
    return next(iter(actions)) if len(actions) == 1 else None


def dialogue_visible(ctx, screen):
    service = getattr(ctx, 'ocr_service', None)
    if service is None:
        return False
    matches = service.get_ocr_result_list(image=screen, rect=Rect(390,790,1540,1050))
    if not isinstance(matches, (list, tuple)):
        return False
    name = any(790 < m.center.y < 850 and 1 <= len(str(m.data).strip()) <= 12
               and str(m.data).strip() not in ('确定','返回','详情') for m in matches)
    content = any(860 < m.center.y < 990 and len(str(m.data).strip()) >= 5 for m in matches)
    return name and content


def collection_tab(screen):
    """藏品面板三个页签只有当前页具有大面积黄色背景。"""
    if screen is None:
        return None
    hsv = cv2.cvtColor(screen, cv2.COLOR_RGB2HSV)
    found = []
    for name, x in (('地图', 390), ('藏品', 640), ('属性', 890)):
        region = hsv[25:75, x-80:x+80]
        mask = cv2.inRange(region, np.array([20,145,155]), np.array([75,255,255]))
        if (mask > 0).mean() > .55:
            found.append(name)
    return found[0] if len(found) == 1 else None


def focused_card(screen, excluded_centers=()):
    """识别手柄焦点的连续外框；装饰金线和零散文字不能成为焦点。输入为标准 RGB。"""
    if screen is None:
        return None
    hsv = cv2.cvtColor(screen, cv2.COLOR_RGB2HSV)
    # Green quality cards are filled with green, so use the bright yellow
    # focus rim first. Preserve dark green gear focus as a separate fallback.
    bright = cv2.inRange(hsv, np.array([20, 145, 155]), np.array([38, 255, 255]))
    candidates = _card_rims(bright, excluded_centers)
    if candidates:
        return candidates[0] if len(candidates) == 1 else None
    mask = cv2.inRange(hsv, np.array([20, 145, 85]), np.array([75, 255, 255]))
    candidates = _card_rims(mask, excluded_centers)
    return candidates[0] if len(candidates) == 1 else None


def common_choice(ctx, screen):
    """Verify controller selection/reward layouts independently of the TAB template."""
    service = getattr(ctx, 'ocr_service', None)
    if service is None or not isinstance(screen, np.ndarray):
        return False
    rows = service.get_ocr_result_list(image=screen, rect=Rect(380,130,1540,990))
    if not isinstance(rows, (list, tuple)):
        return False
    words = [(str(row.data).replace(' ', ''), row.center) for row in rows
             if getattr(row, 'center', None) is not None and hasattr(row.center, 'x')]
    titles = [text for text,p in words if 140 < p.y < 230]
    selection = any(re.fullmatch(r'请选择[123一二三两](项|张卡牌|枚鸣徽|个武备)', text) for text in titles)
    reward = any(text in ('获得武备','武备已升级','获得战利品') for text in titles)
    if not (selection or reward):
        return False
    if not any(re.fullmatch(r'确定(?:[（(]?[123]/[123][）)]?)?', text) and 750 < p.x < 1200
               and 750 < p.y < 990 for text,p in words):
        return False
    focus = focused_card(screen) if selection else None
    if selection and focus is None:
        return False
    def aligned(point):
        return not selection or focus.x1 < point.x < focus.x2
    # Stylized A is read as N on the actual shop upgrade receipt.
    gear = any(text.upper() in ('GEAR', 'GENR') and 730 < p.y < 850 and aligned(p) for text,p in words)
    gear_name = any(re.match(r'[\[【].+?[\]】].+', text) and 410 < p.y < 475 and aligned(p) for text,p in words)
    card = any(re.fullmatch(r'[A-Z]{4,}', text.upper()) and 250 < p.y < 350 and aligned(p) for text,p in words)
    resonium = any(text.upper().startswith('RESON') and 250 < p.y < 350 and aligned(p) for text,p in words)
    name_top, name_bottom = (540, 610) if resonium else (475, 555)
    card_name = any(len(text) >= 2 and name_top < p.y < name_bottom and aligned(p) for text,p in words)
    footer = any('HOLLOW' in text.upper() and 700 < p.y < 760 and aligned(p) for text,p in words)
    return (gear and gear_name) or (card and card_name and (reward or footer))


def single_event_choice(ctx, screen):
    """核验手柄下带放弃按钮的单张事件卡，兼容 TAB 标识模板漏匹配。"""
    service = getattr(ctx, 'ocr_service', None)
    if service is None or screen is None:
        return False
    matches = service.get_ocr_result_list(image=screen, rect=Rect(700,130,1240,930))
    if not isinstance(matches, (list, tuple)):
        return False
    words = [(str(row.data).replace(' ', ''), row.center) for row in matches]
    title = any(text in ('请选择1项', '请选择一项') and 140 < point.y < 205 for text, point in words)
    confirm = any(text == '确定' and 1010 < point.x < 1190 and 800 < point.y < 890 for text, point in words)
    abandon = any(text == '放弃' and 740 < point.x < 950 and 800 < point.y < 890 for text, point in words)
    card_label = any('HOLLOW' in text.upper() and 700 < point.y < 760 for text, point in words)
    card_name = any(len(text) >= 2 and 540 < point.y < 610 for text, point in words)
    if not (title and confirm and abandon and card_label and card_name):
        return False
    focus = focused_card(screen)
    return focus is not None and 240 <= focus.width <= 400 and 860 < focus.center.x < 1060


def black_story_caption(ctx, screen):
    """黑底事件文字必须同时有手柄确认图标；纯加载黑屏不能触发输入。"""
    if screen is None or (screen[100:980,120:1800].max(axis=2) < 45).mean() < .93:
        return None
    loader = getattr(ctx, 'template_loader', None)
    template = loader.get_template('lost_void', 'story_confirm_xbox') if loader is not None else None
    raw = getattr(template, 'raw', None)
    if not isinstance(raw, np.ndarray) and not getattr(sys, 'frozen', False):
        image = cv2.imread(str(Path(__file__).resolve().parents[5] / 'assets/template/lost_void/story_confirm_xbox/raw.png'))
        if image is not None:
            raw = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    if not isinstance(raw, np.ndarray):
        return None
    part = screen[545:640,900:1020]
    if raw.shape[0] > part.shape[0] or raw.shape[1] > part.shape[1]:
        return None
    score = cv2.matchTemplate(cv2.cvtColor(part,cv2.COLOR_RGB2GRAY), cv2.cvtColor(raw,cv2.COLOR_RGB2GRAY),cv2.TM_CCOEFF_NORMED)
    if score.max() < .85:
        return None
    service = getattr(ctx, 'ocr_service', None)
    if service is None:
        return None
    rows = service.get_ocr_result_list(image=screen, rect=Rect(280,420,1640,550))
    if not isinstance(rows, (list, tuple)):
        return None
    caption = ''.join(str(row.data).replace(' ', '') for row in rows if 460 < row.center.y < 550)
    return caption if len(caption) >= 6 else None


def _card_rims(mask, excluded_centers):
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w < 240 or h < 140 or y < 150 or y+h > 950:
            continue
        # 四边均需连续高亮。角色画、说明文字和内部金色横线不会满足。
        crop = mask[y:y+h, x:x+w] > 0
        # 未选中卡牌的绿色品质背景会形成整块轮廓，不能当作选中外框。
        if crop.mean() > .25:
            continue
        # 武备卡片上下的图标和标签会凸出外框；暗色绿框也属于当前焦点。
        coverage = (crop[:180].any(axis=0).mean(), crop[-60:].any(axis=0).mean(),
                    crop[:, :32].any(axis=1).mean(), crop[:, -32:].any(axis=1).mean())
        if min(coverage) >= .65:
            # 多选已选卡仍保留暗色边框，不能与当前未选卡焦点混淆。
            if any(x <= cx <= x+w for cx in excluded_centers):
                continue
            candidates.append(Rect(x, y, x+w, y+h))
    return candidates


def focused_gear(screen):
    if screen is None:
        return None
    hsv=cv2.cvtColor(screen[900:1080], cv2.COLOR_RGB2HSV)
    mask=cv2.inRange(hsv, np.array([20,145,155]), np.array([75,255,255]))
    # 图标和价格会切断圆环，不能要求单个连续轮廓。对标准化画面拟合外环，
    # 同时排除内圈黄色插画；两个分离外环同时高亮时拒绝猜测。
    yy,xx=np.mgrid[-70:71,-70:71]
    radius=np.sqrt(xx*xx+yy*yy)
    kernel=((radius>61)&(radius<69)).astype(np.float32)
    kernel/=kernel.sum()
    response=cv2.filter2D((mask>0).astype(np.float32),-1,kernel)[65:110,150:1750]
    y,x=np.unravel_index(response.argmax(),response.shape)
    if response[y,x] < .35:
        return None
    others=response.copy()
    others[:,max(0,x-85):x+86]=0
    if others.max() >= .35:
        return None
    cx,cy=x+150,y+965
    return Rect(cx-68,cy-68,cx+68,cy+68)


def mission_text(text):
    value = re.sub(r'\s+', '', str(text))
    matches = [name for name in MISSION_NAMES if name in value]
    return matches[0] if len(matches) == 1 else None


def menu_matches(ctx, screen):
    matches = ctx.ocr_service.get_ocr_result_list(image=screen, rect=ENTRY_TITLES)
    result = {}
    for match in matches:
        name = mission_text(match.data)
        if name and (name not in result or match.confidence > result[name].confidence):
            result[name] = match
    return result


def entry_header(ctx, screen):
    """Require bounty progress and tabs, including the single-card weekly entry."""
    service = getattr(ctx, 'ocr_service', None)
    if service is None:
        return None
    rows = service.get_ocr_result_list(image=screen, rect=Rect(650,10,1720,100))
    if not isinstance(rows, (list, tuple)):
        return None
    header = ''.join(str(row.data).replace(' ', '') for row in rows)
    if '悬赏委托完成进度' not in header or not ('周期' in header or '常规' in header):
        return None
    titles = service.get_ocr_result_list(image=screen, rect=Rect(700,180,1830,360))
    if not isinstance(titles, (list, tuple)):
        return None
    return '迷失之地-入口-周期' if '矩阵行动' in ''.join(str(row.data) for row in titles) else '迷失之地-入口-常规'


def detail_mission(ctx, screen):
    matches = ctx.ocr_service.get_ocr_result_list(image=screen, rect=DETAIL_TITLE)
    names = {name for match in matches if (name := mission_text(match.data)) is not None}
    if len(names) == 1:
        return names.pop()
    if names:
        return None
    # 某些版本特遣详情没有模式标题，使用完整的专属按钮与下一步双重确认。
    actions = ctx.ocr_service.get_ocr_result_list(image=screen, rect=DETAIL_ACTIONS)
    texts = {re.sub(r'\s+', '', str(match.data)) for match in actions}
    if '特遣任务' in texts and '下一步' in texts:
        return '特遣调查'
    return None


# Frontline-cleanup period buff cards, one per 周期增益 area: checkmark circle and left rim.
PERIOD_BUFF_ROWS = (453, 596, 740)


def period_buff_state(screen):
    """Return (selected_index, focused_index) for the three buff cards; None where absent. RGB input."""
    if not isinstance(screen, np.ndarray) or screen.shape[:2] != (1080, 1920):
        return None, None
    hsv = cv2.cvtColor(screen[380:820, 980:1790], cv2.COLOR_RGB2HSV)
    selected, focused = [], []
    for row in PERIOD_BUFF_ROWS:
        y = row - 380
        check = hsv[y-12:y+12, 776:800]
        # An unselected circle is a thin green ring (~10% of the box); the checkmark fills it.
        if (cv2.inRange(check, np.array([35, 120, 120]), np.array([85, 255, 255])) > 0).mean() > .25:
            selected.append(PERIOD_BUFF_ROWS.index(row))
        rim = hsv[y-40:y+40, 8:18]
        if (cv2.inRange(rim, np.array([20, 120, 150]), np.array([45, 255, 255])) > 0).mean() > .25:
            focused.append(PERIOD_BUFF_ROWS.index(row))
    return (selected[0] if len(selected) == 1 else None), (focused[0] if len(focused) == 1 else None)
