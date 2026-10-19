"""Render window captures into an offscreen DC; never draw into the game DC."""
import ctypes
import functools
import sys
import threading
import time

import numpy as np


def blank_frame(frame):
    if frame is None or frame.size == 0:
        return True
    pixels = frame[::16, ::16, :3]
    return bool(np.mean(np.max(pixels, axis=2) > 3) < .005)


def install_capture_compat():
    import win32gui
    import win32ui
    from ok.device.capture_methods import bitblt, bitblt_utils

    install_window_position_compat()
    install_device_selection_compat()
    install_windows_graphics_compat()
    install_wgc_blank_frame_guard()
    install_wgc_close_outside_lock()

    if getattr(bitblt_utils.capture_by_bitblt, '_zzz_offscreen', False) is True:
        return
    original = bitblt_utils.capture_by_bitblt
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.PrintWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
    user32.PrintWindow.restype = ctypes.c_int

    def render(context, hwnd, width, height, x, y):
        rect = win32gui.GetWindowRect(hwnd)
        render_width = max(width + x, rect[2] - rect[0])
        render_height = max(height + y, rect[3] - rect[1])
        if (context.last_hwnd, context.last_width, context.last_height) != (hwnd, render_width, render_height):
            bitblt_utils.clean_up_bitblt(context)
            context.last_hwnd = hwnd
            context.window_dc = win32gui.GetWindowDC(hwnd)
            context.dc_object = win32ui.CreateDCFromHandle(context.window_dc)
            context.compatible_dc = context.dc_object.CreateCompatibleDC()
            context.bitmap = win32ui.CreateBitmap()
            context.bitmap.CreateCompatibleBitmap(context.dc_object, render_width, render_height)
            context.last_width, context.last_height = render_width, render_height
            context.compatible_dc.SelectObject(context.bitmap)
        # PrintWindow must write into the bitmap's memory DC. The framework wrote
        # into GetWindowDC and then copied that DC, producing black DirectX frames.
        context.compatible_dc.PatBlt((0, 0), (render_width, render_height), 0x00000042)
        if not user32.PrintWindow(hwnd, context.compatible_dc.GetSafeHdc(), bitblt_utils.PW_RENDERFULLCONTENT):
            context._zzz_capture_error = 'PrintWindow 未返回有效画面'
            return None
        frame = np.frombuffer(context.bitmap.GetBitmapBits(True), dtype=np.uint8).reshape(render_height, render_width, 4)
        return frame[y:y + height, x:x + width].copy()

    def capture(context, hwnd, width, height, x, y, render_full_content):
        if hwnd <= 0 or width <= 0 or height <= 0:
            return None
        try:
            frame = render(context, hwnd, width, height, x, y) if render_full_content else original(
                context, hwnd, width, height, x, y, False)
            if not render_full_content and blank_frame(frame):
                frame = render(context, hwnd, width, height, x, y)
            if blank_frame(frame):
                context._zzz_capture_error = '截图黑屏，等待有效画面；不会据此操作游戏'
                return None
            context._zzz_capture_error = ''
            return frame
        except Exception as error:
            context._zzz_capture_error = str(error)
            bitblt_utils.clean_up_bitblt(context)
            return None

    capture._zzz_offscreen = True
    bitblt_utils.capture_by_bitblt = capture
    bitblt.capture_by_bitblt = capture
    # Some framework versions export the function through this compatibility module.
    import ok.device.capture as exported
    exported.capture_by_bitblt = capture


def install_device_selection_compat():
    """Keep a configured game selected when Windows recreates its handle."""
    from ok.device.DeviceManager import DeviceManager
    original = DeviceManager._replace_pc_devices
    if getattr(original, '_zzz_selection_rebind', False) is True:
        return

    def replace(manager, devices):
        original(manager, devices)
        preferred = manager.config.get('preferred', '')
        # An explicit executable limits discovery to this game. Do not select
        # arbitrary desktop windows or replace an Android/browser selection.
        configured = manager.windows_capture_config or {}
        if (preferred in devices or not configured.get('exe')
                or not (preferred == 'pc' or str(preferred).startswith('pc_'))
                or len(devices) != 1):
            return
        device = next(iter(devices.values()))
        if (device.get('device') != 'windows' or not device.get('connected')
                or not device.get('real_hwnd')):
            return
        manager.config['selected_hwnd'] = device['real_hwnd']
        manager.config['preferred'] = device['imei']

    replace._zzz_selection_rebind = True
    DeviceManager._replace_pc_devices = replace


def refresh_restarted_window(window):
    """Schedule discovery when the bound game restarts, without polling devices."""
    manager = getattr(window, 'device_manager', None)
    configured = getattr(manager, 'windows_capture_config', None) or {}
    if not configured.get('exe') or not hasattr(manager, 'get_preferred_device'):
        return
    selected = manager.get_preferred_device()
    hwnd = getattr(window, 'hwnd', 0)
    if (not selected or selected.get('device') != 'windows' or not hwnd
            or hwnd == selected.get('real_hwnd')
            or getattr(window, 'width', 0) < 1280 or getattr(window, 'height', 0) < 720):
        return
    import win32gui
    previous = selected.get('real_hwnd', 0)
    if previous and win32gui.IsWindow(previous):
        return
    now = time.monotonic()
    if now - getattr(window, '_zzz_rebind_refresh_at', float('-inf')) < 1:
        return
    window._zzz_rebind_refresh_at = now
    manager.refresh()


