"""Recover from a capture stream that keeps returning the very same picture.

A Windows Graphics Capture session can go stale: it keeps handing out frames that
carry an old picture while the game runs on (seen live: the desktop showed a page the
capture never did, and a fresh session showed it at once). A running game never
presents a pixel-identical picture for long — menus pulse, the world animates — so
after FROZEN_SECONDS of identical frames the capture session is restarted once; only
when the fresh session still shows the same picture is the game itself suspect.
"""
import time

from ok import Logger

logger = Logger.get_logger(__name__)

RESTART, STUCK = 'restart', 'stuck'


class FrozenCaptureWatch:
    FROZEN_SECONDS = 15

    def __init__(self):
        self.signature = None
        self.since = 0.
        self.stage = None

    def observe(self, frame, now=None):
        """RESTART or STUCK once per frozen episode, otherwise None."""
        if not hasattr(frame, 'tobytes'):
            return None
        now = time.time() if now is None else now
        signature = hash(frame[::16, ::16].tobytes())
        if signature != self.signature:
            self.signature, self.since, self.stage = signature, now, None
            return None
        if self.stage == STUCK or now - self.since < self.FROZEN_SECONDS:
            return None
        self.stage = STUCK if self.stage == RESTART else RESTART
        self.since = now
        return self.stage


def handle_frozen_capture(watch, frame, method, now=None):
    """Restart a stale WGC session; report a picture that a fresh session confirms."""
    stage = watch.observe(frame, now)
    if stage == RESTART and getattr(method, 'name', '') == 'Windows Graphics Capture':
        logger.warning(f'游戏画面已 {watch.FROZEN_SECONDS} 秒完全没有变化，重建截图会话（WGC 会话可能已失效）')
        method.close()  # the next get_frame starts a new session
    elif stage is not None:
        logger.warning('游戏画面持续完全没有变化：游戏可能已卡住或暂停渲染，手柄与点击都不会生效。'
                       '请检查游戏窗口，必要时重启游戏')
    return stage
