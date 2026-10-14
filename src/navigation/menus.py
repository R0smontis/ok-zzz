"""Verified controller navigation for background application menus."""
import cv2
import numpy as np
from onedragon.base.geometry.rectangle import Rect
from src.controls.gamepad import is_ds4, press as pad

TABS=('目标','日常','训练','作战','战术')
MAIN_MENU_ITEMS=frozenset({'更多','勘域编队','邮件','设置','公告','成就','绳网','仓库','代理人','商城','丽都城募','调频'})

def verified_reward_mode(op, screen, enabled):
    """Set expert challenge 燃竭模式; verify page text, RS hint and each resulting frame."""
    rows = op.ctx.ocr_service.get_ocr_result_list(image=screen, rect=Rect(300, 430, 1910, 850))
    rows = rows if isinstance(rows, (list, tuple)) else []
    text = lambda row: str(row.data).strip().replace(' ', '')
    popup_text = ''.join(text(row) for row in rows if 450 < row.center.x < 1500 and 450 < row.center.y < 590)
    popup = '是否退出' in popup_text and '燃竭模式' in popup_text
    requests = getattr(op, '_reward_mode_requests', 0)
    if popup:
        confirm = next((row for row in rows if text(row) == '确认' and 1000 < row.center.x < 1300 and 570 < row.center.y < 690), None)
        if enabled:
            return op.round_fail('燃竭模式状态冲突：退出确认框仍在显示')
        if confirm is None or not label_focused(screen, confirm.center, half_width=130):
            return op.round_retry('未核验燃竭模式确认文字及手柄焦点，未操作', wait=1)
        if requests >= 4:
            return op.round_fail('燃竭模式确认后画面未变化')
        op._reward_mode_requests = requests + 1
        if getattr(op.ctx.controller, 'background_mode', False):
            pad_press(op, 'a')
        else:
            op.ctx.controller.click(confirm.center)
        return op.round_retry('确认退出燃竭模式，等待实际OFF状态', wait=1)
    labels = [row for row in rows if text(row) == '燃竭模式' and row.center.x > 1300 and 630 < row.center.y < 760]
    toggles = [row for row in rows if text(row).upper() in ('ON', 'OFF') and 1640 < row.center.x < 1790 and 630 < row.center.y < 760]
    if len(labels) != 1 or len(toggles) != 1:
        return op.round_retry('未核验燃竭模式及ON/OFF文字，未操作', wait=1)
    target = 'ON' if enabled else 'OFF'
    if text(toggles[0]).upper() == target:
        op._reward_mode_requests = 0
        return op.round_success('已核验燃竭模式：' + target)
    if requests >= 4:
        return op.round_fail('燃竭模式切换未生效：' + target)
    if getattr(op.ctx.controller, 'background_mode', False):
        hints = [row for row in rows if text(row).upper() == 'RS' and 1530 < row.center.x < 1700 and abs(row.center.y - toggles[0].center.y) < 35]
        if len(hints) != 1:
            return op.round_retry('未核验燃竭模式RS按键提示，未操作', wait=1)
        pad_press(op, 'r_thumb')
    else:
        op.ctx.controller.click(toggles[0].center)
    op._reward_mode_requests = requests + 1
    return op.round_retry('切换燃竭模式，等待实际' + target + '状态', wait=1)



