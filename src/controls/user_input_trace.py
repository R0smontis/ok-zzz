"""Observe physical game keyboard/mouse events without suppressing input."""
import time
import threading


KEY_NAMES = {0x08: 'Backspace', 0x09: 'Tab', 0x0D: 'Enter', 0x10: 'Shift', 0x11: 'Ctrl',
             0x12: 'Alt', 0x1B: 'Escape', 0x20: 'Space', 0x25: 'Left', 0x26: 'Up',
             0x27: 'Right', 0x28: 'Down', 0xA0: 'LeftShift', 0xA1: 'RightShift',
             0xA2: 'LeftCtrl', 0xA3: 'RightCtrl', 0xA4: 'LeftAlt', 0xA5: 'RightAlt'}


def key_name(vk):
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return chr(vk)
    if 0x70 <= vk <= 0x87:
        return f'F{vk-0x6F}'
    return KEY_NAMES.get(vk, f'VK_{vk:02X}')


class GameInputTrace:
    def __init__(self, hwnd_provider, record, *, scope_reader=None, enabled_provider=None):
        self.hwnd_provider = hwnd_provider
        self.record = record
        self.scope_reader = scope_reader or self._read_scope
        self.enabled_provider = enabled_provider
        self._lock = threading.RLock()
        self.listeners = []
        self.held_keys = set()
        self.last_move = {False: 0, True: 0}
        self.last_scope = None
        self.running = False

    def _enabled(self):
        try:
            enabled = self.running and (self.enabled_provider is None or self.enabled_provider())
            if not enabled:
                self.held_keys.clear()
                self.last_scope = None
            return enabled
        except Exception:
            return False

    @staticmethod
    def _read_scope(hwnd, point=None):
        import win32gui
        if not hwnd or win32gui.GetForegroundWindow() != hwnd or not win32gui.IsWindow(hwnd):
            return None
        if point is None:
            return {'hwnd': hwnd}
        x, y = win32gui.ScreenToClient(hwnd, point)
        _, _, width, height = win32gui.GetClientRect(hwnd)
        if width <= 0 or height <= 0 or not (0 <= x < width and 0 <= y < height):
            return None
        return {'hwnd': hwnd, 'x': x, 'y': y, 'game_x': round(x*1920/width, 2),
                'game_y': round(y*1080/height, 2)}

    def _scope(self, point=None):
        try:
            hwnd = self.hwnd_provider()
            # Focus changes clear held-key bookkeeping without recording other apps' keys.
            focused = self.scope_reader(hwnd)
            current = hwnd if focused else None
            if current != self.last_scope:
                self.record('user_input_scope', hwnd=current, active=focused is not None,
                            previous=self.last_scope, previously_held=[key_name(k) for k in sorted(self.held_keys)])
                self.last_scope = current
                self.held_keys.clear()
            if not focused:
                return None
            return focused if point is None else self.scope_reader(hwnd, point)
        except Exception:
            return None

    def keyboard_filter(self, msg, data):
        with self._lock:
            return self._keyboard_filter(msg, data)

    def _keyboard_filter(self, msg, data):
        try:
            if not self._enabled():
                return False
            scope = self._scope()
            if scope is None or msg not in (0x100, 0x101, 0x104, 0x105):
                return False
            injected = bool(int(data.flags) & 0x12)
            vk = int(data.vkCode)
            down = msg in (0x100, 0x104)
            action = 'down' if down else 'up'
            if not injected:
                if down:
                    action = 'repeat' if vk in self.held_keys else 'down'
                    self.held_keys.add(vk)
                else:
                    self.held_keys.discard(vk)
            self.record('observed_injected_input' if injected else 'user_input',
                        device='keyboard', action=action, key=key_name(vk), vk=vk,
                        scan_code=int(data.scanCode), source='injected' if injected else 'user', **scope)
        except Exception:
            pass
        # Filtering only disables our high-level callbacks. suppress=False leaves game input intact.
        return False

    def mouse_filter(self, msg, data):
        with self._lock:
            return self._mouse_filter(msg, data)

    def _mouse_filter(self, msg, data):
        try:
            if not self._enabled():
                return False
            scope = self._scope((int(data.pt.x), int(data.pt.y)))
            if scope is None:
                return False
            injected = bool(int(data.flags) & 3)
            event = {'device': 'mouse', 'source': 'injected' if injected else 'user', **scope}
            if msg == 0x200:
                now = time.monotonic()
                if now - self.last_move[injected] < 0.05:
                    return False
                self.last_move[injected] = now
                event['action'] = 'move'
            elif msg in (0x201, 0x202, 0x204, 0x205, 0x207, 0x208, 0x20B, 0x20C):
                event['action'] = 'down' if msg in (0x201, 0x204, 0x207, 0x20B) else 'up'
                event['button'] = {0x201: 'left', 0x202: 'left', 0x204: 'right', 0x205: 'right',
                                   0x207: 'middle', 0x208: 'middle'}.get(msg)
                if event['button'] is None:
                    event['button'] = 'x1' if int(data.mouseData) >> 16 == 1 else 'x2'
            elif msg in (0x20A, 0x20E):
                event['action'] = 'scroll'
                delta = (int(data.mouseData) >> 16) & 0xFFFF
                delta = delta-0x10000 if delta >= 0x8000 else delta
                event['dx' if msg == 0x20E else 'dy'] = delta/120
            else:
                return False
            self.record('observed_injected_input' if injected else 'user_input', **event)
        except Exception:
            pass
        return False

    def start(self):
        from pynput.keyboard import Listener as KeyboardListener
        from pynput.mouse import Listener as MouseListener
        self.running = True
        try:
            for cls, callback in ((KeyboardListener, self.keyboard_filter), (MouseListener, self.mouse_filter)):
                listener = cls(win32_event_filter=callback, suppress=False)
                self.listeners.append(listener)
                listener.start()
        except Exception:
            self.stop()
            raise

    def stop(self):
        self.running = False
        for listener in self.listeners:
            listener.stop()
        for listener in self.listeners:
            if listener.is_alive():
                listener.join(timeout=1)
        self.listeners.clear()
