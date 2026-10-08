"""Route a fresh warning to defensive assist or dodge, then follow up."""
import threading
import time

from onedragon.base.conditional_operation.atomic_op import AtomicOp
from src.diagnostics import record_event

WARNING_CODES = {'闪避识别-红光': 1, '闪避识别-黄光': 2, '闪避识别-声音': 3}


class AtomicRealtimeResponse(AtomicOp):
    OP_NAME = '实时战斗响应'

    def __init__(self, ctx, warning=None):
        super().__init__(self.OP_NAME)
        self.ctx = ctx
        self.warning = warning
        self._stop = threading.Event()

    def _fresh(self, name, age=.25):
        recorder = self.ctx.state_record_service.get_state_recorder(name)
        return recorder if (recorder is not None and recorder.last_record_time > 0
            and 0 <= time.time()-recorder.last_record_time <= age) else None

    def _assist_block_reason(self):
        if len(self.ctx.agent_context.team_info.agent_list) < 2:
            return '没有可切换队友'
        for state, reason in (('切人-冷却', '切人冷却'), ('格挡-破碎', '支援不可用')):
            recorder = self._fresh(state, .5)
            if recorder is not None and (recorder.last_value or 0) > 0:
                return reason
        return None

    def execute(self):
        self._stop.clear()
        if self._fresh('按键可用-普通攻击') is None:
            return
        if self.warning is None:
            recorder = self._fresh('自定义-实时闪避事件')
            if recorder is None:
                return
            warning = next((name for name, code in WARNING_CODES.items()
                            if recorder.last_value == code), None)
        else:
            warning = self.warning
            if warning not in WARNING_CODES:
                return
            recorder = self._fresh(warning)
            # Several fallback handlers may still match within the 250 ms
            # window. Route their operation by the newest actual cue.
            for name in WARNING_CODES:
                candidate = self._fresh(name)
                if candidate is not None and (recorder is None
                        or candidate.last_record_time > recorder.last_record_time):
                    warning, recorder = name, candidate
        if recorder is None or warning not in WARNING_CODES:
            return
        reason = self._assist_block_reason() if warning == '闪避识别-黄光' else None
        assist = warning == '闪避识别-黄光' and reason is None
        # Use the configured action mapping: Space on default keyboard,
        # RB/R1 on the background pad. No preliminary dodge consumes the cue.
        result = self.ctx.switch_next() if assist else self.ctx.dodge()
        record_event('realtime_response', warning=warning, response='支援弹刀' if assist else '闪避',
                     input_allowed=result is not False, fallback_reason=reason,
                     captured_at=recorder.last_record_time)
        if result is False or self._stop.wait(.12):
            return
        if self._fresh('按键可用-普通攻击') is not None:
            self.ctx.normal_attack()

    def stop(self):
        self._stop.set()
