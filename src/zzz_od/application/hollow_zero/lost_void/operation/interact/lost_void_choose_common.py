# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/application/hollow_zero/lost_void/operation/interact/lost_void_choose_common.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
import re
import time

from cv2.typing import MatLike

from onedragon.base.geometry.point import Point
from onedragon.base.geometry.rectangle import Rect
from onedragon.base.matcher.match_result import MatchResult
from onedragon.base.operation.operation_node import operation_node
from onedragon.base.operation.operation_round_result import OperationRoundResult
from onedragon.base.screen import screen_utils
from onedragon.utils import cv2_utils, str_utils
from onedragon.utils.log_utils import log
from zzz_od.application.hollow_zero.lost_void.operation.interact.lost_void_artifact_pos import (
    LostVoidArtifactPos,
)
from zzz_od.context.zzz_context import ZContext
from zzz_od.operation.zzz_operation import ZOperation
from zzz_od.application.hollow_zero.lost_void.mission_screen import common_choice, focused_card, battle_result, single_event_choice, lottery_counts


class LostVoidChooseCommon(ZOperation):

    def __init__(self, ctx: ZContext):
        """
        有详情 有显示选择数量的选择
        :param ctx:
        """
        ZOperation.__init__(self, ctx, op_name='迷失之地-通用选择')

        self.to_choose_artifact: bool = False  # 需要选择普通藏品
        self.to_choose_gear: bool = False  # 需要选择武备
        self.to_choose_gear_branch: bool = False  # 需要选择武备分支
        self.to_choose_num: int = 1  # 需选数量（本轮总目标）
        self.chosen_idx_list: list[int] = []  # 已经选择过的下标
        self.fallback_click_count: int = 0  # 按钮计数缺失时，使用本轮点击次数作为兜底
        self.last_choose_target_num: int = 0  # 记录上一轮目标数量，用于重置点击计数
        self._pad_target = None
        self._pad_confirm_requests = 0
        self._pad_options = set()
        self._pad_reward_confirm = False
        self._pad_reward_page = None

    @operation_node(name='选择', is_start_node=True, timeout_seconds=90)
    def choose_artifact(self) -> OperationRoundResult:
        if getattr(self.ctx.controller, 'background_mode', False):
            return self._choose_with_pad()
        area = self.ctx.screen_loader.get_area('迷失之地-通用选择', '文本-详情')
        self.ctx.controller.mouse_move(area.center + Point(0, 100))
        time.sleep(0.1)

        art_list, chosen_list = self.get_artifact_pos(self.last_screenshot)
        if self.to_choose_num <= 0:
            self.fallback_click_count = 0
            self.last_choose_target_num = 0
        if self.to_choose_num > 0:
            if self.last_choose_target_num != self.to_choose_num:
                self.fallback_click_count = 0
                self.last_choose_target_num = self.to_choose_num
            chosen_cnt = self.get_effective_chosen_count(self.last_screenshot, chosen_list, self.to_choose_num)
            log.info(
                f'选择决策 | 概览 | 需选={self.to_choose_num} 已选={chosen_cnt} 可选={len(art_list)}'
            )
            if chosen_cnt >= self.to_choose_num:
                return self.click_confirm()

            # 四层流程：NEW -> 同流派 -> 优先级 -> 兜底
            # 每层都按“还需选择数量”补齐，补满即确认。
            if len(art_list) > 0 and self.select_by_layers(self.to_choose_num):
                return self.click_confirm()

            if len(art_list) > 0 and self.try_fill_by_answer_fallback(self.to_choose_num):
                return self.click_confirm()

            # 兜底：无条件点击可见文本块后直接确认，避免卡死。
            self.try_choose_by_click_name_text(target_num=self.to_choose_num)

            # 关键修正：多选场景必须选满后才能确认，避免“1/2就点确定”导致卡死/退出。
            _, latest_screen = self.ctx.controller.screenshot()
            _, final_chosen_list = self.get_artifact_pos(latest_screen)
            final_chosen_cnt = self.get_effective_chosen_count(latest_screen, final_chosen_list, self.to_choose_num)
            if final_chosen_cnt < self.to_choose_num:
                return self.round_retry(
                    status=f'未选满 目标={self.to_choose_num} 当前={final_chosen_cnt}',
                    wait=0.5
                )

        return self.click_confirm()

    def _choose_with_pad(self):
        screen = self.last_screenshot
        if self._pad_confirm_requests and self.ctx.lost_void.in_normal_world(screen):
            self.ctx.lost_void.priority_updated = False
            return self.round_success('已核验选卡菜单关闭')
        if self._pad_confirm_requests and battle_result(self.ctx, screen):
            self.ctx.lost_void.priority_updated = False
            return self.round_success('已核验选卡结束并进入挑战结果')
        return_screen = getattr(self, 'return_screen_name', None)
        verified_common = common_choice(self.ctx, screen)
        if self._pad_confirm_requests and return_screen and not verified_common:
            if (self.check_and_update_current_screen(screen, screen_name_list=[return_screen]) == return_screen
                    or (return_screen == '迷失之地-抽奖机' and lottery_counts(self.ctx, screen) is not None)):
                self.ctx.lost_void.priority_updated = False
                return self.round_success('已核验奖励结束并返回' + return_screen)
        next_menus = ['迷失之地-邦布商店', '迷失之地-路径迭换', '迷失之地-抽奖机', '迷失之地-武备选择']
        name = self.check_and_update_current_screen(screen, screen_name_list=['迷失之地-通用选择', *next_menus])
        if verified_common or (name is None and single_event_choice(self.ctx, screen)):
            name = '迷失之地-通用选择'
        if name != '迷失之地-通用选择':
            if self._pad_confirm_requests and name in next_menus:
                self.ctx.lost_void.priority_updated = False
                return self.round_success('已核验选卡结束并进入' + name)
            return self.round_wait('等待选卡结果画面，未操作', wait=.5)
        candidates, chosen = self.get_artifact_pos(screen)
        if self.to_choose_num == 0 and not (self.to_choose_artifact or self.to_choose_gear):
            if not self._is_single_card_reward(screen):
                return self.round_retry('未识别选卡标题，未确认', wait=.5)
            if self._pad_confirm_requests and not getattr(self, '_pad_reward_confirm', False):
                self.ctx.lost_void.priority_updated = False
                return self.round_success('已核验进入卡牌奖励确认页', wait=.2)
            self._pad_reward_confirm = True
        if self.to_choose_num == 0:
            reward_page = self._reward_page_signature(screen)
            previous_page = getattr(self, '_pad_reward_page', None)
            if reward_page is not None and previous_page is not None and reward_page[:2] == previous_page[:2] and (len(reward_page) == 2 or len(previous_page) == 2):
                reward_page = previous_page
            if reward_page is not None and reward_page != previous_page:
                # A bundle yields several reward pages. Bound retries per verified
                # card, rather than sharing the selection page's attempts.
                self._pad_reward_page = reward_page
                self._pad_confirm_requests = 0
                self._pad_target = None
                log.info('后台确认新奖励卡：%s', ' / '.join(reward_page))
        names = {i.artifact.display_name for i in candidates + chosen}
        previous = getattr(self, '_pad_options', set())
        new_single_option = self.to_choose_num == 1 and len(names) == 1 and focused_card(screen) is not None
        if self._pad_confirm_requests and (len(names) >= 2 or new_single_option) and previous and previous.isdisjoint(names):
            self.ctx.lost_void.priority_updated = False
            return self.round_success('已核验进入下一组选项', wait=.2)
        if self.to_choose_num > 1:
            return self._choose_multiple_with_pad(screen, candidates, chosen)
        single_selected = self.to_choose_num == 1 and len(chosen) == 1
        if self.to_choose_num == 1 and getattr(self, 'to_choose_gear_branch', False):
            single_selected = single_selected or self._get_chosen_count_from_confirm_button(screen, 1) == 1
        if single_selected:
            if chosen:
                self._pad_target = chosen[0]
            self._pad_options = names
        if self._pad_target is None and self.to_choose_num == 1 and not single_selected:
            available = [i for i in candidates + chosen if i.can_choose or i.chosen]
            new = self.sort_candidates([i for i in available if i.is_new]) if self.ctx.lost_void.challenge_config.artifact_priority_new else []
            priority = self.ctx.lost_void.get_artifact_by_priority(available, len(available)) if available else []
            ordered = new + priority + self.sort_candidates(available)
            if not ordered:
                return self.round_retry('未识别到卡牌，未确认', wait=.5)
            self._pad_target = ordered[0]
            self._pad_options = names
            log.info('后台选卡目标：%s', self._pad_target.artifact.display_name)
        if self.to_choose_num == 1 and not single_selected:
            focus = focused_card(screen)
            if focus is None:
                return self.round_wait('未识别选卡焦点，未确认', wait=.5)
            point = self._pad_target.rect.center
            if not focus.x1 <= point.x <= focus.x2:
                self._pad('right' if focus.center.x < point.x else 'left')
                return self.round_wait('手柄定位目标卡牌', wait=.4)
        elif self.to_choose_num != 1 and not (self.to_choose_artifact or self.to_choose_gear or getattr(self, '_pad_reward_confirm', False)):
            return self.round_retry('未识别选卡标题，未确认', wait=.5)
        reward = self.to_choose_num == 0 and getattr(self, '_pad_reward_page', None) is not None
        if self._pad_confirm_requests >= (5 if reward else 3):
            return self.round_fail('选卡确认后菜单未关闭')
        self._pad('confirm')
        self._pad_confirm_requests += 1
        return self.round_wait('已确认，等待选卡菜单实际关闭', wait=2 if reward else .8)

    def _is_single_card_reward(self, screen):
        # 特遣调查额外奖励没有“获得战利品”标题，使用卡牌标识、名称及
        # 单卡下面的确认按钮共同核验，不能把任意无标题页面直接跳过。
        matches = self.ctx.ocr_service.get_ocr_result_list(image=screen, rect=Rect(780,230,1140,900))
        marker = any('CARD' in str(m.data).upper() and m.center.y < 350 for m in matches)
        name = any(len(str(m.data).strip()) >= 2 and 475 < m.center.y < 545 for m in matches)
        confirm = any(str(m.data).strip() == '确定' and 750 < m.center.y < 900 for m in matches)
        return marker and name and confirm

    def _reward_page_signature(self, screen):
        service = getattr(self.ctx, 'ocr_service', None)
        if service is None:
            return None
        rows = service.get_ocr_result_list(image=screen, rect=Rect(780,230,1140,990))
        if not isinstance(rows, (list, tuple)):
            return None
        confirm = any(str(row.data).strip() == '确定' and 750 < row.center.y < 990 for row in rows)
        name_top, name_bottom = (410, 475) if self.to_choose_gear else (475, 565)
        names = tuple(sorted(str(row.data).replace(' ', '') for row in rows
                             if name_top < row.center.y < name_bottom and len(str(row.data).strip()) >= 2))
        quantity = tuple(sorted(str(row.data).replace(' ', '') for row in rows
                                if ((370 < row.center.y < 415) if self.to_choose_gear else (690 < row.center.y < 760))
                                and re.fullmatch(r'[x×]?\d+', str(row.data).strip())))
        return (('武备' if self.to_choose_gear else '藏品'), *names, *quantity) if names and confirm else None

    def _pad(self, action):
        ds4 = self.ctx.game_config.background_gamepad_type == 'ds4'
        if action == 'submit':
            key = 'ds4_square' if ds4 else 'xbox_x'
        else:
            key = ('ds4_cross' if ds4 else 'xbox_a') if action == 'confirm' else ('ds4_' if ds4 else 'xbox_') + 'dpad_' + action
        self.ctx.controller.btn_press(key, press_time=.12)

    def _choose_multiple_with_pad(self, screen, candidates, chosen):
        count = self._get_chosen_count_from_confirm_button(screen, self.to_choose_num)
        if count is None or not 0 <= count <= self.to_choose_num:
            return self.round_wait('未识别多选计数，未操作', wait=.5)
        pending = getattr(self, '_pad_pending_selection', None)
        selected = getattr(self, '_pad_selected_names', set())
        if pending is not None:
            name, before = pending
            if count <= before:
                polls = getattr(self, '_pad_selection_waits', 0) + 1
                self._pad_selection_waits = polls
                if polls >= 4:
                    return self.round_fail('多选操作后已选数量未增加')
                return self.round_wait('等待已选数量增加，未重复按键', wait=.5)
            selected.add(name)
            self._pad_selected_names = selected
            self._pad_pending_selection = None
            self._pad_target = None
        if count == self.to_choose_num:
            if self._pad_confirm_requests >= 3:
                return self.round_fail('多选提交后菜单未关闭')
            self._pad('submit')
            self._pad_confirm_requests += 1
            return self.round_wait('已核验选满，手柄提交并等待菜单关闭', wait=.8)
        if self._pad_target is None:
            available = [i for i in candidates if i.can_choose and not i.chosen and i.artifact.display_name not in selected]
            new = self.sort_candidates([i for i in available if i.is_new]) if self.ctx.lost_void.challenge_config.artifact_priority_new else []
            priority = self.ctx.lost_void.get_artifact_by_priority(available, len(available)) if available else []
            ordered = new + priority + self.sort_candidates(available)
            if not ordered:
                return self.round_retry('未识别到未选卡牌，未操作', wait=.5)
            self._pad_target = ordered[0]
            self._pad_options = {i.artifact.display_name for i in candidates + chosen}
        excluded = [i.rect.center.x for i in candidates + chosen if i.chosen or i.artifact.display_name in selected]
        focus = focused_card(screen, excluded_centers=excluded)
        if focus is None:
            # 恢复时焦点可能仍在唯一已选卡上，允许从已核验焦点移向未选目标。
            focus = focused_card(screen)
        if focus is None:
            return self.round_wait('未识别多选卡牌焦点，未操作', wait=.5)
        target = self._pad_target
        if not focus.x1 <= target.rect.center.x <= focus.x2:
            self._pad('right' if focus.center.x < target.rect.center.x else 'left')
            return self.round_wait('手柄定位未选卡牌', wait=.4)
        self._pad('confirm')
        self._pad_pending_selection = (target.artifact.display_name, count)
        self._pad_selection_waits = 0
        return self.round_wait(f'选择卡牌，等待实际计数 {count}/{self.to_choose_num} 增加', wait=.5)

    def select_by_layers(self, target_num: int) -> bool:
        # 选择策略：
        # 1) 先取NEW候选（无需试探点击）
        # 2) 再取优先级候选
        # 3) 合并去重后仅点击第一个，然后重算
        for _ in range(12):
            _, current_screen = self.ctx.controller.screenshot()
            can_choose_list, chosen_list = self.get_artifact_pos(current_screen)
            chosen_cnt = self.get_effective_chosen_count(current_screen, chosen_list, target_num)
            if chosen_cnt >= target_num:
                return True

            remain_cnt = target_num - chosen_cnt
            available_list = [i for i in can_choose_list if i.can_choose]
            if len(available_list) == 0:
                continue

            new_list: list[LostVoidArtifactPos] = []
            if self.ctx.lost_void.challenge_config.artifact_priority_new:
                new_list = self.sort_candidates([i for i in available_list if i.is_new])

            priority_list: list[LostVoidArtifactPos] = []
            if self.has_priority_rule():
                # 用当前排序规则产出优先级候选顺序
                priority_list = self.ctx.lost_void.get_artifact_by_priority(
                    available_list, len(available_list),
                    consider_priority_1=True,
                    consider_priority_2=True,
                    consider_not_in_priority=False,
                    consider_priority_new=False,
                )

            merged_list: list[LostVoidArtifactPos] = []
            used_center_set: set[tuple[int, int]] = set()
            for item in new_list + priority_list:
                key = (item.rect.center.x, item.rect.center.y)
                if key in used_center_set:
                    continue
                used_center_set.add(key)
                merged_list.append(item)

            if len(merged_list) == 0:
                log.info(
                    f'选择决策 | 常规层 | 需选={target_num} 已选={chosen_cnt} '
                    f'可选={len(available_list)} 结果=无候选 下一步=答题兜底'
                )
                return False

            new_text = ', '.join([i.artifact.display_name for i in new_list]) if len(new_list) > 0 else '无'
            priority_text = ', '.join([i.artifact.display_name for i in priority_list]) if len(priority_list) > 0 else '无'
            merged_text = ', '.join([i.artifact.display_name for i in merged_list]) if len(merged_list) > 0 else '无'
            log.info(
                f'选择决策 | 常规层 | 需选={target_num} 已选={chosen_cnt} 还需={remain_cnt} 可选={len(available_list)} '
                f'NEW={new_text} 优先级={priority_text} 合并={merged_text}'
            )

            target = merged_list[0]
            log.info(f'选择决策 | 常规层 | 动作=点击 目标={target.artifact.display_name} 坐标=({target.rect.center.x},{target.rect.center.y})')
            self.ctx.controller.click(target.rect.center)
            self.fallback_click_count += 1
            time.sleep(0.3)
            if self._reached_target_choose_num(target_num):
                return True

        _, final_screen = self.ctx.controller.screenshot()
        _, final_chosen_list = self.get_artifact_pos(final_screen)
        final_chosen_cnt = self.get_effective_chosen_count(final_screen, final_chosen_list, target_num)
        return final_chosen_cnt >= target_num

    def _reached_target_choose_num(self, target_num: int) -> bool:
        for _ in range(3):
            _, latest_screen = self.ctx.controller.screenshot()
            _, chosen_list = self.get_artifact_pos(latest_screen)
            chosen_cnt = self.get_effective_chosen_count(latest_screen, chosen_list, target_num)
            if chosen_cnt >= target_num:
                return True
            time.sleep(0.2)
        return False

    def has_priority_rule(self) -> bool:
        cfg = self.ctx.lost_void.challenge_config
        if cfg is None:
            return False
        if len(self.ctx.lost_void.dynamic_priority_list) > 0:
            return True
        if len(cfg.artifact_priority) > 0:
            return True
        return len(cfg.artifact_priority_2) > 0

    def sort_candidates(self, candidate_list: list[LostVoidArtifactPos]) -> list[LostVoidArtifactPos]:
        if len(candidate_list) <= 1:
            return candidate_list

        level_rank = {'S': 0, 'A': 1, 'B': 2}
        return sorted(
            candidate_list,
            key=lambda i: (
                0 if i.is_primary_name else 1,
                level_rank.get(i.artifact.level, 9),
                i.rect.center.x,
                i.rect.center.y,
            )
        )

    def click_confirm(self) -> OperationRoundResult:
        _, latest_screen = self.ctx.controller.screenshot()
        result = self.round_by_find_and_click_area(
            screen=latest_screen,
            screen_name='迷失之地-通用选择',
            area_name='按钮-确定',
            success_wait=1,
            retry_wait=1
        )
        if result.is_success:
            self.ctx.lost_void.priority_updated = False
            log.info("藏品选择成功，已设置优先级更新标志")
            return self.round_success(result.status)
        else:
            return self.round_retry(result.status, wait=1)

    def try_fill_by_answer_fallback(self, target_num: int) -> bool:
        """
        答题兜底：
        仅在常规层完全没有可选结果时启用，只点击白名单答题答案。
        命中失败后继续回落到原有盲点兜底。
        """
        tried_center_list: list[Point] = []

        for _ in range(12):
            _, current_screen = self.ctx.controller.screenshot()
            can_choose_list, chosen_list = self.get_artifact_pos(current_screen)
            chosen_cnt = self.get_effective_chosen_count(current_screen, chosen_list, target_num)
            if chosen_cnt >= target_num:
                log.info('选择决策 | 答题兜底 | 结果=已满足目标数量')
                return True

            answer_fallback_list = self.sort_candidates([
                i for i in can_choose_list
                if i.can_choose and i.artifact.category == '无详情'
            ])
            candidate_text = ', '.join([i.artifact.display_name for i in answer_fallback_list]) if len(answer_fallback_list) > 0 else '无'
            log.info(
                f'选择决策 | 答题兜底 | 需选={target_num} 已选={chosen_cnt} '
                f'候选数={len(answer_fallback_list)} 候选={candidate_text}'
            )

            target = None
            for candidate in answer_fallback_list:
                duplicated = False
                for tried_center in tried_center_list:
                    if abs(candidate.rect.center.x - tried_center.x) < 40 and abs(candidate.rect.center.y - tried_center.y) < 40:
                        duplicated = True
                        break
                if not duplicated:
                    target = candidate
                    break

            if target is None:
                log.info('选择决策 | 答题兜底 | 结果=无命中 下一步=盲点兜底')
                break

            log.info(f'选择决策 | 答题兜底 | 动作=点击 目标={target.artifact.display_name} 坐标=({target.rect.center.x},{target.rect.center.y})')
            self.ctx.controller.click(target.rect.center)
            tried_center_list.append(target.rect.center)
            self.fallback_click_count += 1
            time.sleep(0.3)

        _, final_screen = self.ctx.controller.screenshot()
        _, chosen_after = self.get_artifact_pos(final_screen)
        chosen_after_cnt = self.get_effective_chosen_count(final_screen, chosen_after, target_num)
        if chosen_after_cnt >= target_num:
            log.info('选择决策 | 答题兜底 | 结果=点击后已满足目标数量')
            return True

        return False

    def try_choose_by_click_name_text(self, target_num: int | None = None) -> bool:
        """
        兜底选择：
        1. 获取“区域-藏品名称”的OCR文本块
        2. 第一轮逐个点击，每次点击后检查“有同流派武备”
        3. 若第一轮未命中，第二轮逐个点击，每次点击后检查“已选择”
        """
        if target_num is not None:
            return self.try_fill_by_can_choose(target_num)

        _, current_screen = self.ctx.controller.screenshot()
        click_target_list = self.get_name_text_click_target_list(current_screen)
        if len(click_target_list) == 0:
            log.info('选择决策 | 盲点兜底 | 结果=未识别到名称文本块')
            return False

        log.info(f'选择决策 | 盲点兜底 | 阶段=第一轮 文本块数={len(click_target_list)}')
        for target_idx, target in enumerate(click_target_list):
            self.ctx.controller.click(target.center)
            time.sleep(0.3)

            _, clicked_screen = self.ctx.controller.screenshot()
            if self.has_same_style_selected(clicked_screen):
                log.info(f'选择决策 | 盲点兜底 | 阶段=第一轮 结果=命中同流派武备 序号={target_idx + 1}/{len(click_target_list)}')
                return True

        log.info(f'选择决策 | 盲点兜底 | 阶段=第二轮 文本块数={len(click_target_list)}')
        for target_idx, target in enumerate(click_target_list):
            self.ctx.controller.click(target.center)
            time.sleep(0.3)

            _, clicked_screen = self.ctx.controller.screenshot()
            if self.has_selected(clicked_screen):
                log.info(f'选择决策 | 盲点兜底 | 阶段=第二轮 结果=命中已选择 序号={target_idx + 1}/{len(click_target_list)}')
                return True

        _, final_screen = self.ctx.controller.screenshot()
        if self.has_selected(final_screen):
            log.info('选择决策 | 盲点兜底 | 阶段=第二轮 结果=结束后检测到已选择')
            return True

        log.info('选择决策 | 盲点兜底 | 结果=两轮结束仍未命中')
        return False

    def try_fill_by_can_choose(self, target_num: int) -> bool:
        """
        选择数量场景下的兜底：
        仅点击当前可选(can_choose)候选，避免点到已选导致覆盖。
        每次点击后都重新截图和重算，直到达到需选数量或候选耗尽。
        """
        tried_center_list: list[Point] = []

        for _ in range(12):
            _, current_screen = self.ctx.controller.screenshot()
            can_choose_list, chosen_list = self.get_artifact_pos(current_screen)
            chosen_cnt = self.get_effective_chosen_count(current_screen, chosen_list, target_num)
            if chosen_cnt >= target_num:
                log.info('选择决策 | can_choose兜底 | 结果=已达到目标数量')
                return True

            candidate_list = self.sort_candidates([i for i in can_choose_list if i.can_choose])
            target = None
            for candidate in candidate_list:
                duplicated = False
                for tried_center in tried_center_list:
                    if abs(candidate.rect.center.x - tried_center.x) < 40 and abs(candidate.rect.center.y - tried_center.y) < 40:
                        duplicated = True
                        break
                if not duplicated:
                    target = candidate
                    break

            if target is None:
                break

            self.ctx.controller.click(target.rect.center)
            tried_center_list.append(target.rect.center)
            self.fallback_click_count += 1
            time.sleep(0.3)

        _, final_screen = self.ctx.controller.screenshot()
        _, chosen_after = self.get_artifact_pos(final_screen)
        chosen_after_cnt = self.get_effective_chosen_count(final_screen, chosen_after, target_num)
        if chosen_after_cnt >= target_num:
            log.info('选择决策 | can_choose兜底 | 结果=点击后已达到目标数量')
            return True

        log.info('选择决策 | can_choose兜底 | 结果=候选耗尽仍未达到目标数量')
        return False

    def get_effective_chosen_count(
        self,
        screen: MatLike,
        chosen_list: list[LostVoidArtifactPos],
        target_num: int | None = None,
    ) -> int:
        """
        获取已选数量：
        1. 优先使用按钮“确定(x/y)”中的x计数
        2. 按钮计数无法识别时，使用本轮点击次数兜底
        """
        confirm_cnt = self._get_chosen_count_from_confirm_button(screen, target_num)
        if confirm_cnt is not None:
            # 以按钮计数为准，同时同步兜底计数，避免后续切换来源时出现突变。
            self.fallback_click_count = confirm_cnt
            return confirm_cnt
        log.debug(f'按钮计数未命中，使用点击次数兜底={self.fallback_click_count}')
        return self.fallback_click_count

    def _get_chosen_count_from_confirm_button(self, screen: MatLike, target_num: int | None = None) -> int | None:
        area = self.ctx.screen_loader.get_area('迷失之地-通用选择', '按钮-确定')
        ocr_result_map = self.ctx.ocr_service.get_ocr_result_map(
            image=screen,
            rect=area.rect,
            crop_first=True
        )

        chosen_cnt: int | None = None
        for text in ocr_result_map:
            normalized = text.strip().replace('（', '(').replace('）', ')')
            match = re.search(r'(\d+)\s*/\s*(\d+)', normalized)
            if match is None:
                continue
            current_cnt = int(match.group(1))
            total_cnt = int(match.group(2))
            if target_num is not None and total_cnt != target_num:
                log.debug(f'按钮计数忽略 文本={text} 解析={current_cnt}/{total_cnt} 目标={target_num}')
                continue
            if chosen_cnt is None or current_cnt > chosen_cnt:
                chosen_cnt = current_cnt

        if chosen_cnt is not None:
            log.debug(f'按钮计数命中 已选={chosen_cnt} 目标={target_num}')
        return chosen_cnt

    def get_name_text_click_target_list(self, screen: MatLike) -> list[MatchResult]:
        area = self.ctx.screen_loader.get_area('迷失之地-通用选择', '区域-藏品名称')
        ocr_result_map = self.ctx.ocr_service.get_ocr_result_map(
            image=screen,
            rect=area.rect,
            crop_first=True
        )

        all_result_list: list[MatchResult] = []
        for text, mrl in ocr_result_map.items():
            if len(text.strip()) == 0:
                continue
            for mr in mrl:
                all_result_list.append(mr)

        all_result_list.sort(key=lambda i: (i.center.x, i.center.y))

        # 同一卡片名称可能被OCR拆成多个文本块，按X坐标做一次聚合，避免重复点同一张
        result_list: list[MatchResult] = []
        for mr in all_result_list:
            duplicated = False
            for existed in result_list:
                if abs(existed.center.x - mr.center.x) < 90:
                    duplicated = True
                    break
            if not duplicated:
                result_list.append(mr)

        return result_list

    def has_same_style_selected(self, screen: MatLike) -> bool:
        selected_area = self.ctx.screen_loader.get_area('迷失之地-通用选择', '区域-藏品已选择')
        return screen_utils.find_by_ocr(
            self.ctx,
            screen,
            target_cn='有同流派武备',
            area=selected_area
        )

    def has_selected(self, screen: MatLike) -> bool:
        selected_area = self.ctx.screen_loader.get_area('迷失之地-通用选择', '区域-藏品已选择')
        return screen_utils.find_by_ocr(
            self.ctx,
            screen,
            target_cn='已选择',
            area=selected_area
        )

    def get_artifact_pos(self, screen: MatLike) -> tuple[list[LostVoidArtifactPos], list[LostVoidArtifactPos]]:
        """
        获取藏品的位置
        @param screen: 游戏画面
        @return: tuple[识别到的武备的位置, 已经选择的位置]
        """
        self.check_choose_title(screen)
        if self.to_choose_num == 0:  # 不需要选择的
            return [], []

        artifact_pos_list: list[LostVoidArtifactPos] = self.ctx.lost_void.get_artifact_pos(
            screen,
            to_choose_gear_branch=self.to_choose_gear_branch,
            screen_name='迷失之地-通用选择'
        )

        can_choose_list = [i for i in artifact_pos_list if i.can_choose]
        can_choose_text = ', '.join([i.artifact.display_name for i in can_choose_list]) if len(can_choose_list) > 0 else '无'
        log.info(f'选择识别 | 可选 | 数量={len(can_choose_list)} 候选={can_choose_text}')

        chosen_list = [i for i in artifact_pos_list if i.chosen]
        chosen_text = ', '.join([i.artifact.display_name for i in chosen_list]) if len(chosen_list) > 0 else '无'
        log.info(f'选择识别 | 已选 | 数量={len(chosen_list)} 候选={chosen_text}')

        return can_choose_list, chosen_list

    def check_choose_title(self, screen: MatLike) -> None:
        """
        识别标题 判断要选择的类型和数量
        :param screen: 游戏画面
        """
        self.to_choose_artifact = False
        self.to_choose_gear = False
        self.to_choose_gear_branch = False
        self.to_choose_num = 0
        area = self.ctx.screen_loader.get_area('迷失之地-通用选择', '区域-标题')
        ocr_result = self.ctx.ocr.crop_and_run_ocr(screen, area.rect)

        title_words = [w.strip() for w in ocr_result if len(w.strip()) > 0]
        title_text = ''.join(title_words)
        normalized_text = (
            title_text.replace('（', '(').replace('）', ')')
            .replace(' ', '').replace('　', '')
        )

        def apply_rule(rule_id: str) -> None:
            if rule_id == 'GEAR_GAIN' or rule_id == 'GEAR_UPGRADE':
                self.to_choose_gear = True
                self.to_choose_num = 0
            elif rule_id == 'ARTIFACT_GAIN':
                self.to_choose_artifact = True
                self.to_choose_num = 0
            elif rule_id == 'GEAR_BRANCH':
                self.to_choose_gear = True
                self.to_choose_gear_branch = True
                self.to_choose_num = 1
            elif rule_id == 'CHOOSE_2':
                self.to_choose_artifact = True
                self.to_choose_num = 2
            elif rule_id == 'CHOOSE_1_GEAR':
                self.to_choose_gear = True
                self.to_choose_num = 1
            elif rule_id == 'CHOOSE_1_CARD':
                self.to_choose_artifact = True
                self.to_choose_num = 1
            elif rule_id == 'CHOOSE_1':
                # 1.5 更新后 武备和普通鸣徽都可能是这个标题
                self.to_choose_num = 1

        # 第一轮：精准匹配（避免“1项”被模糊吸附到“2项”）
        exact_rule_list: list[tuple[str, list[str]]] = [
            ('GEAR_GAIN', ['获得武备']),
            ('GEAR_UPGRADE', ['武备已升级']),
            ('ARTIFACT_GAIN', ['获得战利品']),
            ('GEAR_BRANCH', ['请选择战术棱镜方案强化的方向']),
            # 兼容 2枚/两枚 变体
            ('CHOOSE_2', ['请选择2项', '请选择2枚鸣徽', '请选择两枚鸣徽']),
            ('CHOOSE_1_GEAR', ['请选择1个武备']),
            ('CHOOSE_1_CARD', ['请选择1张卡牌']),
            # 你指出的文案修正：1枚鸣徽
            ('CHOOSE_1', ['请选择1项', '请选择1枚鸣徽', '请选择一枚鸣徽']),
        ]

        matched_rule = None
        for rule_id, phrase_list in exact_rule_list:
            if any(phrase in normalized_text for phrase in phrase_list):
                apply_rule(rule_id)
                matched_rule = f'exact:{rule_id}'
                break

        # 第二轮：模糊匹配兜底（只有第一轮没命中才使用）
        if matched_rule is None and len(title_words) > 0:
            fuzzy_target_list = [
                '获得武备',
                '武备已升级',
                '获得战利品',
                '请选择战术棱镜方案强化的方向',
                '请选择2项',
                '请选择2枚鸣徽',
                '请选择两枚鸣徽',
                '请选择1个武备',
                '请选择1张卡牌',
                '请选择1项',
                '请选择1枚鸣徽',
                '请选择一枚鸣徽',
            ]
            target_2_rule = {
                '获得武备': 'GEAR_GAIN',
                '武备已升级': 'GEAR_UPGRADE',
                '获得战利品': 'ARTIFACT_GAIN',
                '请选择战术棱镜方案强化的方向': 'GEAR_BRANCH',
                '请选择2项': 'CHOOSE_2',
                '请选择2枚鸣徽': 'CHOOSE_2',
                '请选择两枚鸣徽': 'CHOOSE_2',
                '请选择1个武备': 'CHOOSE_1_GEAR',
                '请选择1张卡牌': 'CHOOSE_1_CARD',
                '请选择1项': 'CHOOSE_1',
                '请选择1枚鸣徽': 'CHOOSE_1',
                '请选择一枚鸣徽': 'CHOOSE_1',
            }
            for ocr_word in title_words:
                idx = str_utils.find_best_match_by_difflib(
                    ocr_word,
                    fuzzy_target_list,
                    cutoff=0.9,
                )
                if idx is None:
                    continue
                target_phrase = fuzzy_target_list[idx]
                apply_rule(target_2_rule[target_phrase])
                matched_rule = f'fuzzy:{target_2_rule[target_phrase]}:{ocr_word}->{target_phrase}'
                break

        # 兜底：标题仍未命中时，仍可用下方GEAR标识判断为武备单选
        if matched_rule is None:
            result = self.round_by_find_area(screen, '迷失之地-通用选择', '区域-武备标识')
            if result.is_success:
                self.to_choose_gear = True
                self.to_choose_num = 1
                matched_rule = 'fallback:gear_marker'
            else:
                matched_rule = 'fallback:none'

        log.info(
            f'选择决策 | 标题 | OCR={title_words if len(title_words) > 0 else ["无"]} '
            f'规则={matched_rule} 需选={self.to_choose_num} '
            f'藏品={self.to_choose_artifact} 武备={self.to_choose_gear} 分支={self.to_choose_gear_branch}'
        )

def __debug():
    ctx = ZContext()
    ctx.init()
    ctx.init_ocr()
    ctx.lost_void.init_before_run()
    ctx.run_context.start_running()

    op = LostVoidChooseCommon(ctx)
    op.execute()


def __get_get_artifact_pos():
    ctx = ZContext()
    ctx.init()
    ctx.init_ocr()
    ctx.lost_void.init_before_run()

    op = LostVoidChooseCommon(ctx)
    from onedragon.utils import debug_utils
    screen = debug_utils.get_debug_image('20251112133547')
    art_list, chosen_list = op.get_artifact_pos(screen)
    print(len(art_list), len(chosen_list))
    cv2_utils.show_image(screen, chosen_list[0] if len(chosen_list) > 0 else None, wait=0)
    import cv2
    cv2.destroyAllWindows()


if __name__ == '__main__':
    __debug()