def install_windows_graphics_compat():
    """Windows 10 supports capture even though border suppression needs 20348."""
    from ok.util import window
    original = window.windows_graphics_available
    if getattr(original, '_zzz_wgc_windows10', False) is True:
        return

    def available():
        if window.WINDOWS_BUILD_NUMBER >= 20348:
            return original()
        if window.WINDOWS_BUILD_NUMBER < 19041:
            return False
        try:
            from ok.rotypes.roapi import GetActivationFactory
            from ok.rotypes.Windows.Graphics.Capture import IGraphicsCaptureItemInterop
            GetActivationFactory('Windows.Graphics.Capture.GraphicsCaptureItem').astype(IGraphicsCaptureItemInterop)
            return True
        except Exception:
            return False

    available._zzz_wgc_windows10 = True
    # Framework modules import this function by value. Replace only references
    # to that exact function, including modules already loaded before Globals.
    for name, module in tuple(sys.modules.items()):
        if name == 'ok' or name.startswith('ok.'):
            if vars(module).get('windows_graphics_available') is original:
                module.windows_graphics_available = available


def install_wgc_blank_frame_guard():
    from ok.device.capture_methods.windows_graphics import WindowsGraphicsCaptureMethod
    original = WindowsGraphicsCaptureMethod.do_get_frame
    if getattr(original, '_zzz_blank_guard', False) is True:
        return

    @functools.wraps(original)
    def capture(method):
        frame = original(method)
        if blank_frame(frame):
            method._zzz_capture_error = 'WGC截图黑屏，等待有效画面；不会据此操作游戏'
            return None
        method._zzz_capture_error = ''
        return frame

    capture._zzz_blank_guard = True
    WindowsGraphicsCaptureMethod.do_get_frame = capture


def install_wgc_close_outside_lock():
    """Release WGC's capture objects only after dropping the capture lock.

    The framework releases them while holding the lock that FrameArrived also takes. A first frame
    arriving during that close blocks its system thread on the lock, and the final texture Release
    then never returns (2026-10-19: the device thread hung there, so a restarted game was never
    rebound and trigger tasks had no frames). Detach under the lock, release after it: a blocked
    callback then finds no frame pool and returns.
    """
    from ok.device.capture_methods import windows_graphics as module
    original = module.WindowsGraphicsCaptureMethod.close
    if getattr(original, '_zzz_release_outside_lock', False) is True:
        return

    def release(action, name):
        try:
            action()
        except Exception as error:
            module.logger.warning(f'destroy windows capture: {name} failed: {error}')

    def close(method):
        with method.lock:
            method._frame_cancel_generation += 1
            method.frame_requested.clear()
            method.frame_event.set()
        # get_frame_lock still keeps composite_hwnds() off the BitBlt contexts released below.
        with method.get_frame_lock:
            with method.lock:
                module.logger.info('destroy windows capture')
                method.frame_requested.clear()
                method.frame_event.set()
                pool, session = method.frame_pool, method.session
                objects = (('cputex', method.cputex), ('immediatedc', method.immediatedc),
                           ('dxdevice', method.dxdevice), ('rtdevice', method.rtdevice))
                contexts = list(method.contexts.values())
                method.frame_pool = method.session = method.item = None
                method.rtdevice = method.dxdevice = method.immediatedc = method.cputex = None
                method.contexts.clear()
                method.capture_hwnd = 0
                method.capture_target_signature = None
            if pool is not None:
                release(pool.Close, 'frame pool')
            if session is not None:
                release(session.Close, 'session')
            for name, value in objects:
                if value:
                    release(value.Release, name)
            for context in contexts:
                release(functools.partial(module.clean_up_bitblt, context), 'bitblt context')

    close._zzz_release_outside_lock = True
    module.WindowsGraphicsCaptureMethod.close = close


def install_window_position_compat():
    """Window-DC capture does not require the client to fit a desktop monitor.

    Keep the framework's on-screen check for desktop captures. Use thread-local
    context so only the bound window's own size update gets this exemption.
    """
    import win32gui
    from ok.device.capture_methods import hwnd_window
    from ok.device.capture_methods.bitblt import BitBltCaptureMethod

    original_update = hwnd_window.HwndWindow.do_update_window_size
    if getattr(original_update, '_zzz_background_position', False) is True:
        return
    original_check = hwnd_window.check_pos
    current = threading.local()

    def check_position(x, y, width, height, monitors_bounds):
        on_screen = original_check(x, y, width, height, monitors_bounds)
        window = getattr(current, 'window', None)
        if window is None or not isinstance(window.device_manager.capture_method, BitBltCaptureMethod):
            return on_screen
        hwnd = window.hwnd
        try:
            available = (width > 0 and height > 0 and win32gui.IsWindow(hwnd)
                         and not win32gui.IsIconic(hwnd))
        except Exception:
            available = False
        if available and not on_screen and not getattr(window, '_zzz_background_position_reported', False):
            hwnd_window.logger.info('后台窗口捕获继续运行：窗口未最小化，尺寸或位置超出屏幕边界')
        window._zzz_background_position_reported = available and not on_screen
        return bool(available)

    @functools.wraps(original_update)
    def update_window_size(window, *args, **kwargs):
        previous = getattr(current, 'window', None)
        current.window = window
        try:
            result = original_update(window, *args, **kwargs)
            refresh_restarted_window(window)
            return result
        finally:
            current.window = previous

    update_window_size._zzz_background_position = True
    hwnd_window.check_pos = check_position
    hwnd_window.HwndWindow.do_update_window_size = update_window_size