def compendium_category(op, screen, target):
    """Choose a controller category and verify its blue selection next frame."""
    from difflib import SequenceMatcher
    rows=op.ctx.ocr_service.get_ocr_result_list(image=screen,rect=Rect(190,300,420,930))
    if not isinstance(rows,(list,tuple)):
        return op.round_retry('未识别快捷手册分类，未操作',wait=.6)
    target_row=None; selected=[]; best=.6
    for row in rows:
        word=str(row.data).replace(' ','')
        if not word or not all('\u4e00' <= c <= '\u9fff' or c == '·' for c in word):
            continue
        # Category names differ a lot; OCR may swap one glyph (式舆 → 式奥), so take the best clear match.
        ratio=SequenceMatcher(None,word,target).ratio()
        if ratio>=best:
            target_row,best=row,ratio
        y=row.center.y
        part=screen[max(0,y-22):y+22,195:415]
        if part.size and np.mean((part[:,:,2]>120)&(part[:,:,0]<140)&(part[:,:,2].astype(np.int16)-part[:,:,0]>40))>.35:
            selected.append(row)
    # A selected category can contain a second status line (e.g. an unset goal).
    # Count highlighted controls, not OCR lines; the first line names the control.
    controls=[]
    for row in sorted(selected,key=lambda item:item.center.y):
        if controls:
            band=screen[controls[-1].center.y:row.center.y+1,195:415]
            blue=(band[:,:,2]>120)&(band[:,:,0]<140)&(band[:,:,2].astype(np.int16)-band[:,:,0]>40)
            if band.size and np.all(np.mean(blue,axis=1)>.35):
                continue
        controls.append(row)
    selected=controls
    if target_row is None or len(selected)!=1:
        # Right after a tab switch the category list is still animating; give it a few frames.
        waits=getattr(op,'_pad_category_unverified',0)
        if waits<6:
            op._pad_category_unverified=waits+1
            return op.round_wait('等待分类列表稳定，未操作',wait=.6)
        read=' / '.join(str(r.data) for r in rows)
        return op.round_retry(f'未核验唯一分类焦点或目标（{target}；读到：{read}；选中 {len(selected)} 项），未操作',wait=.6)
    current=selected[0]
    if abs(current.center.y-target_row.center.y)<25:
        return op.round_success('已核验快捷手册分类：'+target)
    count=getattr(op,'_pad_category_steps',0)
    if count>=12:
        return op.round_fail('手柄分类选择未生效：'+target)
    # B returns from the card list to categories; the selected category remains.
    # When already in categories use only the directional control.
    # Each verified press waits (not retries): reaching a lower category takes more presses than
    # the node's retry budget, and _pad_category_steps already bounds the loop.
    if panel_button_focused(screen):
        # Empty training-goal pages may focus a setup button instead of 前往.
        # Return from any verified card-panel button, not only populated cards.
        pad_press(op,'b');op._pad_category_steps=count+1
        return op.round_wait('返回分类列表，等待实际焦点',wait=.6)
    pad_press(op,'dpad_up' if target_row.center.y<current.center.y else 'dpad_down')
    op._pad_category_steps=count+1
    return op.round_wait('手柄选择分类：'+target,wait=.6)


def focus_mask(part):
    """Controller focus fill; it pulses between yellow (≈247,219,0) and yellow-green (≈152,190,0)."""
    return (part[:,:,0]>120)&(part[:,:,1]>150)&(part[:,:,2]<100)


def label_focused(screen, center, half_width=150):
    """Whether the button whose label is centred at `center` carries the controller focus fill."""
    part=screen[max(0,center.y-28):center.y+28,max(0,center.x-half_width):center.x+half_width]
    return bool(part.size) and np.mean(focus_mask(part))>.35


def go_focused(screen, y):
    """Whether the 前往 button at row y carries the controller focus; unfocused buttons are near black."""
    part=screen[max(0,y-28):y+28,1330:1610]
    return bool(part.size) and np.mean(focus_mask(part))>.35


def panel_button_focused(screen):
    """Whether any solid button in the card panel carries the focus (e.g. the 周期挑战 header button).

    Card outlines and progress bars are excluded by requiring a filled, button-sized region.
    """
    mask=focus_mask(screen[220:950,480:1700]).astype(np.uint8)
    _,_,stats,_=cv2.connectedComponentsWithStats(mask)
    return any(w>150 and h>40 and area>.5*w*h for _,_,w,h,area in stats[1:])


