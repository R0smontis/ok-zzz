# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/application/hollow_zero/lost_void/operation/interact/lost_void_choose_gear.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
import re
import time
from typing import Any, ClassVar

import cv2
from cv2.typing import MatLike

from onedragon.base.geometry.point import Point
from onedragon.base.geometry.rectangle import Rect
from onedragon.base.matcher.match_result import MatchResultList
from onedragon.base.operation.operation_edge import node_from
from onedragon.base.operation.operation_node import operation_node
from onedragon.base.operation.operation_round_result import OperationRoundResult
from onedragon.utils import cv2_utils, str_utils
from onedragon.utils.log_utils import log
from zzz_od.application.hollow_zero.lost_void.context.lost_void_artifact import (
    LostVoidArtifact,
)
from zzz_od.application.hollow_zero.lost_void.operation.interact.lost_void_artifact_pos import (
    LostVoidArtifactPos,
)
from zzz_od.context.zzz_context import ZContext
from zzz_od.operation.zzz_operation import ZOperation
from zzz_od.application.hollow_zero.lost_void.mission_screen import focused_gear
from src.controls.gamepad import press as pad


def normalize_gear_name(text):
    value=re.sub(r'\s+','',text).replace('【','[').replace('】',']')
    # The equipped header uses a different font than the preview. Preserve
    # exact identity while correcting the variants observed in that header.
    value=value.replace('攜游','携游').replace('携遊','携游')
    return value.replace('[携游]救令玄幡','[携游]敕令玄幡')


