# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/application/ridu_weekly/ridu_weekly_app.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from cv2.typing import MatLike
import cv2
import numpy as np
from onedragon.base.geometry.rectangle import Rect
from src.navigation.menus import menu_words, pad_press, compendium_tab

from onedragon.base.operation.operation_edge import node_from
from onedragon.base.operation.operation_node import operation_node
from onedragon.base.operation.operation_notify import node_notify, NotifyTiming
from onedragon.base.operation.operation_round_result import OperationRoundResult
from zzz_od.application.ridu_weekly import ridu_weekly_const
from zzz_od.application.zzz_application import ZApplication
from zzz_od.context.zzz_context import ZContext
from zzz_od.operation.back_to_normal_world import BackToNormalWorld


class RiduWeeklyApp(ZApplication):

    """丽都周纪:领取周纪的积分/奖励。周限、无体力消耗。"""

    def __init__(self, ctx: ZContext):
        ZApplication.__init__(
            self,
            ctx=ctx,
            app_id=ridu_weekly_const.APP_ID,
            op_name=ridu_weekly_const.APP_NAME,
        )
        self.timeout_seconds=150

    def handle_init(self):
        self._pad_weekly_open=0
        self._pad_weekly_entry_steps=0
        self._pad_weekly_score=0
        self._pad_weekly_rewards=0

    def _weekly_page(self):
        words=menu_words(self,Rect(100,140,1820,940))
        return any('三格连线' in w for w in words) and '累计获取积分' in words and '积分特赏' in words

    @operation_node(name='返回大世界', is_start_node=True)
    def back_at_first(self) -> OperationRoundResult:
        op = BackToNormalWorld(self.ctx)
        return self.round_by_op_result(op.execute())

    @node_from(from_name='返回大世界')
    @operation_node(name='日常')
    def choose_daily(self) -> OperationRoundResult:
        return self.round_by_goto_screen(screen_name='快捷手册-日常')

    @node_from(from_name='日常')
    @operation_node(name='丽都周纪')
    def click_schedule(self) -> OperationRoundResult:
        if getattr(self.ctx.controller,'background_mode',False):
            if self._weekly_page():
                return self.round_success('已核验丽都周纪任务页')
            tab=compendium_tab(self,self.last_screenshot,'快捷手册-日常')
            if not tab.is_success:
                return tab
            rows=self.ctx.ocr_service.get_ocr_result_list(image=self.last_screenshot,rect=Rect(350,800,1680,900))
            entries=[r for r in rows if str(r.data).replace(' ','')=='丽都周纪'] if isinstance(rows,(list,tuple)) else []
            if len(entries)>1:
                return self.round_retry('周纪入口不唯一，未操作',wait=1)
            selected=False
            if entries:
                p=entries[0].center
                part=self.last_screenshot[max(0,p.y-28):p.y+28,max(0,p.x-120):p.x+120]
                selected=part.size and np.mean((part[:,:,0]>150)&(part[:,:,1]>140)&(part[:,:,2]<100))>.2
            if not selected:
                if '今日最大活跃度' not in menu_words(self,Rect(400,220,650,330)):
                    return self.round_retry('未核验日常任务卡片，未操作',wait=1)
                if self._pad_weekly_entry_steps>=12:
                    return self.round_fail('周纪入口滚动定位未生效')
                pad_press(self,'dpad_left')
                self._pad_weekly_entry_steps+=1
                return self.round_wait('向左定位丽都周纪，等待入口及焦点实际显示',wait=.6)
            if self._pad_weekly_open>=3:
                return self.round_fail('丽都周纪入口确认未生效')
            pad_press(self,'a');self._pad_weekly_open+=1
            return self.round_retry('打开丽都周纪，等待真实任务页',wait=1)
        return self.round_by_find_and_click_area(self.last_screenshot, '丽都周纪', '丽都周纪',
                                                 success_wait=2, retry_wait=1)

    @node_from(from_name='丽都周纪')
    @operation_node(name='领取积分')
    def claim_score(self, screen: MatLike = None) -> OperationRoundResult:
        if getattr(self.ctx.controller,'background_mode',False):
            if not self._weekly_page():
                return self.round_retry('未核验周纪积分页，未操作',wait=1)
            candidates=[];focus=[]
            for i in range(9):
                x,y=120+(i%3)*314,240+(i//3)*230
                strip=self.last_screenshot[y+175:y+225,x+10:x+300]
                yellow=(strip[:,:,0]>150)&(strip[:,:,1]>140)&(strip[:,:,2]<100)
                if np.mean(yellow)>.3:
                    candidates.append(i)
                part=self.last_screenshot[y:y+228,x:x+312]
                mask=((part[:,:,0]>150)&(part[:,:,1]>140)&(part[:,:,2]<100)).astype(np.uint8)
                contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
                if any(cv2.boundingRect(c)[2]>280 and cv2.boundingRect(c)[3]>205 for c in contours):
                    focus.append(i)
            if not candidates:
                return self.round_fail('已核验无可领取积分')
            if len(focus)!=1:
                return self.round_retry('未核验周纪格子焦点，未操作',wait=1)
            current,target=focus[0],candidates[0]
            if current==target:
                if '领取' not in menu_words(self,Rect(1100,855,1400,930)):
                    return self.round_retry('未核验积分领取按钮，未操作',wait=1)
                if self._pad_weekly_score>=12:
                    return self.round_fail('周纪积分领取未改变画面')
                pad_press(self,'a');self._pad_weekly_score+=1
                return self.round_wait('领取已达成周纪积分，等待格子变为完成',wait=1)
            if current%3!=target%3:
                direction='left' if current%3>target%3 else 'right'
            else:
                direction='up' if current//3>target//3 else 'down'
            pad_press(self,'dpad_'+direction)
            return self.round_wait('定位实际可领取周纪格子',wait=.6)
        if screen is None:
            screen = self.last_screenshot

        for i in range(3):
            area = self.ctx.screen_loader.get_area('丽都周纪', f'积分行-{i+1}')

            result = self.round_by_ocr_and_click(screen, '100', area=area,
                                                 lcs_percent=1,
                                                 color_range=[(250, 250, 250), (255, 255, 255)])

            if result.is_success:
                return self.round_wait(result.status, wait=0.5)

        return self.round_retry(result.status, wait=0.5)

    @node_from(from_name='领取积分', success=False)  # 没有100积分之后
    @node_notify(when=NotifyTiming.CURRENT_DONE)
    @operation_node(name='领取奖励')
    def confirm_schedule(self) -> OperationRoundResult:
        if getattr(self.ctx.controller,'background_mode',False):
            words=menu_words(self,Rect(500,300,1450,950))
            if '确认' in words and any('获得' in w for w in words):
                pad_press(self,'a')
                return self.round_retry('确认周纪积分特赏，等待真实任务页',wait=1)
            if not self._weekly_page() or '领取积分特赏' not in menu_words(self,Rect(1000,980,1220,1060)):
                return self.round_retry('未核验周纪奖励页，未操作',wait=1)
            part=self.last_screenshot[1004:1044,1065:1190]
            if np.mean(np.all(part>190,axis=2))<.04:
                return self.round_success('已核验当前可领取周纪奖励处理完毕')
            if self._pad_weekly_rewards>=3:
                return self.round_fail('周纪积分特赏领取未生效')
            pad_press(self,'x');self._pad_weekly_rewards+=1
            return self.round_retry('领取周纪积分特赏，等待实际获得奖励',wait=1)
        return self.round_by_click_area('丽都周纪', '领取奖励',
                                        success_wait=1, retry_wait=1)

    @node_from(from_name='领取奖励')
    @operation_node(name='完成后返回')
    def finish(self) -> OperationRoundResult:
        op = BackToNormalWorld(self.ctx)
        return self.round_by_op_result(op.execute())


def __debug():
    ctx = ZContext()
    ctx.init_by_config()
    app = RiduWeeklyApp(ctx)
    app.execute()


if __name__ == '__main__':
    __debug()