def compendium_card(op, screen, is_target, label):
    """Focus the 前往 button of the card whose title matches, scrolling the list with the d-pad.

    Window-message drags do not scroll this list; the d-pad moves focus card by card and the list follows.
    Every press is verified on the next frame; the end of the list reverses the search direction.
    """
    # Card lists start at y≈320 (实战模拟室) or below a challenge header (恶名狩猎); header text never matches a target.
    rows=op.ctx.ocr_service.get_ocr_result_list(image=screen,rect=Rect(500,300,1650,950))
    if not isinstance(rows,(list,tuple)):
        return op.round_retry(f'未识别{label}所在卡片，未操作',wait=.6)
    text=lambda r: str(r.data).replace(' ','')
    goes=[r for r in rows if text(r)=='前往']
    # Item icons produce stray glyphs ("2", "®"); card titles have at least two CJK characters.
    titles=[r for r in rows if r.center.x<1200 and sum('一'<=c<='鿿' for c in text(r))>=2]
    seen=getattr(op,'_pad_card_seen',[])
    seen.extend(t for t in (text(r) for r in titles) if t not in seen)
    op._pad_card_seen=seen
    count=getattr(op,'_pad_card_steps',0)
    if count>=30:
        return op.round_fail(f'手柄未找到{label}的前往按钮；列表中的卡片：{" / ".join(seen) or "无"}')
    op._pad_card_steps=count+1
    focused=[r for r in goes if go_focused(screen,r.center.y)]
    if not focused:
        if panel_button_focused(screen):
            # Focus enters on a header button above the cards (e.g. 周期挑战).
            pad_press(op,'dpad_down')
            return op.round_wait('手柄移入卡片列表，等待实际焦点',wait=.6)
        # Category level, or keyboard prompts where the first controller press only switches prompts.
        pad_press(op,'a')
        return op.round_wait('打开已选分类的卡片列表，等待实际焦点',wait=1)
    if len(focused)!=1:
        return op.round_retry('未核验唯一前往按钮焦点，未操作',wait=.6)
    current=focused[0]
    target=next((t for t in titles if is_target(text(t))),None)
    if target is not None:
        go=min((r for r in goes if target.center.y<r.center.y<target.center.y+190),key=lambda r:r.center.y,default=None)
        if go is not None and abs(go.center.y-current.center.y)<=25:
            pad_press(op,'a')
            op._pad_go_sent=True
            return op.round_success(f'已核验{label}，手柄前往',wait=1)
        direction='dpad_down' if go is None or current.center.y<go.center.y else 'dpad_up'
    else:
        direction=getattr(op,'_pad_card_direction','dpad_down')
        title=next((text(t) for t in titles if current.center.y-190<t.center.y<current.center.y),None)
        if title is not None and title==getattr(op,'_pad_card_last_title',None):
            direction='dpad_up' if direction=='dpad_down' else 'dpad_down'  # Focus did not move: list end.
        op._pad_card_direction=direction
        op._pad_card_last_title=title
    pad_press(op,direction)
    return op.round_wait(f'手柄查找{label}，等待实际焦点',wait=.6)


def combat_simulation_mission(op, screen, target, names):
    """Focus the 实战模拟室 mission tile; the focused tile is the selection, so nothing is confirmed.

    Window-message clicks are ignored on this screen. The focused tile carries the yellow-green border.
    The game's tile order can differ from the compendium order and the row may wrap around, so the
    d-pad direction comes from the visible tiles; an off-screen target is searched in one direction.
    """
    from difflib import get_close_matches
    rows=op.ctx.ocr_service.get_ocr_result_list(image=screen,rect=Rect(80,700,1850,900))
    if not isinstance(rows,(list,tuple)):
        return op.round_retry('未识别实战模拟室副本，未操作',wait=.6)
    focused=[]; visible={}
    for row in rows:
        # Close names such as 击破演练/命破演练 need a strict cutoff.
        match=get_close_matches(str(row.data).replace(' ',''),names,n=1,cutoff=.8)
        if not match:
            continue
        x=row.center.x
        visible[match[0]]=x
        part=screen[700:880,max(0,x-90):x+250]
        if part.size and np.mean(focus_mask(part))>.04:
            focused.append(match[0])
    if len(focused)!=1:
        return op.round_retry('未核验唯一副本焦点，未操作',wait=.6)
    current=focused[0]
    if current==target:
        return op.round_success('已核验副本焦点：'+target)
    count=getattr(op,'_pad_mission_steps',0)
    if count>=2*len(names)+2:
        return op.round_fail('手柄副本选择未生效：'+target)
    op._pad_mission_steps=count+1
    if target in visible:
        direction='dpad_right' if visible[target]>visible[current] else 'dpad_left'
    else:
        direction=getattr(op,'_pad_mission_direction','dpad_right')
        if current==getattr(op,'_pad_mission_last',None):
            direction='dpad_left' if direction=='dpad_right' else 'dpad_right'  # Focus did not move: row end.
    op._pad_mission_direction=direction
    op._pad_mission_last=current
    pad_press(op,direction)
    return op.round_wait(f'手柄选择副本：{current} → {target}',wait=.6)


