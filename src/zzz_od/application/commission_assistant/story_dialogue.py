# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 上游提交: f6bed27f54f79c8833a66f0d7a1767721deb1e89
# 路径: src/zzz_od/application/commission_assistant/commission_assistant_app.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
"""有状态的剧情推进核心：只识别当前画面，由调用方把动作交给输入层执行。

识别优先级沿用上游的 跳过 -> 跳过确认 -> 剧情按钮（菜单/自动） -> 选项 -> 对话正文：
- 已确认的普通对话按配置间隔重复点击，同一句文本也继续推进；
- 点击选项后 0.5s 内优先重按已选选项，同一组选项停留超过 2s 则不再重复它；
- 跳过后点击菜单/自动只尝试一次，5s 内只等跳过按钮或确认框，随后回到正文推进，
  避免同一帧的菜单按钮不断刷新等待时间；
- 只有已确认的对话会话才允许短时间的过渡画面补点，最多 5 次，超出即结束会话。

安全边界（有意与上游不同，均以当前画面证据为前提）：
- 跳过确认只接受明确的「是否跳过…」提示，绝不确认购买、抽卡或升级弹窗；
- 战斗 HUD、玩法引导、世界/二级菜单等明确非剧情画面不产生动作；
- 涉及购买、消耗、解锁等敏感选项不自动选择；
- 跳过剧情模式不从中间的装饰性场景文字推断选项。
"""
import re
import time
from dataclasses import dataclass

import cv2

from onedragon.base.geometry.point import Point
from onedragon.base.geometry.rectangle import Rect
from onedragon.base.screen import screen_utils
from onedragon.utils import cv2_utils, str_utils
from zzz_od.operation.enter_game.game_startup import startup_word

MODE_CLICK = '自动点击'
MODE_AUTO = '等待剧情自动播放'
MODE_SKIP = '跳过剧情'
MODES = (MODE_CLICK, MODE_AUTO, MODE_SKIP)

_OPTION_FIRST = '第一个'
_OPTION_LAST = '最后一个'

# 上游兼容：只接受明确的跳过剧情确认，不把普通「确认」当剧情确认。
_SKIP_PROMPT_RE = re.compile(
    r'是否跳过(?:(?:当前|本段|这段)?(?:剧情|对话|动画)|「[^「」\r\n]+」的剧情)[？?]?')
_DOTS_RE = re.compile(r'[.．。…·・\s]+')

# 这些文本出现在正文区域时是系统标签而不是剧情正文。只做完整匹配，避免
# 正常的剧情台词因为提到「材料不足」等词被误伤。
_UI_BODY_LABELS = frozenset({
    '确认', '确定', '取消', '关闭', '返回', '跳过', '菜单', '自动',
    '材料不足', '升级', '优化', '购买', '充值', '消耗', '解锁', '拆解', '销毁',
    '兑换', '十次调频', '调频', '当前正在自动播放', '是否跳过当前对话',
})
_SENSITIVE_OPTION_WORDS = ('购买', '支付', '消耗', '充值', '解锁', '拆解', '销毁', '兑换')


@dataclass(frozen=True)
class StoryAction:
    """一次待执行的剧情输入。wait 是执行后到下一次检测的最短间隔。"""

    kind: str
    point: Point
    text: str
    wait: float = 0.5


