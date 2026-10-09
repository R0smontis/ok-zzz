# -*- coding: utf-8 -*-
"""常驻战斗助手：统一输入接管、配置切换和帧调度。"""
import math
import os
import threading
import time

from ok import TriggerTask
from onedragon.utils.log_utils import log
from src.tasks.zzz_base_task import ZzzBaseTask
from src.diagnostics.recorder import record_event


def list_battle_templates(sub_dir: str, suffix: str = '.merged.yml') -> list[str]:
    """枚举 merged/sample/用户配置，去除重复名称。"""
    from onedragon.utils import os_utils
    suffixes = ('.merged.yml', '.sample.yml', '.yml')
    fallback = '闪避' if sub_dir == 'dodge' else '全配队通用'
    try:
        directory = os_utils.get_path_under_work_dir('config', sub_dir)
        names = set()
        for entry in os.scandir(directory):
            if not entry.is_file():
                continue
            for ending in suffixes:
                if entry.name.endswith(ending):
                    names.add(entry.name[:-len(ending)])
                    break
        names.discard('_od_merged')
        return sorted(names) or [fallback]
    except OSError:
        return [fallback]


class BattleTriggerTask(ZzzBaseTask, TriggerTask):
    config_key = '战斗配置'
    config_sub_dir = 'auto_battle'
    COMBAT_DURATION = 10.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.trigger_interval = 0.02
        self._engine_started = False
        self._engine_op = None
        self._last_settings = None
        self._last_frame_check = None
        self._engine_lock = threading.RLock()
        self._actions_running = False
        self._input_phase = 'idle'
        self._ui_paused = False
        self._last_burst_end = None
        self._arrow_since = None
        self._arrow_last_seen = 0.0
        self._input_until = 0.0
        self._input_generation = 0
        self._session_started = 0.0
        self._last_screen_time = 0.0
        self._last_frame_seen = 0.0
        self._last_flash = None
        self._last_flash_time = 0.0
        self._flash_absent_since = None
        self._last_visual_warning_time = 0.0
        self._last_event_time = 0.0
        self._watchdog_stop = None
        self._input_guard = self._input_allowed
        self._action_guard = self._action_allowed
        self._event_listener = self._on_dodge_event
        self._engine_hwnd = None
        self.config_description.update({
            '截图间隔秒': '识别间隔，范围 0.01～1 秒；较大值降低 CPU 占用，但响应更慢',
            '后台模式': '开启：虚拟手柄，不切换前台、不移动鼠标，需要 ViGEmBus；关闭：前台键鼠，切走时暂停',
        })

    def validate_config(self, key, value):
        error = super().validate_config(key, value)
        if error:
            return error
        if key == '截图间隔秒':
            try:
                interval = float(value)
            except (TypeError, ValueError):
                return '截图间隔秒必须是数字'
            if not math.isfinite(interval) or not 0.01 <= interval <= 1:
                return '截图间隔秒应在 0.01～1 之间'

    def _start_engine(self, config_name: str) -> bool:
        from zzz_od.application.battle_assistant.battle_assistant_input_mode import (
            apply_battle_assistant_input_mode,
        )
        ctx = self.ctx
        battle_ctx = ctx.auto_battle_context
        try:
            self.stop_battle_triggers()
            ctx.init_for_application(activate=False)
            if not ctx.controller.init_game_win():
                raise RuntimeError('未找到游戏窗口，请先启动游戏并在界面选择窗口')
            success, message = apply_battle_assistant_input_mode(
                ctx, background_mode=bool(self.config.get('后台模式', False)), activate=False)
            if not success:
                raise RuntimeError(message)
            battle_ctx.init_auto_op(config_name, sub_dir=self.config_sub_dir)
            with self._engine_lock:
                # 用户可能在模型加载期间取消；取消后不再发送游戏输入。
                if not self.enabled:
                    return False
                self._engine_op = battle_ctx.auto_op
                self._engine_hwnd = ctx.controller.game_win.get_hwnd()
                self._session_started = time.time()
                ctx.controller.battle_input_guard = self._input_guard
                ctx.controller.battle_action_guard = self._action_guard
                self._engine_op.execution_allowed = self._input_guard
                self._engine_op.execution_guard_factory = self._make_input_guard
                self._engine_op.event_only = self.config_sub_dir == 'dodge'
                self._engine_op.event_started_at = self._session_started
                battle_ctx.dodge_context.event_listener = self._event_listener
                battle_ctx.init_battle_context()
                battle_ctx.clear_all_states()
                battle_ctx.start_context_async()
                self._engine_started = True
                from src.controls.interaction import selected_gamepad_mode
                self._last_settings = (config_name, bool(self.config.get('后台模式', False)) or selected_gamepad_mode())
                self._watchdog_stop = threading.Event()
                threading.Thread(target=self._watch_input, args=(self._watchdog_stop,),
                                 name='battle-input-watchdog', daemon=True).start()
                if self.config_sub_dir == 'dodge':
                    # Passive event subscription; both normal and periodic input are gated.
                    self._engine_op.start_running_async()
            self.info['助手状态'] = '等待闪避事件' if self.config_sub_dir == 'dodge' else '等待敌人'
            self.info['输入方式'] = message
            log.info(f'{self.name}识别已启动: {config_name}')
            return True
        except Exception as exc:
            self._stop_engine()
            self.log_error(f'{self.name}启动失败：{exc}', notify=True)
            return False

    def _stop_engine(self):
        with self._engine_lock:
            self._stop_engine_locked()

    def _stop_engine_locked(self):
        self._input_until = 0.0
        self._input_generation += 1
        if self._watchdog_stop is not None:
            self._watchdog_stop.set()
            self._watchdog_stop = None
        if self._engine_op is not None:
            try:
                battle_ctx = self.ctx.auto_battle_context
                # 上下文可能已被独立应用接管，不停止其它应用的新指令。
                if battle_ctx.auto_op is self._engine_op:
                    battle_ctx.stop_auto_battle()
                else:
                    self._engine_op.stop_running()
                # Cached templates may be reused by ordinary applications later.
                self._engine_op.execution_allowed = None
                self._engine_op.execution_guard_factory = None
                self._engine_op.event_only = False
                if battle_ctx.dodge_context.event_listener is self._event_listener:
                    battle_ctx.dodge_context.event_listener = None
                if self.ctx.controller.battle_input_guard is self._input_guard:
                    self.ctx.controller.battle_input_guard = None
                if getattr(self.ctx.controller, 'battle_action_guard', None) is self._action_guard:
                    self.ctx.controller.battle_action_guard = None
            except Exception as exc:
                log.warning(f'{self.name}停止异常: {exc}')
        self._engine_started = False
        self._engine_op = None
        self._engine_hwnd = None
        self._last_settings = None
        self._last_frame_check = None
        self._actions_running = False
        self._input_phase = 'idle'
        self._ui_paused = False
        self._last_burst_end = None
        self._last_screen_time = 0.0
        self._last_frame_seen = 0.0
        self._last_flash = None
        self._last_flash_time = 0.0
        self._flash_absent_since = None
        self._last_visual_warning_time = 0.0
        self._last_event_time = 0.0

    def _input_allowed(self):
        return self._input_phase in ('normal', 'chain') and self._session_input_allowed()

    def _action_allowed(self, action):
        return (self._input_allowed() and (self._input_phase == 'normal'
                or action in ('chain_left', 'chain_right', 'chain_cancel')))

    def _session_input_allowed(self):
        return (self.enabled and self._engine_started
                and self._engine_op is self.ctx.auto_battle_context.auto_op
                and time.monotonic() < self._input_until
                and time.monotonic() - self._last_frame_seen < self._frame_lease()
                and self._window_input_allowed())

    def _window_input_allowed(self):
        controller = self.ctx.controller
        window = controller.game_win
        return (window.get_hwnd() == self._engine_hwnd and window.is_win_valid
                and (controller.background_mode or getattr(controller, 'message_mode', False) or window.is_win_active))

    def _make_input_guard(self):
        generation = self._input_generation
        return lambda: generation == self._input_generation and self._input_allowed()

    def _suspend_actions(self, preserve_states=False):
        record_event('assistant_suspend', task=self.name, was_running=self._actions_running,
                     throttle=f'assistant_suspend:{self.name}')
        self._input_until = 0.0
        self._input_generation += 1
        self._last_burst_end = time.monotonic() if preserve_states else None
        if not self._actions_running:
            return
        self._actions_running = False
        self._ui_paused = False
        if self._engine_op is not self.ctx.auto_battle_context.auto_op:
            return
        # Keep the model/audio alive; cancel the current sequence and held keys.
        if self.config_sub_dir == 'dodge':
            with self._engine_op._task_lock:
                self._engine_op._stop_running_task()
        else:
            self._engine_op.stop_running()
            if not preserve_states:
                self.ctx.auto_battle_context.clear_all_states()
        self.ctx.controller.btn_controller.reset()
        self.ctx.controller.is_moving = False
        self.info['助手状态'] = '等待闪避事件' if self.config_sub_dir == 'dodge' else '等待敌人'

    def _set_input_phase(self, phase, screenshot_time):
        if phase == self._input_phase:
            return
        previous = self._input_phase
        self._input_phase = phase
        self._last_screen_time = screenshot_time
        self._last_flash = None
        self._flash_absent_since = None
        self._arrow_since = None
        self._input_generation += 1
        record_event('assistant_input_phase', task=self.name, previous=previous, phase=phase,
                     captured_at=screenshot_time)
        if self._actions_running:
            # Cancel the old sequence before entering a cinematic/chain screen.
            # Keep the fixed deadline and character state across the animation.
            self._engine_op.stop_running()
            self.ctx.controller.btn_controller.reset()
            self.ctx.controller.is_moving = False
            self._ui_paused = phase == 'idle'
            if phase != 'idle':
                self._engine_op.start_running_async()
        elif self.config_sub_dir == 'dodge' and previous == 'idle' and phase == 'normal':
            self._engine_op.start_running_async()

    def _watch_input(self, stop_event):
        while not stop_event.wait(0.02):
            with self._engine_lock:
                if stop_event.is_set():
                    return
                if self._actions_running and not self._session_input_allowed():
                    self._suspend_actions(preserve_states=(self.config_sub_dir != 'dodge'
                        and self._input_phase == 'normal' and time.monotonic() >= self._input_until))

    def _on_dodge_event(self, state_name, screenshot_time):
        with self._engine_lock:
            now = time.time()
            if state_name is not None:
                record_event('assistant_dodge_event', task=self.name, event=state_name,
                             age=now-screenshot_time, captured_at=screenshot_time)
            reason = None
            if not self.enabled or not self._engine_started:
                reason = '助手已停止'
            elif self._input_phase != 'normal':
                reason = '攻击按钮不可见或连携画面'
            elif not self._window_input_allowed():
                reason = '窗口输入条件不满足'
            elif self._engine_op is not self.ctx.auto_battle_context.auto_op:
                reason = '战斗引擎已切换'
            elif screenshot_time < self._session_started or screenshot_time < self._last_screen_time:
                reason = '旧画面结果'
            elif not 0 <= now-screenshot_time <= .25:
                reason = '识别结果过期'
            if reason is not None:
                if state_name is not None:
                    record_event('assistant_warning_rejected', warning=state_name, reason=reason,
                                 captured_at=screenshot_time, age=now-screenshot_time,
                                 throttle=f'warning_rejected:{self.name}:{reason}')
                return False
            if state_name is None:
                # One missed model frame must not re-arm the same attack.
                if self._flash_absent_since is None:
                    self._flash_absent_since = screenshot_time
                return False
            # Audio and a colored flash often describe the same attack.
            if (state_name == '闪避识别-声音'
                    and 0 <= screenshot_time-self._last_visual_warning_time < .35):
                record_event('assistant_warning_rejected', warning=state_name, reason='同一次视觉预警的声音',
                             captured_at=screenshot_time, throttle=f'warning_audio_duplicate:{self.name}')
                return False
            # A continuous flash is one event, even if the classifier sees it in many frames.
            is_flash = state_name != '闪避识别-声音'
            if (is_flash and self._flash_absent_since is not None
                    and screenshot_time-self._flash_absent_since >= .08):
                self._last_flash = None
            repeated = (is_flash and self._last_flash == state_name
                        and screenshot_time - self._last_flash_time < 0.3)
            if is_flash:
                self._last_flash = state_name
                self._last_flash_time = screenshot_time
                self._flash_absent_since = None
                self._last_visual_warning_time = screenshot_time
            if repeated or screenshot_time - self._last_event_time < 0.1:
                record_event('assistant_warning_rejected', warning=state_name,
                             reason='持续闪光重复帧' if repeated else '事件间隔过短',
                             captured_at=screenshot_time, throttle=f'warning_duplicate:{self.name}')
                return False
            self._last_event_time = screenshot_time
            if self.config_sub_dir != 'dodge':
                # A fresh warning is also direct evidence of an active fight.
                if self._actions_running and time.monotonic() >= self._input_until:
                    self._suspend_actions(preserve_states=True)
                self._activate_combat(state_name)
                self._publish_dodge_event(state_name, screenshot_time)
                return True
            self._suspend_actions()
            self.ctx.auto_battle_context.clear_all_states()
            self._engine_op.event_started_at = screenshot_time
            # Bounded response permits configured dodge/counter/assist follow-ups.
            self._input_until = time.monotonic() + 0.8
            self._actions_running = True
            self.info['助手状态'] = f'响应{state_name}'
            self._publish_dodge_event(state_name, screenshot_time)
            return True

    def _publish_dodge_event(self, state_name, screenshot_time):
        from onedragon.base.conditional_operation.state_recorder import StateRecord
        service = self.ctx.auto_battle_context.state_record_service
        if self.config_sub_dir == 'auto_battle' and self.config.get('优先实时闪避', True):
            from zzz_od.auto_battle.atomic_op.realtime_response import WARNING_CODES
            service.batch_update_states([StateRecord('按键可用-普通攻击', screenshot_time),
                StateRecord(state_name, screenshot_time),
                StateRecord('自定义-实时闪避事件', screenshot_time, value=WARNING_CODES[state_name])])
        else:
            service.update_state(StateRecord(state_name, screenshot_time))

    def _frame_lease(self):
        return max(0.25, float(self.config.get('截图间隔秒', 0.02)) * 2)

    def _activate_combat(self, evidence):
        if not self._actions_running:
            record_event('assistant_combat_start', task=self.name, evidence=evidence,
                         duration=self.COMBAT_DURATION)
            # Immediate re-confirmation must not erase the current role/mode
            # and wait for avatar recognition to bootstrap a second time.
            continuing = (self._last_burst_end is not None
                          and time.monotonic() - self._last_burst_end <= .5)
            if not continuing:
                self.ctx.auto_battle_context.clear_all_states()
            self._last_burst_end = None
            self._input_until = time.monotonic() + self.COMBAT_DURATION
            self._actions_running = True
            self._ui_paused = False
            self._engine_op.start_running_async()
            self.info['触发原因'] = evidence

    def enable(self):
        # UI 线程只更新启用状态，模型与控制器初始化交给执行线程。
        self.stop_battle_triggers()
        self.enable_passive_trigger()

    def on_create(self):
        super().on_create()
        if self.config_sub_dir == 'auto_battle':
            self.ctx.auto_battle_context.realtime_dodge_enabled_provider = (
                lambda: bool(self.config.get('优先实时闪避', True)))
        from ok.core.events import communicate
        communicate.executor_paused.connect(self._on_executor_paused)

    def _on_executor_paused(self, paused):
        if paused:
            self._stop_engine()

    def disable(self):
        with self._engine_lock:
            try:
                self._stop_engine()
            finally:
                super().disable()

    def on_destroy(self):
        from ok.core.events import communicate
        communicate.executor_paused.disconnect(self._on_executor_paused)
        self._stop_engine()
        super().on_destroy()

    def should_trigger(self):
        interval = self.config.get('截图间隔秒', 0.02)
        error = self.validate_config('截图间隔秒', interval)
        if error:
            self.log_error(error, notify=True)
            self.disable()
            return False
        from src.runtime.inference import recognition_interval
        self.trigger_interval = max(float(interval), recognition_interval())
        return self.enabled and super().should_trigger()

    def run(self):
        if not self.enabled:
            return
        config_name = str(self.config.get(self.config_key, '全配队通用'))
        from src.controls.interaction import selected_gamepad_mode
        settings = (config_name, bool(self.config.get('后台模式', False)) or selected_gamepad_mode())
        if self._engine_started and (
                self._last_settings != settings or
                self.ctx.controller.game_win.get_hwnd() != self._engine_hwnd or
                self._engine_op is not self.ctx.auto_battle_context.auto_op):
            self._stop_engine()
        if not self._engine_started and not self._start_engine(config_name):
            self.disable()
            return
        if not self._window_input_allowed():
            with self._engine_lock:
                self._last_screen_time = time.time()
                self._suspend_actions()
                self.info['助手状态'] = '等待游戏前台（切走时暂停）'
            return
        battle_ctx = self.ctx.auto_battle_context
        battle_ctx.auto_ultimate_enabled = bool(self.config.get('自动终结技', True))
        frame = self.ctx.controller.normalize_frame(self.frame)
        geometry = getattr(self.ctx.controller, 'frame_geometry', None)
        if geometry:
            self.info['窗口分辨率'] = '×'.join(map(str, geometry['source']))
        if frame is None:
            with self._engine_lock:
                self._last_screen_time = time.time()
                self._suspend_actions()
            return
        now = time.monotonic()
        interval = float(self.config.get('截图间隔秒', 0.02))
        if self._last_frame_check is not None and now - self._last_frame_check < interval:
            return
        self._last_frame_check = now
        self._last_frame_seen = now
        screen_time = time.time()
        battle_ctx.auto_ultimate_enabled = bool(self.config.get('自动终结技', True))
        attack_hud = battle_ctx.is_normal_attack_btn_available(frame)
        with self._engine_lock:
            if not self.enabled or not self._engine_started:
                return
            if not attack_hud and self._input_phase == 'normal':
                self._set_input_phase('idle', screen_time)
        chain_ui = False
        if not attack_hud and self.config_sub_dir != 'dodge':
            from zzz_od.auto_battle.battle_presence import detect_chain_presence, has_chain_timer
            # A small UI probe is the only exception. No enemy/flash/role model
            # runs without the attack button; chain portraits confirm its UI.
            if has_chain_timer(frame):
                chain_ui = detect_chain_presence(frame, battle_ctx, timer_confirmed=True) is not None
        with self._engine_lock:
            if not self.enabled or not self._engine_started:
                return
            self._set_input_phase('normal' if attack_hud else 'chain' if chain_ui else 'idle', screen_time)
            if (self.config_sub_dir != 'dodge' and self._actions_running
                    and now >= self._input_until):
                self._suspend_actions(preserve_states=attack_hud)
            scan_enemy = self.config_sub_dir != 'dodge' and attack_hud and not self._actions_running
            scan_op = self._engine_op
        # Pixel matching must not hold the lifecycle lock: fresh GPU/audio
        # warnings and the release watchdog can complete during this scan.
        evidence = None
        if scan_enemy:
            from zzz_od.auto_battle.battle_presence import detect_battle_presence
            evidence = detect_battle_presence(frame, battle_ctx)
        elif chain_ui:
            evidence = '连携技'
        with self._engine_lock:
            if not self.enabled or not self._engine_started or self._engine_op is not scan_op:
                return
            # Timestamp is a session watermark for late asynchronous recognitions.
            if self.config_sub_dir == 'dodge':
                if not attack_hud:
                    self._last_screen_time = screen_time
                    self._last_flash = None
                    self._suspend_actions()
                # Don't advance the watermark on each normal frame: a result may
                # arrive a few frames later, but must still satisfy the 250ms TTL.
            else:
                # Enemy presence starts a fixed burst. Do not rescan or extend
                # its deadline while skills/agents/dodge states keep updating.
                if not self._actions_running:
                    if attack_hud:
                        if evidence == '敌人方向箭头':
                            if self._arrow_since is None or now-self._arrow_last_seen > .3:
                                self._arrow_since = now
                            self._arrow_last_seen = now
                            if now-self._arrow_since < .12:
                                evidence = None
                        else:
                            self._arrow_since = None
                        record_event('enemy_detection', task=self.name, evidence=evidence,
                                     captured_at=screen_time)
                    elif chain_ui:
                        evidence = '连携技'
                        record_event('chain_detection', task=self.name, captured_at=screen_time)
                    if evidence is None:
                        self._last_screen_time = screen_time
                        self._suspend_actions()
                        if not attack_hud:
                            self.info['助手状态'] = '等待攻击按钮（暂停敌人检测）'
                    else:
                        self._activate_combat(evidence)
                if self._actions_running and self._ui_paused:
                    self.info['助手状态'] = '等待攻击按钮（动画期间暂停操作与战斗识别）'
                elif self._actions_running:
                    remaining = max(0.0, self._input_until - time.monotonic())
                    self.info['助手状态'] = f'战斗中：剩余 {remaining:.1f} 秒，结束后检测敌人'
        stop_on_end = bool(self.config.get('战斗结束停止', False))
        in_battle = battle_ctx.check_battle_state(
            frame, screen_time,
            check_battle_end_normal_result=stop_on_end,
            check_battle_end_hollow_result=stop_on_end,
            check_battle_end_defense_result=stop_on_end,
            passive=self.config_sub_dir == 'dodge' or not self._actions_running,
            attack_hud_visible=attack_hud, chain_ui_visible=chain_ui,
        )
        if stop_on_end and not in_battle and battle_ctx.last_check_end_result is not None:
            self.log_info(f'战斗结束（{battle_ctx.last_check_end_result}），已停用自动战斗', notify=True)
            self.disable()