def grid_target(op, screen, target, rect, half_width=66):
    """Move the outlined focus of an icon grid (e.g. 功能导览) to the labelled cell and press A.

    A cell is focused when the outline lights both of its vertical edges; NEW! badges and the
    neighbour's outline only ever light one edge.
    """
    rows=op.ctx.ocr_service.get_ocr_result_list(image=screen,rect=rect)
    rows=rows if isinstance(rows,(list,tuple)) else []
    cells=[r for r in rows if sum('一'<=c<='鿿' for c in str(r.data))>=2]
    def lit(r):
        x,y=r.center.x,r.center.y
        edge=lambda cx: screen[max(0,y-90):y+10,max(0,cx-4):cx+4]
        return all(np.mean(focus_mask(edge(cx)))>.3 for cx in (x-half_width,x+half_width))
    focused=[r for r in cells if lit(r)]
    wanted=next((r for r in cells if str(r.data).replace(' ','')==target),None)
    if wanted is None or len(focused)!=1:
        # Keyboard prompts show no outline; the first d-pad press only reveals it.
        steps=getattr(op,'_pad_grid_reveal',0)
        if wanted is not None and not focused and steps<2:
            op._pad_grid_reveal=steps+1
            pad_press(op,'dpad_down')
            return op.round_wait('手柄显示焦点，等待实际画面',wait=.8)
        return op.round_retry(f'未核验{target}及唯一焦点，未操作',wait=.6)
    current=focused[0]
    count=getattr(op,'_pad_grid_steps',0)
    if count>=12:
        return op.round_fail(f'手柄选择{target}未生效')
    op._pad_grid_steps=count+1
    if current is wanted:
        pad_press(op,'a')
        return op.round_success(f'手柄打开{target}',wait=1.5)
    dx,dy=wanted.center.x-current.center.x,wanted.center.y-current.center.y
    button=('dpad_down' if dy>0 else 'dpad_up') if abs(dy)>40 else ('dpad_right' if dx>0 else 'dpad_left')
    pad_press(op,button)
    return op.round_wait(f'手柄选择{target}：{current.data} → {target}',wait=.6)


def press_labelled(op, screen, label, rect):
    """Press the controller button printed just left of a visible label (e.g. 「B 退出」).

    Returns the pressed button, or None when the label or its button glyph is not on screen,
    so callers never assume a press that the game could not have received.
    """
    rows=op.ctx.ocr_service.get_ocr_result_list(image=screen,rect=rect)
    rows=rows if isinstance(rows,(list,tuple)) else []
    text=lambda r: str(r.data).replace(' ','')
    target=next((r for r in rows if text(r).endswith(label)),None)
    if target is None:
        return None
    merged=text(target)[:-len(label)]  # OCR may read 「B退出」 as one word.
    glyphs=[merged] if merged in ('A','B','X','Y') else [
        text(r) for r in rows if text(r) in ('A','B','X','Y')
        and abs(r.center.y-target.center.y)<22 and 0<target.center.x-r.center.x<180]
    if not glyphs:
        return None
    button=glyphs[-1].lower()
    pad_press(op,button)
    return button


def pad_next_step(op):
    """Dungeon entry pages bind 下一步 to the menu button (≡) and ignore window-message clicks."""
    result=op.round_by_find_area(op.last_screenshot,'实战模拟室','下一步')
    if not result.is_success:
        return op.round_retry('尚未识别下一步，未操作',wait=1)
    requests=getattr(op,'_pad_next_requests',0)
    if requests>=5:
        return op.round_fail('手柄下一步后画面未变化')
    op._pad_next_requests=requests+1
    pad_press(op,'start')
    return op.round_wait('手柄下一步，等待出战画面',wait=1)


