# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: one_dragon/base/controller/pc_button/keyboard_mouse_controller.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
import time
import threading

from pynput import keyboard, mouse

from onedragon.base.controller.pc_button import pc_button_utils
from onedragon.base.controller.pc_button.pc_button_controller import PcButtonController


class KeyboardMouseController(PcButtonController):

    def __init__(self):
        PcButtonController.__init__(self)
        self.keyboard = keyboard.Controller()
        self.mouse = mouse.Controller()
        self._pressed_keys: set[str] = set()  # 当前按下的键
        self._key_lock = threading.RLock()
        self._release_events: dict[str, threading.Event] = {}

    def tap(self, key: str) -> None:
        """
        按一次按键
        :param key: 按键
        :return:
        """
        if pc_button_utils.is_mouse_button(key):
            self.mouse.click(pc_button_utils.get_mouse_button(key))
        else:
            self.keyboard.tap(pc_button_utils.get_keyboard_button(key))

    def press(self, key: str, press_time: float | None = None) -> None:
        """
        :param key: 按键
        :param press_time: 持续按键时间
        :return:
        """
        if press_time is not None and press_time < 0:
            raise ValueError('press_time must be non-negative')
        with self._key_lock:
            is_mouse = pc_button_utils.is_mouse_button(key)
            real_key = pc_button_utils.get_mouse_button(key) if is_mouse else pc_button_utils.get_keyboard_button(key)
            device = self.mouse if is_mouse else self.keyboard
            device.press(real_key)
            previous = self._release_events.get(key)
            if previous is not None:
                previous.set()
            released = threading.Event()
            self._release_events[key] = released
            self._pressed_keys.add(key)
        if press_time is not None:
            try:
                released.wait(press_time)
            finally:
                with self._key_lock:
                    if self._release_events.get(key) is released:
                        self.release(key)

    def release(self, key: str) -> None:
        with self._key_lock:
            if key not in self._pressed_keys:
                return
            is_mouse = pc_button_utils.is_mouse_button(key)
            if is_mouse:
                self.mouse.release(pc_button_utils.get_mouse_button(key))
            else:
                self.keyboard.release(pc_button_utils.get_keyboard_button(key))
            self._pressed_keys.discard(key)
            released = self._release_events.pop(key)
            released.set()

    def reset(self) -> None:
        with self._key_lock:
            for key in list(self._pressed_keys):
                self.release(key)


if __name__ == '__main__':
    _c = KeyboardMouseController()
    t1 = time.time()
    _c.press('a')
    _c.release('a')
    print('%.4f' % (time.time() - t1))