class AutoCombatTask(BattleTriggerTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '⚔️ 自动战斗'
        self.description = '发现敌人后持续战斗 10 秒，结束后再检测；与闪避助手互斥'
        self.default_config.update({
            '_enabled': False, '战斗配置': '全配队通用', '自动终结技': True,
            '优先实时闪避': True, '战斗结束停止': False, '截图间隔秒': 0.02, '后台模式': False,
        })
        self.config_type['战斗配置'] = {
            'type': 'drop_down', 'options': list_battle_templates('auto_battle'),
        }
        self.config_description.update({
            '战斗配置': '切换后在下一次识别时重新加载指令',
            '自动终结技': '控制终结技自动释放，可在运行中调整',
            '优先实时闪避': '开启：黄光优先支援弹刀（默认空格/手柄RB），红光或声音闪避反击；关闭：按角色模板处理支援、闪避及无敌动作',
            '战斗结束停止': '识别到结算画面后停用此助手；下一场需重新启用',
        })


class DodgeAssistantTriggerTask(BattleTriggerTask):
    config_key = '闪避配置'
    config_sub_dir = 'dodge'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '🛡️ 闪避助手'
        self.description = '实时响应红光、黄光或声音提示，无事件时不操作；与自动战斗互斥'
        self.default_config.update({
            '_enabled': False, '闪避配置': '闪避', '截图间隔秒': 0.02, '后台模式': False,
        })
        self.config_type['闪避配置'] = {
            'type': 'drop_down', 'options': list_battle_templates('dodge'),
        }
        self.config_description['闪避配置'] = '切换后在下一次识别时重新加载闪避指令'