def predefined_team(op, screen, target, names):
    """Focus a predefined team in the two-column team list and select it with A.

    The focused card has the yellow-green outline along its top edge, about 33 px above its title centre.
    `names` is the configured team order; it decides the d-pad direction when the target is off screen.
    """
    import re
    rows=op.ctx.ocr_service.get_ocr_result_list(image=screen,rect=Rect(60,80,1860,990))
    if not isinstance(rows,(list,tuple)):
        return op.round_retry('未识别预备编队列表，未操作',wait=.6)
    titles={}
    for row in rows:
        name=re.sub(r'[A-Za-z]+$','',str(row.data).replace(' ',''))  # 编队1RS: the RS hint follows the title.
        if name in names:
            titles[name]=row
    focused=[]
    for name,row in titles.items():
        y=row.center.y-33  # Title centre to the card's top edge.
        band=screen[max(0,y-6):y+6,max(0,row.center.x-60):row.center.x+640]
        if band.size and np.mean(focus_mask(band))>.15:
            focused.append(name)
    if len(focused)!=1:
        return op.round_retry('未核验唯一编队焦点，未操作',wait=.6)
    current=focused[0]
    if current==target:
        pad_press(op,'a')
        return op.round_success('已选择预备编队：'+target,wait=1)
    count=getattr(op,'_pad_team_steps',0)
    if count>=24:
        return op.round_fail('手柄预备编队选择未生效：'+target)
    op._pad_team_steps=count+1
    gap=names.index(target)-names.index(current)
    if abs(gap)>=2 or (abs(gap)==1 and names.index(min(target,current,key=names.index))%2==1):
        button='dpad_down' if gap>0 else 'dpad_up'  # Different row of the two-column grid.
    else:
        button='dpad_right' if gap>0 else 'dpad_left'
    pad_press(op,button)
    return op.round_wait(f'手柄选择预备编队：{current} → {target}',wait=.6)


def compendium_lost_void(op, screen):
    rows=op.ctx.ocr_service.get_ocr_result_list(image=screen,rect=Rect(500,440,1650,950))
    if not isinstance(rows,(list,tuple)):
        return op.round_retry('未识别迷失之地卡片，未操作',wait=.6)
    title=next((r for r in rows if str(r.data).replace(' ','')=='迷失之地'),None)
    goes=[r for r in rows if str(r.data).replace(' ','')=='前往']
    if title is None or not goes:
        return op.round_retry('未核验迷失之地及前往按钮，未操作',wait=.6)
    target=min((r for r in goes if title.center.y<r.center.y<title.center.y+190),key=lambda r:r.center.y,default=None)
    if target is None:
        return op.round_retry('未核验迷失之地对应按钮，未操作',wait=.6)
    focused=[r for r in goes if go_focused(screen,r.center.y)]
    count=getattr(op,'_pad_lost_go_steps',0)
    if count>=8:
        return op.round_fail('迷失之地前往确认未生效')
    op._pad_lost_go_steps=count+1
    if not focused:
        if getattr(op, '_pad_lost_list_requested', False):
            return op.round_retry('等待已发送的卡片列表请求显示实际焦点，未重复确认', wait=.6)
        pad_press(op,'a')
        op._pad_lost_list_requested = True
        return op.round_retry('打开已选分类的卡片列表，等待实际焦点',wait=1)
    if len(focused)!=1:
        return op.round_retry('未核验唯一前往按钮焦点，未操作',wait=.6)
    current=focused[0]
    if abs(current.center.y-target.center.y)>25:
        pad_press(op,'dpad_down' if current.center.y<target.center.y else 'dpad_up')
        return op.round_retry('手柄选择迷失之地前往按钮',wait=.6)
    pad_press(op,'a')
    op._pad_go_sent=True
    return op.round_success('已核验迷失之地目标，手柄前往',wait=1)


def lost_void_gateway_visible(op, screen):
    from difflib import SequenceMatcher
    left=menu_words(op,Rect(260,790,720,920),screen)
    right=menu_words(op,Rect(1250,820,1800,960),screen)
    return any('迷失之地' in w for w in left) and any(SequenceMatcher(None,'枯萎之都',w).ratio()>=.75 for w in right)