class LostVoidChooseGear(ZOperation):

    STATUS_REPEATED: ClassVar[str] = '重复武备选择'

    def __init__(self, ctx: ZContext, completed_name_list: list[str] | None = None):
        """
        入口处 人物武备和通用武备的选择
        :param ctx:
        :param completed_name_list: 入口层已完成选择画面的首个武备名列表 跨交互共享
            传入时 若当前画面首个武备命中列表 说明重复交互了同一个NPC 直接返回退出 不再重复整套选择
            完成一次选择后 本画面的首个武备名会补充进列表
            判断信号与存储信号对称(都是画面最左侧槽位的武备名) 避免与其他画面的非首个武备误匹配
        """
        ZOperation.__init__(self, ctx, op_name='迷失之地-武备选择')
        self._pad_scan = None
        self._equip_requests = 0
        self._unlock_requests = 0
        self._equip_confirmed = False
        self.completed_name_list: list[str] | None = completed_name_list
        # 本次画面最左侧槽位的武备名 携带成功后写入 completed_name_list
        # 最左侧槽位OCR解析失败时为None 本画面不记录(宁可下次重复识别 也不存错位的名字)
        self.first_slot_gear_name: str | None = None

    @operation_node(name='选择武备', is_start_node=True, timeout_seconds=90)
    def choose_gear(self) -> OperationRoundResult:
        if getattr(self.ctx.controller, 'background_mode', False):
            return self._choose_gear_with_pad()
        area = self.ctx.screen_loader.get_area('迷失之地-通用选择', '文本-详情')
        self.ctx.controller.mouse_move(area.center + Point(0, 100))
        time.sleep(0.1)

        screen_name = self.check_and_update_current_screen(self.last_screenshot)
        if screen_name != '迷失之地-武备选择':
            # 进入本指令之前 有可能识别错画面
            return self.round_retry(status=f'当前画面 {screen_name}', wait=1)

        # 入口层只有两个武备NPC 两个都完成过还进武备画面 必为重复 直接退出
        # 省掉判重的点击首格+OCR(约10秒) 去门途中被NPC抢交互时的自愈更快
        if self.completed_name_list is not None and len(self.completed_name_list) >= 2:
            log.info('入口层两个武备均已完成 当前武备画面必为重复 直接返回')
            return self.round_success(LostVoidChooseGear.STATUS_REPEATED)

        choose_new: bool = False
        gear_contours, gear_context = self._find_gears_with_status()
        if not gear_contours:
            return self.round_retry(status='无法识别武备槽位')

        # 入口层可能因为交互判定(角度>距离)命中了刚选完武备的NPC 重复打开同一个画面
        # 此时只看首个武备名称 命中已完成列表(各画面首个武备名)则直接退出 避免重复整套点击识别
        # cutoff=0.8 只容忍同名的OCR错字 不同画面即使名称相近也不会误判为重复
        if self.completed_name_list is not None and len(self.completed_name_list) > 0:
            first_name = self._get_first_gear_name(gear_context)
            if (first_name is not None
                    and str_utils.find_best_match_by_difflib(first_name, self.completed_name_list, cutoff=0.8) is not None):
                log.info(f'重复进入已完成选择的武备画面 直接返回 首个武备={first_name}')
                return self.round_success(LostVoidChooseGear.STATUS_REPEATED)

        gear_list, has_level_list = self.get_gear_pos_by_click_ocr(gear_contours, gear_context)
        if len(gear_list) == 0:
            return self.round_retry(status='无法识别武备名称')

        if self.ctx.lost_void.challenge_config.chase_new_mode:
            unlocked_gears: list[LostVoidArtifactPos] = [
                gear_list[i]
                for i in range(min(len(gear_list), len(has_level_list)))
                if not has_level_list[i]
            ]
            if unlocked_gears:
                priority_new = self.ctx.lost_void.get_artifact_by_priority(unlocked_gears, 1)
                target = priority_new[0] if len(priority_new) > 0 else unlocked_gears[0]
                self.ctx.controller.click(target.rect.center)
                time.sleep(0.5)

                # 将选择的武备类型鸣徽添加至第一优先级
                text = target.artifact.category
                if text not in self.ctx.lost_void.challenge_config.artifact_priority_in_battle:
                    self.ctx.lost_void.challenge_config.artifact_priority_in_battle.append(text)
                log.info('【武备追新】添加开局选择的武备属性至第一优先级: [' + text + ']')

                choose_new = True
                log.info(f'【武备追新】当前可选未获取武备 {",".join([i.artifact.display_name for i in unlocked_gears])}')
            else:
                log.info('【武备追新】所有武备都已获取，回退至优先级')

        if not choose_new:
            priority_list: list[LostVoidArtifactPos] = self.ctx.lost_void.get_artifact_by_priority(gear_list, 1)
            target = priority_list[0] if len(priority_list) > 0 else gear_list[0]
            self.ctx.controller.click(target.rect.center)
            time.sleep(0.5)

        return self.round_success(wait=0.5)

    def _pad(self, action):
        pad(self.ctx, {'left': 'dpad_left', 'right': 'dpad_right', 'confirm': 'a',
                       'back': 'b', 'unlock': 'y'}[action])

    def _repeated_screen(self, first_name) -> bool:
        """本画面最左侧武备命中入口层已完成列表：重复交互了同一个NPC。"""
        return bool(first_name is not None and self.completed_name_list
                    and str_utils.find_best_match_by_difflib(first_name, self.completed_name_list, cutoff=0.8) is not None)

    def _choose_gear_with_pad(self):
        if self._pad_scan is None:
            if self.completed_name_list is not None and len(self.completed_name_list) >= 2:
                log.info('入口层两个武备均已完成 当前武备画面必为重复 直接返回')
                return self.round_success(LostVoidChooseGear.STATUS_REPEATED)
            contours, context=self._find_gears_with_status()
            pairs=self._gear_rect_pairs(context) if contours else []
            statuses=sorted(contours,key=lambda item:cv2.boundingRect(item[0])[0])
            if not pairs:
                return self.round_retry('无法识别武备槽位，未操作',wait=.5)
            self._pad_scan={'slots':[Rect(*pair[1]) for pair in pairs], 'levels':[s[1] for s in statuses],
                            'index':0,'gears':[],'availability':[], 'target':None,'phase':'scan'}
        state=self._pad_scan
        focus=focused_gear(self.last_screenshot)
        if focus is None:
            self._pad('right')
            return self.round_wait('等待武备手柄焦点',wait=.4)
        target=state['target'] if state['phase']=='select' else state['slots'][state['index']]
        # 只通过当前帧焦点定位，不用后台点击枚举得到虚假的同名武备。
        if abs(focus.center.x-target.center.x) > max(30,target.width*.35):
            self._pad('right' if focus.center.x < target.center.x else 'left')
            return self.round_wait('手柄定位武备槽位',wait=.4)
        if state['phase']=='select':
            return self.round_success('已核验目标武备焦点',wait=.3)
        area=self.ctx.screen_loader.get_area('迷失之地-武备选择','武备名称')
        matches=self.ctx.ocr_service.get_ocr_result_list(image=self.last_screenshot,rect=area.rect)
        text=''.join(m.data for m in sorted(matches,key=lambda m:m.center.x))
        art,primary=self._build_artifact_from_ocr_name(text)
        if art is None:
            return self.round_retry('当前武备名称未识别，未确认携带',wait=.5)
        idx=state['index']
        if idx == 0:
            self.first_slot_gear_name = art.display_name
            if self._repeated_screen(art.display_name):
                log.info(f'重复进入已完成选择的武备画面 直接返回 首个武备={art.display_name}')
                return self.round_success(LostVoidChooseGear.STATUS_REPEATED)
        state['gears'].append(LostVoidArtifactPos(art=art,rect=target,ocr_text=text,is_primary_name=primary))
        availability = self._gear_availability(focus, art.display_name)
        if availability is None:
            state['gears'].pop()
            return self.round_retry('武备携带状态未识别，等待稳定画面', wait=.5)
        state['availability'].append(availability)
        log.info('手柄逐帧识别武备 %d/%d：%s',idx+1,len(state['slots']),art.display_name)
        if not availability['usable']:
            log.info('跳过不可携带武备 %s：解锁需要=%s，当前资源=%s',
                     art.display_name, availability.get('cost'), availability.get('balance'))
        state['index']+=1
        if state['index'] < len(state['slots']):
            return self.round_wait('识别下一个武备',wait=.1)
        return self._select_usable_gear()

    def _select_usable_gear(self):
        state = self._pad_scan
        gears = [g for i, g in enumerate(state['gears']) if state['availability'][i]['usable']]
        if not gears:
            return self.round_fail('当前没有可携带或可解锁的武备')
        new_gears = [g for i, g in enumerate(state['gears'])
                     if state['availability'][i]['usable'] and not state['levels'][i]]
        choices = new_gears if self.ctx.lost_void.challenge_config.chase_new_mode and new_gears else gears
        priorities=self.ctx.lost_void.get_artifact_by_priority(choices,1)
        chosen=priorities[0] if priorities else choices[0]
        state.update(phase='select',target=chosen.rect,chosen=chosen)
        return self.round_wait(f'准备携带 {chosen.artifact.display_name}',wait=.1)

    def _gear_button_enabled(self, rect):
        # OCR can read the grey disabled label, so text presence alone is insufficient.
        crop = cv2_utils.crop_image_only(self.last_screenshot, rect)
        if crop is None or crop.size == 0:
            return False
        pixels = crop.astype('int16')
        white = (pixels.min(axis=2) >= 150) & (pixels.max(axis=2)-pixels.min(axis=2) <= 70)
        return int(white.sum()) >= 80

    def _gear_number(self, rect):
        matches = self.ctx.ocr_service.get_ocr_result_list(image=self.last_screenshot, rect=rect)
        numbers = [int(text) for m in matches
                   if re.fullmatch(r'\d+', text := re.sub(r'\s+', '', str(m.data)))]
        return numbers[0] if len(numbers) == 1 else None

    def _gear_availability(self, focus, expected_name=None):
        if self._gear_button_enabled(Rect(1780, 849, 1870, 894)):
            return {'usable': True, 'unlock': False}
        matches = self.ctx.ocr_service.get_ocr_result_list(
            image=self.last_screenshot, rect=Rect(1732, 755, 1912, 825))
        if not any('解锁' in str(m.data) for m in matches):
            # The equipped item also has a grey A button. It remains a valid
            # candidate, verified by its actual equipped title rather than by input.
            if expected_name is not None:
                top = self.ctx.ocr_service.get_ocr_result_list(
                    image=self.last_screenshot, rect=Rect(730, 340, 1200, 410))
                text = ''.join(m.data for m in sorted(top, key=lambda m:m.center.x))
                if normalize_gear_name(text) == normalize_gear_name(expected_name):
                    return {'usable': True, 'unlock': False, 'equipped': True}
            return None
        balance = self._gear_number(Rect(1630, 20, 1795, 85))
        cost = self._gear_number(Rect(max(190, focus.center.x-70), 1020,
                                      min(1740, focus.center.x+75), 1075))
        return {'usable': balance is not None and cost is not None and cost <= balance,
                'unlock': True, 'balance': balance, 'cost': cost}

    def _find_gears_with_status(self) -> tuple[list[tuple[Any, bool]], Any]:
        """
        使用CV流水线查找武备及其状态
        :return: (武备轮廓, 是否有等级)
        """

        # 经常截错图，等1秒
        time.sleep(1)
        gear_context = self.ctx.cv_service.run_pipeline('迷失之地-武备列表检测', self.last_screenshot)
        level_context = self.ctx.cv_service.run_pipeline('迷失之地-武备等级检测', self.last_screenshot)

        if not gear_context.is_success or not gear_context.contours:
            return [], gear_context

        # 1. 预处理：获取所有武备框和等级框的绝对坐标
        gear_rects = self._gear_rect_pairs(gear_context)
        # 按x1坐标排序武备框
        gear_rects.sort(key=lambda item: item[1][0])  # item[1][0] 是 x1 坐标

        level_rects = []  # [(轮廓, 绝对矩形坐标)]
        if level_context.is_success and level_context.contours:
            level_rects = level_context.get_absolute_rect_pairs()
            # 按x1坐标排序等级框
            level_rects.sort(key=lambda item: item[1][0])  # item[1][0] 是 x1 坐标

        # 按x1坐标排序等级框
        if level_rects:
            level_rects.sort(key=lambda item: item[1][0])  # item[1][0] 是 x1 坐标

        # 2. 生成用于显示的框
        # debug_rects = []
        # 添加所有矩形框
        # for _, (x1, y1, x2, y2) in gear_rects:
        #     debug_rects.append(Rect(x1, y1, x2, y2))
        # for _, (x1, y1, x2, y2) in level_rects:
        #     debug_rects.append(Rect(x1, y1, x2, y2))

        # 3. 匹配武备和等级
        gear_with_status = []
        remaining_levels = list(level_rects)  # 创建一个副本用于迭代和删除

        for i, (gear_contour, (gear_x1, gear_y1, gear_x2, gear_y2)) in enumerate(gear_rects):
            has_level = False

            for j, (_level_contour, (level_x1, level_y1, level_x2, level_y2)) in enumerate(remaining_levels):
                is_overlapping = not (gear_x2 < level_x1 or level_x2 < gear_x1 or
                                      gear_y2 < level_y1 or level_y2 < gear_y1)

                if is_overlapping:
                    log.debug(f"  !!! 发现重叠: 武备[{i}] ({gear_x1},{gear_y1},{gear_x2},{gear_y2}) "
                              f"与 等级[{j}] ({level_x1},{level_y1},{level_x2},{level_y2}) 匹配成功 !!!")
                    has_level = True
                    remaining_levels.pop(j)  # 直接移除匹配的等级
                    break

            gear_with_status.append((gear_contour, has_level))

        # 4. 显示debug信息
        # cv2_utils.show_image(self.last_screenshot, debug_rects, wait=0)
        return gear_with_status, gear_context

    @staticmethod
    def _gear_rect_pairs(context):
        # A highlighted ring and its inner artwork can form separate external contours.
        # Keep one slot per centre so the same locked gear cannot re-enter the candidate list.
        pairs = sorted(context.get_absolute_rect_pairs(),
                       key=lambda p: (p[1][2]-p[1][0])*(p[1][3]-p[1][1]), reverse=True)
        result = []
        for pair in pairs:
            rect = Rect(*pair[1])
            # Bright artwork protruding between the round icons can pass the
            # area filter. It is not a selectable slot: navigating towards its
            # centre alternates forever between the two neighbouring gears.
            # These bounds apply to the already normalized 1080p game frame.
            if (rect.width < 70 or rect.height < 75
                    or not .55 <= rect.width / rect.height <= 1.8):
                continue
            if any(abs(rect.center.x-Rect(*other[1]).center.x) < 45
                   and abs(rect.center.y-Rect(*other[1]).center.y) < 45 for other in result):
                continue
            result.append(pair)
        return sorted(result, key=lambda item: item[1][0])
    def _get_first_gear_name(self, gear_context: Any) -> str | None:
        """
        点击最左侧的武备 读取其名称 用于入口重复画面的快速判断
        :param gear_context: 武备列表检测的CV流水线结果
        :return: 武备展示名 无法识别时返回None
        """
        gear_abs_pairs = gear_context.get_absolute_rect_pairs()
        if len(gear_abs_pairs) == 0:
            return None
        gear_abs_pairs.sort(key=lambda item: item[1][0])
        x1, y1, x2, y2 = gear_abs_pairs[0][1]
        self.ctx.controller.click(Point((x1 + x2) // 2, (y1 + y2) // 2))
        time.sleep(1)
        _, current_screen = self.ctx.controller.screenshot()

        name_area = self.ctx.screen_loader.get_area('迷失之地-武备选择', '武备名称')
        name_part = cv2_utils.crop_image_only(current_screen, name_area.rect)
        ocr_map = self.ctx.ocr_service.get_ocr_result_map(
            image=name_part,
            crop_first=False,
        )

        token_list: list[tuple[int, str]] = []
        for text, mrl in ocr_map.items():
            token = text.strip()
            if len(token) == 0:
                continue
            for mr in mrl:
                token_list.append((mr.center.x, token))
        token_list.sort(key=lambda item: item[0])
        ocr_text = ''.join([i[1] for i in token_list]).strip()

        art, _ = self._build_artifact_from_ocr_name(ocr_text)
        if art is None:
            return None
        return art.display_name

    def get_gear_pos_by_click_ocr(
            self,
            gear_with_status: list[tuple[Any, bool]],
            gear_context: Any,
    ) -> tuple[list[LostVoidArtifactPos], list[bool]]:
        """
        逐个点击武备，等待1秒截图，裁剪“武备名称”区域，按实际数量纵向拼图后统一OCR。
        按从上到下的OCR结果回填到从左到右的武备槽位。
        """
        if len(gear_with_status) == 0:
            return [], []

        name_area = self.ctx.screen_loader.get_area('迷失之地-武备选择', '武备名称')
        gear_abs_pairs = self._gear_rect_pairs(gear_context)
        gear_abs_pairs.sort(key=lambda item: item[1][0])
        sorted_status_list = sorted(gear_with_status, key=lambda item: cv2.boundingRect(item[0])[0])

        slice_list: list[MatLike] = []
        click_rect_list: list[Rect] = []
        has_level_list: list[bool] = []

        for i, (_, (x1, y1, x2, y2)) in enumerate(gear_abs_pairs):
            click_pos = Point((x1 + x2) // 2, (y1 + y2) // 2)
            self.ctx.controller.click(click_pos)
            time.sleep(1)
            _, current_screen = self.ctx.controller.screenshot()
            slice_list.append(cv2_utils.crop_image_only(current_screen, name_area.rect))
            click_rect_list.append(Rect(x1, y1, x2, y2))

            if i < len(sorted_status_list):
                has_level_list.append(sorted_status_list[i][1])
            else:
                has_level_list.append(True)

        if len(slice_list) == 0:
            return [], []

        stitched = cv2.vconcat(slice_list)
        ocr_map = self.ctx.ocr_service.get_ocr_result_map(
            image=stitched,
            crop_first=False,
        )
        name_list = self._extract_names_from_stitched_ocr(ocr_map, len(slice_list), slice_list[0].shape[0])
        self._update_first_slot_gear_name(name_list)

        result_list: list[LostVoidArtifactPos] = []
        total_cnt = min(len(click_rect_list), len(name_list))
        for i in range(total_cnt):
            ocr_text = name_list[i]
            if len(ocr_text) == 0:
                continue

            art, is_primary = self._build_artifact_from_ocr_name(ocr_text)
            if art is None:
                continue

            result_list.append(
                LostVoidArtifactPos(
                    art=art,
                    rect=click_rect_list[i],
                    ocr_text=ocr_text,
                    is_primary_name=is_primary,
                )
            )

        display_text = ','.join([i.artifact.display_name for i in result_list]) if len(result_list) > 0 else '无'
        log.info(f'当前识别武备 {display_text}')
        return result_list, has_level_list

    def _update_first_slot_gear_name(self, name_list: list[str]) -> None:
        """
        从各槽位的OCR文本更新最左侧槽位的武备名 解析失败时为None

        与入口重复判断(_get_first_gear_name 点击最左格)读取的槽位保持一致
        不能用识别结果列表的首元素代替: 结果列表会跳过解析失败的槽位 首元素不一定是最左格
        :param name_list: 按槽位从左到右的OCR文本列表
        """
        self.first_slot_gear_name = None
        if len(name_list) > 0 and len(name_list[0]) > 0:
            first_art, _ = self._build_artifact_from_ocr_name(name_list[0])
            if first_art is not None:
                self.first_slot_gear_name = first_art.display_name

    def _extract_names_from_stitched_ocr(
            self,
            ocr_map: dict[str, MatchResultList],
            slot_cnt: int,
            slot_height: int,
    ) -> list[str]:
        slot_tokens: list[list[tuple[int, str]]] = [[] for _ in range(slot_cnt)]
        for text, mrl in ocr_map.items():
            token = text.strip()
            if len(token) == 0:
                continue
            for mr in mrl:
                slot_idx = mr.center.y // slot_height
                if slot_idx < 0 or slot_idx >= slot_cnt:
                    continue
                slot_tokens[slot_idx].append((mr.center.x, token))

        name_list: list[str] = []
        for token_list in slot_tokens:
            token_list.sort(key=lambda item: item[0])
            text = ''.join([i[1] for i in token_list]).strip()
            name_list.append(text)
        return name_list

    def _build_artifact_from_ocr_name(self, ocr_text: str) -> tuple[LostVoidArtifact | None, bool]:
        normalized = normalize_gear_name(ocr_text)
        if len(normalized) == 0:
            return None, False

        match = re.search(r'\[(.+?)\](.+)$', normalized)
        if match is not None:
            raw_category = match.group(1).strip()
            raw_name = match.group(2).strip()
            if len(raw_name) == 0:
                return None, False
            # OCR 常见识别错误修复
            raw_category = raw_category.replace('昇常', '异常')
            category = raw_category.split('：', 1)[0].split(':', 1)[0].strip()
            if len(category) == 0:
                category = raw_category
            return LostVoidArtifact(category=category, name=raw_name, level='?', is_gear=True), True

        # 武备选择仅接受 [分类]名称 结构，其他OCR结果直接丢弃。
        return None, False

    @node_from(from_name='选择武备')
    @operation_node(name='点击携带', timeout_seconds=15)
    def click_equip(self) -> OperationRoundResult:
        if getattr(self.ctx.controller,'background_mode',False):
            target=self._pad_scan['chosen']
            normalize=normalize_gear_name
            matches=self.ctx.ocr_service.get_ocr_result_list(image=self.last_screenshot,rect=Rect(730,340,1200,410))
            text=''.join(m.data for m in sorted(matches,key=lambda m:m.center.x))
            artifact = getattr(target, 'artifact', None)
            # The preview ROI also includes "等级1:". Compare the parsed name,
            # not all preview OCR tokens, against the equipped slot title.
            expected = normalize(artifact.display_name if artifact is not None else target.ocr_text)
            parsed = re.search(r'\[[^\]]+\].+$', expected)
            if parsed is not None:
                expected = parsed.group(0)
            if normalize(text)==expected:
                self._equip_confirmed = True
                self.ctx.lost_void.priority_updated=False
                if artifact is not None:
                    priorities = self.ctx.lost_void.challenge_config.artifact_priority_in_battle
                    if artifact.category not in priorities:
                        priorities.append(artifact.category)
                log.info('武备携带已核验：%s', expected)
                self._remember_completed_screen()
                return self.round_success('已核验携带武备',wait=.3)
            focus = focused_gear(self.last_screenshot)
            if focus is None or (getattr(target, 'rect', None) is not None
                    and abs(focus.center.x-target.rect.center.x) > max(30,target.rect.width*.35)):
                return self.round_retry('等待目标武备焦点，未操作', wait=.5)
            availability = self._gear_availability(focus)
            if availability is None:
                return self.round_retry('等待武备按钮状态，未操作', wait=.5)
            if not availability['usable']:
                log.warning('武备不可携带：%s，解锁需要=%s，当前资源=%s',
                            expected, availability.get('cost'), availability.get('balance'))
                return self.round_fail('目标武备资源不足，未重复确认')
            if availability['unlock']:
                if self._unlock_requests >= 2:
                    return self.round_fail('武备解锁未生效，停止重复操作')
                self._unlock_requests += 1
                log.info('手柄解锁武备：%s，需要=%s，当前资源=%s',
                         expected, availability['cost'], availability['balance'])
                self._pad('unlock')
                return self.round_wait('手柄解锁武备，等待携带按钮启用', wait=.6)
            if self._equip_requests >= 3:
                log.warning('携带武备核验失败：目标=%s，当前顶部=%s', expected, normalize(text))
                return self.round_fail('携带武备未生效，停止重复操作')
            found=self.round_by_find_area(self.last_screenshot,'迷失之地-武备选择','按钮-携带')
            if not found.is_success:
                return self.round_retry('未找到携带按钮，未操作',wait=.5)
            self._equip_requests+=1
            self._pad('confirm')
            return self.round_wait('手柄携带，等待顶部武备名称核验',wait=.6)
        result = self.round_by_find_and_click_area(screen_name='迷失之地-武备选择', area_name='按钮-携带',
                                                   success_wait=1, retry_wait=1)
        if result.is_success:
            self.ctx.lost_void.priority_updated = False
            log.info("武备选择成功，已设置优先级更新标志")
            self._remember_completed_screen()
        return result

    def _remember_completed_screen(self) -> None:
        # 只记录本画面最左侧槽位的武备名 与重复判断读取的信号一致
        # 记录其他槽位名称会让别的画面的首个武备有机会与本画面的非首个武备误匹配
        if (self.completed_name_list is not None
                and self.first_slot_gear_name is not None
                and self.first_slot_gear_name not in self.completed_name_list):
            self.completed_name_list.append(self.first_slot_gear_name)

    @node_from(from_name='选择武备', status=STATUS_REPEATED)
    @operation_node(name='重复退出')
    def exit_repeated(self) -> OperationRoundResult:
        """
        重复进入已完成选择的画面时 点击返回退出 并透传重复状态给调用方
        """
        if getattr(self.ctx.controller, 'background_mode', False):
            if self.ctx.lost_void.in_normal_world(self.last_screenshot):
                return self.round_success(LostVoidChooseGear.STATUS_REPEATED)
            self._back_requests = getattr(self, '_back_requests', 0) + 1
            if self._back_requests > 4:
                return self.round_fail('手柄退出重复武备画面未生效')
            self._pad('back')
            return self.round_wait('手柄退出重复武备画面', wait=.8)
        result = self.round_by_find_and_click_area(screen_name='迷失之地-武备选择', area_name='按钮-返回',
                                                   until_not_find_all=[('迷失之地-武备选择', '按钮-返回')],
                                                   success_wait=1, retry_wait=1)
        if result.is_success:
            return self.round_success(LostVoidChooseGear.STATUS_REPEATED)
        return result

    @node_from(from_name='选择武备', success=False)
    @node_from(from_name='点击携带')
    @operation_node(name='点击返回', timeout_seconds=15)
    def click_back(self) -> OperationRoundResult:
        if getattr(self.ctx.controller,'background_mode',False):
            if self.ctx.lost_void.in_normal_world(self.last_screenshot):
                if not self._equip_confirmed:
                    return self.round_fail('武备选择未完成，已关闭菜单')
                return self.round_success('已关闭武备菜单',wait=.3)
            popup=self.round_by_find_area(self.last_screenshot,'迷失之地-武备选择','确认')
            self._pad('confirm' if popup.is_success else 'back')
            return self.round_wait('等待武备菜单关闭',wait=.6)
        # 先尝试点击返回
        result = self.round_by_find_and_click_area(screen_name='迷失之地-武备选择', area_name='按钮-返回',
                                                 success_wait=1, retry_wait=1)
        if result.is_success:
            return result

        # 如果找不到返回按钮，说明有弹窗，先点不再提示，再点确认
        result = self.round_by_find_and_click_area(screen_name='迷失之地-武备选择', area_name='不再提示',
                                                   success_wait=0.5, retry_wait=0.5)
        if not result.is_success:
            # 找不到不再提示，可能弹窗没有出现，直接重试返回
            return self.round_retry(wait=1)

        # 点确认
        self.round_by_find_and_click_area(screen_name='迷失之地-武备选择', area_name='确认',
                                         success_wait=0.5, retry_wait=0.5)

        # 最后再点返回
        return self.round_by_find_and_click_area(screen_name='迷失之地-武备选择', area_name='按钮-返回',
                                                 success_wait=1, retry_wait=1)


def __debug():
    ctx = ZContext()
    ctx.init_by_config()
    ctx.init_ocr()
    ctx.lost_void.init_before_run()
    ctx.run_context.start_running()

    op = LostVoidChooseGear(ctx)
    op.execute()


if __name__ == '__main__':
    __debug()
