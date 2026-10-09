"""Verified controller navigation for background application menus."""
import numpy as np
from onedragon.base.geometry.rectangle import Rect
from src.controls.gamepad import is_ds4, press as pad

TABS=('目标','日常','训练','作战','战术')


def compendium_category(op, screen, target):
    """Choose a controller category and verify its blue selection next frame."""
    from difflib import SequenceMatcher
    rows=op.ctx.ocr_service.get_ocr_result_list(image=screen,rect=Rect(190,300,420,930))
    if not isinstance(rows,(list,tuple)):
        return op.round_retry('未识别快捷手册分类，未操作',wait=.6)
    target_row=None; selected=[]
    for row in rows:
        word=str(row.data).replace(' ','')
        if not word or not all('\u4e00' <= c <= '\u9fff' or c == '·' for c in word):
            continue
        if SequenceMatcher(None,word,target).ratio()>=.85:
            target_row=row
        y=row.center.y
        part=screen[max(0,y-22):y+22,195:415]
        if part.size and np.mean((part[:,:,2]>120)&(part[:,:,0]<140)&(part[:,:,2].astype(np.int16)-part[:,:,0]>40))>.35:
            selected.append(row)
    if target_row is None or len(selected)!=1:
        return op.round_retry('未核验唯一分类焦点或目标，未操作',wait=.6)
    current=selected[0]
    if abs(current.center.y-target_row.center.y)<25:
        return op.round_success('已核验快捷手册分类：'+target)
    count=getattr(op,'_pad_category_steps',0)
    if count>=12:
        return op.round_fail('手柄分类选择未生效：'+target)
    # B returns from the card list to categories; the selected category remains.
    # When already in categories use only the directional control.
    if any(w=='前往' for w in menu_words(op,Rect(1300,400,1650,940),screen)):
        part=screen[400:940,1300:1650]
        if np.mean((part[:,:,0]>170)&(part[:,:,1]>150)&(part[:,:,2]<100))>.02:
            pad_press(op,'b');op._pad_category_steps=count+1
            return op.round_retry('返回分类列表，等待实际焦点',wait=.6)
    pad_press(op,'dpad_up' if target_row.center.y<current.center.y else 'dpad_down')
    op._pad_category_steps=count+1
    return op.round_retry('手柄选择分类：'+target,wait=.6)


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
    focused=[]
    for row in goes:
        y=row.center.y;part=screen[y-28:y+28,1330:1610]
        if np.mean((part[:,:,0]>170)&(part[:,:,1]>150)&(part[:,:,2]<100))>.35:
            focused.append(row)
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
    op._pad_lost_go_sent=True
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
    names={'更多','勘域编队','邮件','设置','公告','成就','绳网','仓库','代理人','商城','丽都城募','调频'}
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
    pad_press(op,'dpad_left' if points[target].x<points[current].x else 'dpad_right')
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
        if not isinstance(footer,(tuple,list)) or not any(str(row.data).strip()=='返回'
                and 970<row.center.y<1060 for row in footer):
            return op.round_retry('快捷手册返回提示未显示，未操作',wait=.5)
        requests=getattr(op,'_compendium_back_requests',0)
        if requests>=3:
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
