# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: one_dragon/base/controller/pc_button/pc_button_utils.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from functools import lru_cache
from pynput import keyboard, mouse
from typing import Union

# Importing vgamepad opens ViGEmBus immediately; probe lazily so the bus is only touched
# once a gamepad mode is actually used.
_VGAMEPAD_INSTALLED: bool | None = None


@lru_cache
def is_mouse_button(key: str) -> bool:
    """
    是否鼠标按键
    :param key:
    :return:
    """
    return key.startswith('mouse_')


@lru_cache
def is_xbox_button(key: str) -> bool:
    """
    是否xbox按键
    :param key:
    :return:
    """
    return key.startswith('xbox_')


@lru_cache
def is_ds4_button(key: str) -> bool:
    """
    是否ds4按键
    :param key:
    :return:
    """
    return key.startswith('ds4_')


@lru_cache
def get_button(key: str):
    if is_mouse_button(key):
        return get_mouse_button(key)
    else:
        return get_keyboard_button(key)


@lru_cache
def get_mouse_button(key: str) -> mouse.Button:
    real_key = key[6:]  # 取mouse_之后的部分
    return mouse.Button[real_key]


@lru_cache
def get_keyboard_button(key: str) -> Union[keyboard.KeyCode, keyboard.Key, str]:
    # 处理小键盘数字键: numpad_0 到 numpad_9
    if key.startswith('numpad_') and len(key) == 8 and key[-1].isdigit():
        vk_code = 96 + int(key[-1])  # 小键盘0的虚拟键码是96
        return keyboard.KeyCode.from_vk(vk_code)

    if key in keyboard.Key.__members__:
        return keyboard.Key[key]
    elif len(key) == 1:
        return keyboard.KeyCode.from_char(key)
    else:
        return key


@lru_cache
def is_vgamepad_installed() -> bool:
    """
    是否安装了虚拟手柄库
    :return:
    """
    global _VGAMEPAD_INSTALLED
    if _VGAMEPAD_INSTALLED is None:
        try:
            import vgamepad  # noqa: F401
            _VGAMEPAD_INSTALLED = True
        except Exception:
            _VGAMEPAD_INSTALLED = False
    return _VGAMEPAD_INSTALLED
