"""Recognize one dialogue action from the current frame, without sending input."""
from dataclasses import dataclass

from onedragon.base.geometry.point import Point
from onedragon.base.geometry.rectangle import Rect
from onedragon.base.screen import screen_utils
from onedragon.utils import cv2_utils, str_utils
from zzz_od.operation.enter_game.game_startup import startup_word


@dataclass(frozen=True)
class DialogueAction:
    kind: str
    point: Point
    text: str


class DialogueDetector:
    WHITE = [[220, 220, 220], [255, 255, 255]]

    def __init__(self, ctx):
        self.ctx = ctx

    def _area(self, name):
        return self.ctx.screen_loader.get_area('委托助手', name)

    def _ocr(self, screen, name, white=False):
        return self.ctx.ocr_service.get_ocr_result_list(
            image=screen, rect=self._area(name).rect,
            color_range=self.WHITE if white else None)

    def _found(self, screen, screen_name, area_name):
        return screen_utils.find_area(self.ctx, screen, screen_name, area_name) == screen_utils.FindAreaResultEnum.TRUE

    @staticmethod
    def _text(record):
        return str(record.data).strip().replace(' ', '')

    def has_dialogue(self, screen):
        area = self._area('对话框内容')
        if not cv2_utils.is_in_gray_mask(screen, rect=area.rect):
            return False
        words = [self._text(record) for record in self._ocr(screen, '对话框内容')]
        if any(startup_word(word) for word in words):
            # The title's 「点击进入游戏」 slot and the launch splash's health advisory sit where dialogue text goes.
            return False
        return any(str_utils.with_chinese(word) for word in words)

    def skip_confirmation(self, screen):
        # A generic "确认" can belong to purchases or other menus. Require
        # an explicit skip prompt, even after we clicked a skip button.
        prompt = self.ctx.ocr_service.get_ocr_result_list(
            image=screen, rect=Rect(600, 300, 1320, 780))
        if not any('跳过' in self._text(record) for record in prompt):
            return None
        for record in self._ocr(screen, '对话框确认'):
            if self._text(record) == '确认':
                return DialogueAction('confirm_skip', record.center, '确认跳过')
        return None

    def detect(self, screen, mode='跳过剧情', option='最后一个', *, menu_opened=False):
        if screen is None or screen.shape[:2] != (1080, 1920) or self.ctx.ocr_service is None:
            return None
        # Exploration and combat HUDs must never be interpreted as dialogue.
        if self._found(screen, '战斗画面', '按键-普通攻击'):
            return None
        controls = {self._text(record): record for record in self._ocr(screen, '文本-剧情右上角', white=True)
                    if self._text(record) in ('跳过', '菜单', '自动')}
        if any(self._text(record) in ('玩法引导', '战斗引导')
               for record in self._ocr(screen, '玩法引导')):
            return None
        if mode == '跳过剧情':
            confirmation = self.skip_confirmation(screen)
            if confirmation is not None:
                return confirmation
            if '跳过' in controls:
                record = controls['跳过']
                return DialogueAction('skip', record.center, '跳过剧情')
        # Dialogue screens and story menus differ from general secondary menus.
        if not controls and any(self._found(screen, s, a) for s, a in (
                ('委托助手', '左上角返回'), ('大世界-勘域', '勘域-菜单'),
                ('委托助手', '战斗-菜单'), ('委托助手', '标题-短信'))):
            return None
        if mode == '等待剧情自动播放' and menu_opened:
            for record in self._ocr(screen, '按钮-自动', white=True):
                if self._text(record) == '自动':
                    return DialogueAction('auto', record.center, '开启剧情自动播放')
        if mode in ('跳过剧情', '等待剧情自动播放') and '菜单' in controls:
            record = controls['菜单']
            return DialogueAction('menu', record.center, '展开剧情菜单')

        with_dialog = self.has_dialogue(screen)
        center_choice = self._found(screen, '委托助手', '中间选项区域')
        # Text in an option ROI alone can be a quest tracker or other HUD text.
        if with_dialog or controls or center_choice:
            areas = ['右侧选项区域']
            if controls or center_choice:
                areas.append('中间选项区域')
            for name in areas:
                # A controller-focused option is black on yellow; the white-only mask loses it.
                background = bool(getattr(self.ctx.controller, 'background_mode', False))
                choices = [record for record in self._ocr(screen, name, white=not background)
                           if str_utils.with_chinese(self._text(record))]
                if choices:
                    chosen = (max if option == '最后一个' else min)(choices, key=lambda r: r.center.y)
                    return DialogueAction('option', chosen.center, self._text(chosen))
        if with_dialog and mode != '等待剧情自动播放':
            return DialogueAction('advance', self._area('对话框内容').rect.center, '继续对话')
        return None
