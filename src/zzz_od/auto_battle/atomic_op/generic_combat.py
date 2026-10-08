"""Standard controls for a character without a usable operation template."""
import threading
import time

from onedragon.base.conditional_operation.atomic_op import AtomicOp
from zzz_od.auto_battle.auto_battle_state import BattleStateEnum


class AtomicGenericCombat(AtomicOp):
    OP_NAME = '通用战斗'

    def __init__(self, ctx):
        super().__init__(self.OP_NAME)
        self.ctx = ctx
        self._stop = threading.Event()

    def _recent(self, state, age):
        recorder = self.ctx.state_record_service.get_state_recorder(state)
        return (recorder is not None and recorder.last_record_time > 0
                and 0 <= time.time() - recorder.last_record_time <= age)

    def execute(self):
        self._stop.clear()
        if not self._recent(BattleStateEnum.STATUS_NORMAL_ATTACK_READY.value, .25):
            return
        if (self.ctx.auto_ultimate_enabled
                and self._recent(BattleStateEnum.STATUS_ULTIMATE_READY.value, .5)
                and not self._recent(BattleStateEnum.BTN_ULTIMATE.value, 3)):
            self.ctx.ultimate()
            delay = .2
        elif (self._recent(BattleStateEnum.STATUS_SPECIAL_READY.value, .5)
              and not self._recent(BattleStateEnum.BTN_SWITCH_SPECIAL_ATTACK.value, .8)):
            self.ctx.special_attack()
            delay = .2
        else:
            self.ctx.normal_attack()
            delay = .12
        self._stop.wait(delay)

    def stop(self):
        self._stop.set()