class StoryDialogue:
    """识别剧情动作并维护跨帧节奏；本身不操作鼠标、键盘或手柄。"""

    WHITE = [[220, 220, 220], [255, 255, 255]]
    OPTION_HOLD_SEC: float = 0.5
    OPTION_STALL_SEC: float = 2.0
    SKIP_WAIT_SEC: float = 5.0
    UNKNOWN_GRACE_SEC: float = 5.0
    UNKNOWN_GRACE_ROUNDS: int = 5
    AUTO_MENU_ATTEMPTS: int = 2

    def __init__(self, ctx):
        self.ctx = ctx
        self.reset()

    def reset(self) -> None:
        """清空所有跨帧策略；取消任务或输入过期后必须调用。"""
        self._next_at: float = 0.
        self._status: str = '等待对话画面'
        self._mode: str = MODE_CLICK
        self._last_action_mode: str = MODE_CLICK

        self._pending_option_set: frozenset[str] = frozenset()
        self._chosen_option: str | None = None
        self._chosen_at: float = 0.
        self._chosen_set: frozenset[str] = frozenset()
        self._chosen_point: Point = Point(0, 0)
        self._ignored_option: str | None = None
        self._ignored_set: frozenset[str] = frozenset()

        self._menu_attempts: int = 0
        self._menu_hold_until: float = 0.
        self._menu_opened_at: float = 0.
        self._skip_wait_until: float = 0.
        self._skip_menu_used: bool = False

        self._session_active: bool = False
        self._last_dialogue_at: float = 0.
        self._unknown_rounds: int = 0
        self._option_note: str = ''
        self._auto_waiting: bool = False
        self._ocr_cache: dict = {}

    @property
    def status(self) -> str:
        """最近一次动作或等待原因，用于任务界面的简短状态。"""
        return self._status

    def detect(self, screen, *, mode: str = MODE_SKIP, option: str = _OPTION_LAST,
               click_interval: float = 0.5) -> StoryAction | None:
        """根据当前帧和自身记录返回一个动作；同一帧不会产生输入副作用。"""
        now = self._now()
        # 等待期内保留上一次的状态，避免父流程把「等待动画」清成「无对话」。
        if now < self._next_at:
            return None
        if screen is None or getattr(screen, 'shape', (None,))[:2] != (1080, 1920) \
                or getattr(self.ctx, 'ocr_service', None) is None:
            self._status = '等待游戏画面'
            return None

        self._mode = self._mode_value(mode)
        interval = self._interval(click_interval)
        # 同一帧内多个判定会请求相同 ROI，缓存一次避免重复 OCR 拖慢 0.5s 循环。
        self._ocr_cache = {}

        # 最便宜的排除先做：战斗 HUD 存在时连剧情 OCR 都不必跑。
        if self._found(screen, '战斗画面', '按键-普通攻击'):
            self._clear_session()
            self._status = '战斗画面，不处理剧情'
            return None

        # Menu labels can look like a speaker, dialogue body and choices in the same frame.
        if self._blocked_ui(screen):
            self._clear_session()
            self._status = '非剧情画面，等待剧情'
            return None

        if self._mode == MODE_SKIP:
            confirmation = self._skip_confirmation(screen, interval)
            if confirmation is not None:
                return self._publish(confirmation)

        if self._tutorial(screen):
            self._clear_session()
            self._status = '玩法引导，等待手动操作'
            return None

        controls = self._story_controls(screen)
        body_texts, speaker_present, dots = self._dialogue_text(screen)
        framed_dialogue = not controls and (
            (bool(body_texts) and not speaker_present and self._has_dialogue_frame(screen))
            or (not body_texts and speaker_present and self._has_dialogue_frame(screen)
                and (dots or self._has_visual_ellipsis(screen))))
        # The upgrade modal places its explanation and button in the speaker and body areas.
        if not controls and (speaker_present or framed_dialogue or self._session_active) and any(
                self._text(row) == '系统优化'
                for row in self._ocr_rect(screen, Rect(400, 200, 660, 275))):
            self._clear_session()
            self._status = '非剧情画面，等待剧情'
            return None
        body_dialogue = framed_dialogue or (bool(body_texts) and (bool(controls) or speaker_present))
        centered_narration = (not body_dialogue and not speaker_present
                              and self._has_centered_narration(screen, menu_expanded='跳过' in controls))
        cinematic = (not body_dialogue and not centered_narration and bool(controls)
                     and self._has_cinematic_dialogue(screen))
        has_dialogue = (body_dialogue or centered_narration or cinematic
                        or self._ellipsis_dialogue(dots, speaker_present, controls))

        if has_dialogue:
            if not self._session_active:
                # 新一段剧情：之前的菜单尝试和选项保护不再适用。
                self._menu_attempts = 0
                self._menu_hold_until = 0.
                self._menu_opened_at = 0.
                self._skip_wait_until = 0.
                self._skip_menu_used = False
            self._session_active = True
            self._last_dialogue_at = now
            self._unknown_rounds = 0

        if framed_dialogue and any(self._text(row) in ('确认', '确定', '取消')
                                    for row in self._ocr(screen, '对话框确认')):
            self._clear_session()
            self._status = '非剧情画面，等待剧情'
            return None
        if not controls and not speaker_present and body_texts and self._is_blackout_narration(screen):
            return self._publish(StoryAction(
                'advance', self._area('对话框内容').rect.center, '继续对话', interval))

        if self._mode == MODE_SKIP:
            action = self._detect_skip(screen, controls, has_dialogue, now, interval)
            if action is not None:
                return action
            if now < self._skip_wait_until:
                self._status = '等待跳过键和确认框'
                return None

        # 上游自动模式先处理中间的剧情选项；已经开启自动播放时也一样，
        # 否则选项画面会一直停在等待。
        if self._mode == MODE_AUTO and has_dialogue and not (centered_narration or cinematic):
            action = self._detect_option(screen, option, now, interval, has_dialogue)
            if action is not None:
                return action
            if self._option_note:
                self._status = self._option_note
                return None

        if self._mode == MODE_AUTO:
            action = self._detect_auto(screen, controls, has_dialogue, now, interval)
            if action is not None:
                return action
            if self._auto_waiting:
                return None
            if any(str_utils.with_chinese(text) for text in body_texts) \
                    and '自动' in controls:
                self._status = '剧情自动播放中'
                return None

        if has_dialogue:
            if self._mode != MODE_AUTO and not (centered_narration or cinematic):
                action = self._detect_option(screen, option, now, interval, has_dialogue)
                if action is not None:
                    return action
                if self._option_note:
                    self._status = self._option_note
                    return None
            return self._publish(StoryAction(
                'advance', self._area('对话框内容').rect.center, '继续对话', interval))

        if self._session_active:
            action = self._unknown_transition(screen, controls, now, interval)
            if action is not None:
                return action

        if not has_dialogue and not self._session_active:
            self._status = '等待对话画面'
        return None

    def feedback(self, action: StoryAction, completed: bool) -> None:
        """记录输入结果并从单调时钟安排下一次尝试。

        completed=False 表示没发出去或只移动了焦点，仍按动作间隔重试；
        只有 completed=True 才记录选项选择、菜单打开和跳过等待。
        """
        if action is None:
            return
        now = self._now()
        self._next_at = now + self._interval(action.wait)
        mode = self._last_action_mode

        if action.kind == 'option':
            if completed:
                same_target = self._chosen_option == action.text and self._chosen_at > 0
                new_set = bool(self._pending_option_set) \
                    and self._pending_option_set != self._chosen_set
                self._chosen_option = action.text
                if not same_target or new_set:
                    # 保护期的起点是第一次选择；同一坐标的重复按不刷新 2s 停滞计时。
                    self._chosen_at = now
                    self._chosen_set = self._pending_option_set
                self._pending_option_set = frozenset()
                self._session_active = True
                self._last_dialogue_at = now
                self._unknown_rounds = 0
                self._status = f'已选择{action.text}'
            else:
                self._status = '等待对话选项焦点'
        elif action.kind == 'advance':
            self._status = '继续对话' if completed else '等待对话推进确认'
        elif action.kind == 'skip':
            self._status = '等待跳过确认' if completed else '等待剧情按钮确认'
        elif action.kind == 'confirm_skip':
            if completed:
                self._clear_session()
                self._status = '等待跳过动画'
            else:
                self._status = '等待跳过确认焦点'
        elif action.kind in ('menu', 'auto'):
            if completed:
                self._menu_attempts += 1
                if action.kind == 'menu':
                    self._menu_opened_at = now
                    self._menu_hold_until = now + 1.
                if mode == MODE_SKIP:
                    self._skip_wait_until = now + self.SKIP_WAIT_SEC
                    self._skip_menu_used = True
                    self._chosen_option = None
                    self._chosen_at = 0.
                    self._chosen_set = frozenset()
                    self._status = '等待跳过键和确认框'
                else:
                    self._status = '等待剧情菜单' if action.kind == 'menu' else '等待自动播放'
            else:
                self._status = '等待剧情按钮确认'

    # ------------------------------------------------------------------ 识别

    def _area(self, name):
        return self.ctx.screen_loader.get_area('委托助手', name)

    def _ocr(self, screen, name, white: bool = False):
        key = ('area', name, bool(white))
        cached = self._ocr_cache.get(key)
        if cached is not None:
            return cached
        rows = self.ctx.ocr_service.get_ocr_result_list(
            image=screen, rect=self._area(name).rect,
            color_range=self.WHITE if white else None)
        rows = rows if isinstance(rows, (list, tuple)) else []
        self._ocr_cache[key] = rows
        return rows

    def _found(self, screen, screen_name: str, area_name: str) -> bool:
        return screen_utils.find_area(
            self.ctx, screen, screen_name, area_name) == screen_utils.FindAreaResultEnum.TRUE

    @staticmethod
    def _text(record) -> str:
        return str(getattr(record, 'data', '')).strip().replace(' ', '')

    def _story_controls(self, screen) -> dict:
        controls = {}
        for record in self._ocr(screen, '文本-剧情右上角', white=True):
            text = self._text(record)
            if text in ('跳过', '菜单', '自动') and text not in controls:
                controls[text] = record
        return controls

    def _dialogue_text(self, screen):
        """(本轮正文, 是否有说话人, 是否是省略号) — 旁白允许没有说话人。"""
        area = self._area('对话框内容')
        if not cv2_utils.is_in_gray_mask(screen, rect=area.rect):
            return [], False, False

        rows = self._ocr(screen, '对话框内容')
        body: list[str] = []
        dots = False
        for record in rows:
            text = self._text(record)
            if not text:
                continue
            if _DOTS_RE.fullmatch(text):
                dots = True
            if str_utils.with_chinese(text) and not startup_word(text) \
                    and text not in _UI_BODY_LABELS and not self._is_ui_confirmation(text):
                body.append(text)

        speakers = [self._text(record) for record in self._ocr(screen, '对话框标题')]
        speaker_present = any(str_utils.with_chinese(name) and len(name) <= 20
                              and name not in _UI_BODY_LABELS for name in speakers)
        return body, speaker_present, dots

    @staticmethod
    def _ellipsis_dialogue(dots: bool, speaker_present: bool, controls: dict) -> bool:
        # Without a verified frame, dots or a speaker alone still need visible story controls.
        if not controls:
            return False
        return dots or speaker_present

    @staticmethod
    def _is_ui_confirmation(text: str) -> bool:
        return (len(text) <= 24 and bool(re.match(r'^(是否|确认|确定)', text))
                and any(word in text for word in _SENSITIVE_OPTION_WORDS))

    def _tutorial(self, screen) -> bool:
        return any(self._text(record) in ('玩法引导', '战斗引导')
                   for record in self._ocr(screen, '玩法引导'))

    def _blocked_ui(self, screen) -> bool:
        return any(self._found(screen, screen_name, area_name) for screen_name, area_name in (
            ('委托助手', '左上角返回'),
            ('大世界-普通', '按钮-菜单'),
            ('大世界-勘域', '勘域-菜单'),
            ('委托助手', '战斗-菜单'),
            ('委托助手', '标题-短信'),
            ('打开游戏', '点击进入游戏'),
        ))

    def _ocr_rect(self, screen, rect: Rect):
        key = ('rect', rect.x1, rect.y1, rect.x2, rect.y2)
        cached = self._ocr_cache.get(key)
        if cached is not None:
            return cached
        rows = self.ctx.ocr_service.get_ocr_result_list(image=screen, rect=rect)
        rows = rows if isinstance(rows, (list, tuple)) else []
        self._ocr_cache[key] = rows
        return rows

    def _skip_confirmation(self, screen, interval: float) -> StoryAction | None:
        """只有明确的跳过提示和确认按钮同帧出现时才返回确认动作。"""
        # 先读小按钮区域；普通剧情帧不会为跳过提示整块 OCR 中央区域。
        confirm = next((record for record in self._ocr(screen, '对话框确认')
                        if self._text(record) == '确认'), None)
        if confirm is None:
            return None
        prompt = self._ocr_rect(screen, Rect(600, 300, 1320, 780))
        if not any(_SKIP_PROMPT_RE.fullmatch(self._text(record)) for record in prompt):
            return None
        return StoryAction('confirm_skip', confirm.center, '确认跳过剧情', interval)

    # ------------------------------------------------------------ 模式分支

    def _detect_skip(self, screen, controls: dict, has_dialogue: bool,
                     now: float, interval: float) -> StoryAction | None:
        # 跳过按钮优先；无台词的过场必须同时有剧情控件，不能只凭一个「跳过」标签。
        if '跳过' in controls and (has_dialogue or '菜单' in controls or '自动' in controls):
            return self._publish(StoryAction('skip', controls['跳过'].center,
                                             '跳过剧情', interval))

        # 上游主线分支：跳过不可用时优先菜单，其次自动。
        if has_dialogue and not self._skip_menu_used and now >= self._skip_wait_until:
            label = '菜单' if '菜单' in controls else ('自动' if '自动' in controls else None)
            if label is not None:
                record = controls[label]
                kind = 'menu' if label == '菜单' else 'auto'
                return self._publish(StoryAction(
                    kind, record.center, '展开剧情菜单' if kind == 'menu' else '开启自动播放',
                    interval))
        return None

    def _detect_auto(self, screen, controls: dict, has_dialogue: bool,
                     now: float, interval: float) -> StoryAction | None:
        self._auto_waiting = False
        # 已经显示「自动」：上游在这里只等待，不重复切换按钮。
        if '自动' in controls:
            self._auto_waiting = True
            self._status = '剧情自动播放中'
            return None

        auto_button = None
        for record in self._ocr(screen, '按钮-自动', white=True):
            if self._text(record) == '自动':
                auto_button = record
                break

        menu_context = has_dialogue or bool(self._menu_opened_at
                                            and now - self._menu_opened_at <= self.SKIP_WAIT_SEC)
        # 菜单已经打开时优先点「自动」按钮，不重复点右上角的「菜单」。
        if auto_button is not None and menu_context and (
                self._menu_opened_at > 0 or '菜单' not in controls):
            return self._publish(StoryAction('auto', auto_button.center,
                                             '开启自动播放', interval))

        if has_dialogue and '菜单' in controls \
                and self._menu_attempts < self.AUTO_MENU_ATTEMPTS \
                and now >= self._menu_hold_until:
            return self._publish(StoryAction('menu', controls['菜单'].center,
                                             '展开剧情菜单', interval))

        if self._menu_opened_at > 0 and now < self._menu_hold_until:
            self._auto_waiting = True
            self._status = '等待剧情菜单'
            return None
        return None

    # ---------------------------------------------------------------- 选项

    def _detect_option(self, screen, option: str, now: float, interval: float,
                       has_dialogue: bool) -> StoryAction | None:
        self._option_note = ''
        rows, area_center_x = self._option_rows(screen)
        option_set = frozenset(self._text(record) for record in rows)
        ignored: str | None = None

        if self._ignored_option is not None:
            if not option_set:
                self._ignored_option = None
                self._ignored_set = frozenset()
            elif option_set != self._ignored_set:
                self._ignored_option = None
                self._ignored_set = frozenset()
            else:
                ignored = self._ignored_option

        if self._chosen_option is not None:
            # 同一组选项超过 2s 仍是同一个目标，说明按钮没被游戏接受；换下一个。
            same_set = bool(option_set) and option_set == self._chosen_set
            if same_set and now - self._chosen_at > self.OPTION_STALL_SEC + interval:
                ignored = self._chosen_option
                self._ignored_option = self._chosen_option
                self._ignored_set = self._chosen_set
                self._chosen_option = None
                self._chosen_at = 0.
                self._chosen_set = frozenset()
            elif now - self._chosen_at <= self.OPTION_HOLD_SEC and has_dialogue:
                # 首击可能被动画吞掉；保护期内即使 OCR 暂时丢了按钮也重按原目标。
                if not option_set or self._chosen_option in option_set:
                    point = self._chosen_point if not rows else self._find_point(
                        rows, self._chosen_option, area_center_x) or self._chosen_point
                    self._pending_option_set = option_set or self._chosen_set
                    return self._publish(StoryAction('option', point,
                                                     self._chosen_option, interval))
            elif self._chosen_option not in option_set:
                self._chosen_option = None
                self._chosen_at = 0.
                self._chosen_set = frozenset()

        if not rows:
            return None

        candidates = [record for record in rows if self._text(record) != ignored]
        if not candidates:
            self._option_note = '剧情选项未变化，等待画面'
            return None
        target = (max if option == _OPTION_LAST else min)(candidates, key=lambda r: r.center.y)
        target_text = self._text(target)
        if not target_text:
            return None
        if any(word in target_text for word in _SENSITIVE_OPTION_WORDS):
            self._option_note = '对话选项需人工确认'
            return None

        target_point = self._option_point(target, area_center_x)
        self._pending_option_set = option_set
        self._chosen_point = target_point
        return self._publish(StoryAction('option', target_point, target_text, interval))

    def _option_rows(self, screen):
        """优先右侧选项；中间区域只在点击/自动模式且有剧情正文时识别。"""
        rows = self._option_rows_in(screen, '右侧选项区域')
        if rows:
            return rows, None

        if self._mode == MODE_SKIP:
            # 跳过模式不读中间区域，避免把场景装饰文字当成选项后一直等焦点。
            return [], None
        if self._mode == MODE_AUTO:
            y = self._central_template_y(screen)
            if y is None:
                return [], None
            rows = self._option_rows_in(screen, '中间选项区域')
            rows = [record for record in rows if abs(record.center.y - y) <= 60]
            return rows, 960  # 上游 center_x=True 点击画面中心，而不是模板区域中心。
        rows = self._option_rows_in(screen, '中间选项区域')
        # 中间区域只有至少两个中文选项时才采用，单个装饰文字/任务追踪不当作选择。
        return (rows, 960) if len(rows) >= 2 else ([], None)

    def _option_rows_in(self, screen, area_name: str):
        # 当前画面可能仍是手柄提示；完整 OCR 同时保留白字和黄色焦点上的黑字。
        # 与上游一致不限长度：「是」「否」等单字选项也必须能选。
        return [record for record in self._ocr(screen, area_name)
                if str_utils.with_chinese(self._text(record))]

    def _central_template_y(self, screen) -> int | None:
        area = self._area('中间选项区域')
        if getattr(self.ctx, 'tm', None) is None or not getattr(area, 'template_id', None):
            return None
        match = screen_utils.find_template_coord_in_area(
            self.ctx, screen, '委托助手', '中间选项区域')
        return None if match is None else match.center.y

    def _find_point(self, rows, text: str, area_center_x: int | None):
        for record in rows:
            if self._text(record) == text:
                return self._option_point(record, area_center_x)
        return None

    @staticmethod
    def _option_point(record, area_center_x: int | None) -> Point:
        if area_center_x is None:
            return record.center
        return Point(area_center_x, record.center.y)

    # ------------------------------------------------------------ 过渡补点

    def _unknown_transition(self, screen, controls: dict, now: float,
                            interval: float) -> StoryAction | None:
        if now - self._last_dialogue_at > self.UNKNOWN_GRACE_SEC \
                or self._unknown_rounds >= self.UNKNOWN_GRACE_ROUNDS:
            self._clear_session()
            self._status = '等待对话画面'
            return None
        if not controls and not self._black_scene(screen):
            # 对话结束后的彩色世界/奖励画面不补点。
            self._status = '等待对话画面'
            return None
        self._unknown_rounds += 1
        return self._publish(StoryAction(
            'advance', self._area('对话框内容').rect.center,
            '继续对话', interval))

    @staticmethod
    def _has_dialogue_frame(screen) -> bool:
        # A dark text area or horizontal separator alone isn't a dialogue box. Check the
        # top and both side borders of the textbox in the normalized 1920×1080 frame.
        for edge in (screen[828:831, 460:1460:8, :3], screen[856:978:4, 400:403, :3],
                     screen[856:978:4, 1518:1521, :3]):
            low, high = edge.min(axis=-1), edge.max(axis=-1)
            if ((low >= 25) & (high <= 58) & (high - low <= 8)).mean() < .85:
                return False
        return True

    def _has_visual_ellipsis(self, screen) -> bool:
        # OCR can miss punctuation-only lines. Require one row of equally spaced white dots,
        # not merely bright pixels or a speaker over an empty box.
        rect = self._area('对话框内容').rect
        body = screen[rect.y1:rect.y2, rect.x1:rect.x2, :3]
        mask = cv2.inRange(body, (200, 200, 200), (255, 255, 255))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        dots = sorted(box for contour in contours
                      if (box := cv2.boundingRect(contour))[2] * box[3] >= 4)
        if len(dots) not in (3, 6):
            return False
        y0, h0 = dots[0][1], dots[0][3]
        if not all(3 <= w <= 10 and 3 <= h <= 10 and abs(w - h) <= 3
                   and abs(2 * (y - y0) + h - h0) <= 4 for _, y, w, h in dots):
            return False
        gaps = [right[0] - left[0] for left, right in zip(dots, dots[1:])]
        smallest, largest = min(gaps), max(gaps)
        return 5 <= smallest <= largest <= 18 and largest - smallest <= 4

    def _is_blackout_narration(self, screen) -> bool:
        # A black scene with only subtitles is distinct from an ordinary gray textbox.
        above_subtitle = screen[:self._area('对话框标题').rect.y1:16, ::16, :3]
        return ((above_subtitle.max(axis=-1) <= 20).mean() >= .99
                and not any(self._text(row) in ('确认', '确定', '取消')
                            for row in self._ocr(screen, '对话框确认')))

    def _has_centered_narration(self, screen, *, menu_expanded: bool) -> bool:
        # Expanded story controls extend down the right edge, outside the subtitle band.
        top_right = 1600 if menu_expanded else 1820
        for part in (screen[160:415:8, 100:top_right:8], screen[615:1000:8, 100:1820:8],
                     screen[415:615:8, 100:418:8], screen[415:615:8, 1500:1820:8]):
            if (part.max(axis=-1) > 20).mean() > .01:
                return False
        rows = self._ocr_rect(screen, Rect(418, 415, 1500, 615))
        texts = [self._text(row) for row in rows if self._text(row)]
        return (bool(texts)
                and all(str_utils.with_chinese(text) and text not in _UI_BODY_LABELS
                        and not startup_word(text) and not self._is_ui_confirmation(text)
                        for text in texts)
                and not any(self._text(row) in ('确认', '确定', '取消')
                            for row in self._ocr(screen, '对话框确认')))

    def _has_cinematic_dialogue(self, screen) -> bool:
        # Letterboxed scenes render dialogue within the artwork, not over the bottom dialogue mask.
        for band in (screen[40:115:8, 240:1580:8], screen[980:1040:8, 240:1580:8]):
            if (band.max(axis=-1) > 20).mean() > .01:
                return False
        rows = self._ocr_rect(screen, Rect(418, 155, 1500, 930))
        texts = [text for row in rows if (text := self._text(row))]
        return (any(str_utils.with_chinese(text) and text not in _UI_BODY_LABELS
                    and not startup_word(text) for text in texts)
                and not any(self._is_ui_confirmation(text) or text in ('确认', '确定', '取消')
                            for text in texts))

    def _black_scene(self, screen) -> bool:
        part = cv2_utils.crop_image_only(screen, self._area('中间选项区域').rect)
        return part is not None and not cv2_utils.is_colorful(
            part, saturation_threshold=1, color_ratio_threshold=0.01)

    # ------------------------------------------------------------- 内部

    def _publish(self, action: StoryAction) -> StoryAction:
        self._last_action_mode = self._mode
        self._status = {
            'advance': '继续对话',
            'option': f'选择{action.text}',
            'skip': '跳过剧情',
            'confirm_skip': '确认跳过剧情',
            'menu': '展开剧情菜单',
            'auto': '开启自动播放',
        }.get(action.kind, action.text)
        return action

    def _clear_session(self) -> None:
        self._session_active = False
        self._last_dialogue_at = 0.
        self._unknown_rounds = 0
        self._menu_attempts = 0
        self._menu_hold_until = 0.
        self._menu_opened_at = 0.
        self._skip_wait_until = 0.
        self._skip_menu_used = False
        self._chosen_option = None
        self._chosen_at = 0.
        self._chosen_set = frozenset()
        self._ignored_option = None
        self._ignored_set = frozenset()
        self._pending_option_set = frozenset()
        self._option_note = ''
        self._auto_waiting = False

    @staticmethod
    def _interval(value: float) -> float:
        try:
            result = float(value)
        except (TypeError, ValueError):
            result = 0.5
        return min(5., max(0.05, result))

    @staticmethod
    def _mode_value(mode) -> str:
        """接受原始 StoryMode 枚举或它保存的字符串，其他值按自动点击处理。"""
        value = mode
        if hasattr(value, 'value'):
            value = value.value
        if hasattr(value, 'value'):
            value = value.value
        return value if value in MODES else MODE_CLICK

    @staticmethod
    def _now() -> float:
        return time.monotonic()