def lost_void_gateway(op, screen):
    if not lost_void_gateway_visible(op, screen):
        return None
    def marker(rect):
        part=screen[rect.y1:rect.y2,rect.x1:rect.x2].astype(np.int16)
        if is_ds4(op.ctx):
            active=(part[:,:,2]>90)&(part[:,:,2]>part[:,:,0]*1.3)&(part[:,:,2]>part[:,:,1]*1.2)
        else:
            active=(part[:,:,1]>70)&(part[:,:,1]>part[:,:,0]*1.5)&(part[:,:,1]>part[:,:,2]*1.3)
        return np.mean(active)>.01
    focused=[marker(Rect(430,910,490,960)),marker(Rect(1400,925,1470,985))]
    if sum(focused)!=1:
        return op.round_retry('未核验深层调查唯一选择标记，未操作',wait=.6)
    count=getattr(op,'_pad_gateway_steps',0)
    if count>=4:
        return op.round_fail('迷失之地入口手柄确认未生效')
    op._pad_gateway_steps=count+1
    pad_press(op,'a' if focused[0] else 'dpad_left')
    return op.round_retry('手柄进入迷失之地，等待实际入口' if focused[0] else '选择迷失之地卡片，等待实际标记',wait=1)


def pad_press(op, button, duration=.12):
    pad(op.ctx, button, duration)


def menu_words(op, rect, screen=None):
    rows=op.ctx.ocr_service.get_ocr_result_list(image=op.last_screenshot if screen is None else screen,rect=rect)
    return [str(r.data).strip().replace(' ','') for r in rows] if isinstance(rows,(list,tuple)) else []


def selected_tab(op, rect, names):
    """Read the highlighted controller tab without changing focus."""
    rows=op.ctx.ocr_service.get_ocr_result_list(image=op.last_screenshot,rect=rect)
    active=[]
    if not isinstance(rows,(list,tuple)):
        return None
    for row in rows:
        name=str(row.data).replace(' ','')
        if name not in names:
            continue
        x,y=row.center.x,row.center.y
        part=op.last_screenshot[max(0,y-25):y+25,max(0,x-65):x+65]
        if part.size and np.mean((part[:,:,0]>150)&(part[:,:,1]>140)&(part[:,:,2]<100))>.3:
            active.append(name)
    return active[0] if len(active)==1 else None


def main_menu_target(op, target):
    rows=op.ctx.ocr_service.get_ocr_result_list(image=op.last_screenshot,rect=Rect(220,920,1730,1070),crop_first=False)
    names=MAIN_MENU_ITEMS
    if not isinstance(rows,(tuple,list)):
        return op.round_retry('未识别主菜单，未操作',wait=.5)
    points={str(r.data).replace(' ',''):r.center for r in rows if str(r.data).replace(' ','') in names}
    if len(points)<8 or target not in points:
        return op.round_retry('主菜单选项不完整，未操作',wait=.5)
    active=[]
    for name,p in points.items():
        part=op.last_screenshot[930:1060,max(0,p.x-45):p.x+45]
        if np.mean((part[:,:,0]>125)&(part[:,:,1]>150)&(part[:,:,2]<80))>.5:
            active.append(name)
    if len(active)!=1:
        return op.round_retry('未核验唯一主菜单焦点，未操作',wait=.5)
    current=active[0]
    count=getattr(op,'_pad_menu_steps',0)
    if count>=16:
        return op.round_fail(f'主菜单未打开目标：{target}，当前：{current}')
    op._pad_menu_steps=count+1
    if current==target:
        confirmations=getattr(op,'_pad_menu_confirms',0)
        if confirmations>=3:
            return op.round_fail(f'主菜单确认未生效：{target}')
        pad_press(op,'a');op._pad_menu_confirms=confirmations+1
        return op.round_wait(f'手柄打开{target}，等待实际页面',wait=1)
    left=points[target].x<points[current].x
    if len(points)==len(names):
        # The bar wraps around (live 2026-10-12: left from 更多 lands on 调频): take the short way.
        order=sorted(points,key=lambda n:points[n].x)
        steps=(order.index(target)-order.index(current))%len(order)
        left=steps*2>len(order) or (steps*2==len(order) and left)  # A tie keeps the direct way.
    pad_press(op,'dpad_left' if left else 'dpad_right')
    return op.round_wait(f'手柄选择主菜单：{current} → {target}',wait=.6)


def compendium_tab(op, screen, target):
    targets={f'快捷手册-{name}':name for name in TABS}
    returning = target == '大世界-普通'
    if target not in targets and not returning:
        return None
    if not isinstance(screen,np.ndarray):
        return op.round_retry('快捷手册画面无效，未操作',wait=.5)
    rows=op.ctx.ocr_service.get_ocr_result_list(image=screen,rect=Rect(690,105,1660,210))
    if not isinstance(rows,(tuple,list)):
        return op.round_retry('未识别快捷手册页签，未操作',wait=.5)
    positions={str(row.data).replace(' ',''):row.center for row in rows
               if str(row.data).replace(' ','') in TABS and 105<row.center.y<210}
    if len(positions)!=len(TABS):
        return op.round_retry('快捷手册页签不完整，未操作',wait=.5)
    active=[]
    for name,center in positions.items():
        part=screen[max(0,center.y-32):center.y+32,max(0,center.x-65):center.x+65]
        if part.size and np.mean((part[:,:,0]>170)&(part[:,:,1]>140)&(part[:,:,2]<100))>.2:
            active.append(name)
    if len(active)!=1:
        return op.round_retry('未核验唯一选中页签，未操作',wait=.5)
    current=active[0]
    if returning:
        footer=op.ctx.ocr_service.get_ocr_result_list(image=screen,rect=Rect(750,970,1230,1060))
        if not isinstance(footer,(tuple,list)):
            return op.round_retry('快捷手册返回提示未显示，未操作',wait=.5)
        words=[str(row.data).strip() for row in footer if 970<row.center.y<1060]
        # OCR may merge the button glyph into the label ("B返回"). An empty footer means the game shows
        # keyboard prompts; the first controller press only switches it to controller prompts.
        if words and not any(word.endswith('返回') for word in words):
            return op.round_retry('快捷手册返回提示未显示，未操作',wait=.5)
        requests=getattr(op,'_compendium_back_requests',0)
        if requests>=4:
            return op.round_fail('快捷手册返回大世界未生效')
        pad(op.ctx, 'b')
        op._compendium_back_requests=requests+1
        return op.round_wait('手柄关闭快捷手册，等待实际大世界',wait=1)
    if current==targets[target]:
        op._compendium_tab_requests=None
        return op.round_success(target)
    previous,count=getattr(op,'_compendium_tab_requests',None) or (None,0)
    signature=(current,target)
    count=count if previous==signature else 0
    if count>=3:
        return op.round_fail(f'快捷手册页签切换未生效：{current} → {targets[target]}')
    direction='lb' if TABS.index(targets[target])<TABS.index(current) else 'rb'
    pad(op.ctx, direction)
    op._compendium_tab_requests=(signature,count+1)
    return op.round_wait(f'手柄切换快捷手册页签：{current} → {targets[target]}，等待实际画面',wait=.8)


def escape_stuck(op, screen):
    """Leave a battle that will not end (e.g. 勘域「喧闹」): menu → 更多 → 脱离卡死.

    Verified live 2026-10-14: in the battle HUD START opens the main menu (View does not),
    and 脱离卡死 teleports to a safe spot at once, without a confirmation dialog.
    """
    from src.navigation.redemption import GRID_HALF_WIDTH, MORE_GRID, more_panel_open
    if more_panel_open(op, screen):
        result = grid_target(op, screen, '脱离卡死', MORE_GRID, half_width=GRID_HALF_WIDTH)
        if result.is_success:
            op._pad_escape_sent = True
            return op.round_wait('手柄脱离卡死，等待实际画面', wait=2)
        return result
    rows = op.ctx.ocr_service.get_ocr_result_list(image=screen, rect=Rect(220, 920, 1730, 1070), crop_first=False)
    rows = rows if isinstance(rows, (list, tuple)) else []
    if sum(str(r.data).replace(' ', '') in MAIN_MENU_ITEMS for r in rows) >= 8:
        return main_menu_target(op, '更多')
    opens = getattr(op, '_pad_escape_menu', 0)
    if opens >= 3:
        return op.round_fail('手柄打开菜单脱离卡死未生效')
    op._pad_escape_menu = opens + 1
    pad_press(op, 'start')
    return op.round_wait('手柄打开菜单以脱离卡死', wait=1.2)
