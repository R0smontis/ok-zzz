import time
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from src.controls.capture_compat import blank_frame, install_capture_compat, install_window_position_compat


@pytest.mark.parametrize('build,expected', [(18362, False), (19041, True), (19045, True), (20348, True)])
def test_wgc_does_not_require_optional_border_suppression(monkeypatch, build, expected):
    from ok.util import window
    from ok.device.capture_methods import update
    from ok.rotypes import roapi
    from src.controls.capture_compat import install_windows_graphics_compat
    original = Mock(return_value=True)
    monkeypatch.setattr(window, 'windows_graphics_available', original)
    monkeypatch.setattr(update, 'windows_graphics_available', original)
    monkeypatch.setattr(window, 'WINDOWS_BUILD_NUMBER', build)
    factory = Mock()
    monkeypatch.setattr(roapi, 'GetActivationFactory', factory)
    import ok.rotypes.Windows.Graphics.Capture  # noqa: F401 (Import may initialize runtime factories.)
    factory.reset_mock()
    install_windows_graphics_compat()
    assert update.windows_graphics_available() is expected
    assert window.WGC_NO_BORDER_MIN_BUILD == 20348
    assert factory.call_count == (1 if 19041 <= build < 20348 else 0)


@pytest.fixture
def capture(monkeypatch):
    import ctypes
    import win32gui
    import win32ui
    import ok.device.capture as exported
    from ok.device.capture_methods import bitblt, bitblt_utils
    frame = np.full((360, 640, 4), 100, np.uint8)
    bitmap = Mock()
    bitmap.GetBitmapBits.side_effect = lambda _: frame.tobytes()
    memory = Mock()
    memory.GetSafeHdc.return_value = 200
    source = Mock()
    source.GetSafeHdc.return_value = 100
    source.CreateCompatibleDC.return_value = memory
    native = SimpleNamespace(PrintWindow=Mock(return_value=1))
    original = Mock(return_value=frame.copy())
    monkeypatch.setattr(ctypes, 'WinDLL', lambda *a, **k: native)
    monkeypatch.setattr(win32gui, 'GetWindowRect', lambda _: (0, 0, 640, 360))
    monkeypatch.setattr(win32gui, 'GetWindowDC', lambda _: 12)
    monkeypatch.setattr(win32ui, 'CreateDCFromHandle', lambda _: source)
    monkeypatch.setattr(win32ui, 'CreateBitmap', lambda: bitmap)
    monkeypatch.setattr(bitblt_utils, 'clean_up_bitblt', Mock())
    for module in (bitblt_utils, bitblt, exported):
        monkeypatch.setattr(module, 'capture_by_bitblt', original)
    install_capture_compat()
    ctx = SimpleNamespace(last_hwnd=0, last_width=0, last_height=0)
    return SimpleNamespace(call=bitblt.capture_by_bitblt, ctx=ctx, native=native,
                           original=original, memory=memory, frame=frame)


def test_full_capture_renders_directly_into_memory_bitmap(capture):
    result = capture.call(capture.ctx, 7, 600, 330, 20, 15, True)
    capture.native.PrintWindow.assert_called_once_with(7, 200, 2)
    capture.memory.BitBlt.assert_not_called()
    capture.original.assert_not_called()
    assert result.shape == (330, 600, 4)
    assert result.mean() == 100
    assert result.flags.owndata


def test_black_bitblt_retries_offscreen_without_foreground_input(capture):
    capture.original.return_value = np.zeros_like(capture.frame)
    assert capture.call(capture.ctx, 7, 640, 360, 0, 0, False) is not None
    capture.native.PrintWindow.assert_called_once_with(7, 200, 2)


def test_regular_bitblt_does_not_change_capture_path(capture):
    assert capture.call(capture.ctx, 7, 640, 360, 0, 0, False) is not None
    capture.native.PrintWindow.assert_not_called()


def test_failed_or_black_render_is_not_a_usable_game_frame(capture):
    capture.native.PrintWindow.return_value = 0
    assert capture.call(capture.ctx, 7, 640, 360, 0, 0, True) is None
    capture.native.PrintWindow.return_value = 1
    capture.frame[:] = 0
    assert capture.call(capture.ctx, 7, 640, 360, 0, 0, True) is None
    assert '黑屏' in capture.ctx._zzz_capture_error


def test_blank_detection_keeps_dark_but_visible_gameplay():
    frame = np.zeros((1080, 1920, 3), np.uint8)
    assert blank_frame(frame)
    frame[300:400, 600:900] = 12
    assert not blank_frame(frame)


def test_wgc_black_frames_are_rejected_before_task_and_live_observers(monkeypatch):
    from ok.device.capture_methods.windows_graphics import WindowsGraphicsCaptureMethod as WGC
    from src.controls.capture_compat import install_wgc_blank_frame_guard
    frame = np.zeros((720,1280,3), np.uint8)
    original = Mock(return_value=frame)
    monkeypatch.setattr(WGC, 'do_get_frame', original)
    install_wgc_blank_frame_guard()
    method = SimpleNamespace()
    assert WGC.do_get_frame(method) is None
    assert '黑屏' in method._zzz_capture_error
    frame[50:150,50:150] = 100
    assert WGC.do_get_frame(method) is frame
    assert not method._zzz_capture_error


@pytest.fixture
def position_check(monkeypatch):
    import win32gui
    from ok.device.capture_methods import hwnd_window, bitblt
    # Exercise the same call boundary as the framework's window update.
    def update(window):
        return hwnd_window.check_pos(*window.geometry, [(0, 0, 2560, 1440)])
    monkeypatch.setattr(hwnd_window.HwndWindow, 'do_update_window_size', update)
    monkeypatch.setattr(hwnd_window, 'check_pos', lambda x, y, w, h, bounds:
                        w > 0 and h > 0 and x >= 0 and y >= 0 and x + w <= 2560 and y + h <= 1440)
    monkeypatch.setattr(win32gui, 'IsWindow', lambda hwnd: hwnd == 7)
    monkeypatch.setattr(win32gui, 'IsIconic', lambda hwnd: hwnd == 8)
    install_window_position_compat()
    window = SimpleNamespace(hwnd=7, geometry=(0, 0, 3200, 1440),
                             device_manager=SimpleNamespace(capture_method=object.__new__(bitblt.BitBltCaptureMethod)))
    return hwnd_window, bitblt, window


@pytest.mark.parametrize('geometry', [(0, 0, 3200, 1440), (-800, 0, 1920, 1080), (1800, 600, 1920, 1080)])
def test_background_capture_keeps_running_outside_monitor_bounds(position_check, geometry):
    module, _, window = position_check
    window.geometry = geometry
    assert module.HwndWindow.do_update_window_size(window) is True
    # The exemption must not leak into unrelated checks on the same thread.
    assert module.check_pos(*geometry, []) is False


@pytest.mark.parametrize('hwnd,geometry', [(0, (0, 0, 1920, 1080)), (8, (0, 0, 1920, 1080)),
                                          (7, (0, 0, 0, 1080)), (7, (0, 0, 1920, 0))])
def test_background_capture_rejects_missing_minimized_or_empty_window(position_check, monkeypatch, hwnd, geometry):
    import win32gui
    module, _, window = position_check
    monkeypatch.setattr(win32gui, 'IsWindow', lambda value: value in (7, 8))
    window.hwnd, window.geometry = hwnd, geometry
    assert module.HwndWindow.do_update_window_size(window) is False


def test_desktop_capture_still_requires_on_screen_window(position_check):
    module, bitblt, window = position_check
    window.device_manager.capture_method = object.__new__(bitblt.ForegroundBitBltCaptureMethod)
    assert module.HwndWindow.do_update_window_size(window) is False
    window.geometry = (0, 0, 1920, 1080)
    assert module.HwndWindow.do_update_window_size(window) is True


def test_position_patch_is_idempotent(position_check):
    module, _, _ = position_check
    update, check = module.HwndWindow.do_update_window_size, module.check_pos
    install_window_position_compat()
    assert module.HwndWindow.do_update_window_size is update
    assert module.check_pos is check


def wgc_closing_with_pending_frame(monkeypatch):
    """A WGC capture whose texture Release waits for a FrameArrived callback that is blocked on the lock."""
    import threading
    from ok.device.capture_methods import windows_graphics as module
    method = object.__new__(module.WindowsGraphicsCaptureMethod)
    method.lock, method.get_frame_lock = threading.RLock(), threading.RLock()
    method._frame_cancel_generation = 0
    method.frame_requested, method.frame_event = threading.Event(), threading.Event()
    method.contexts, method.item, method.session = {}, object(), None
    method.capture_hwnd, method.capture_target_signature = 1, ('sig',)
    method.frame_pool = SimpleNamespace(Close=Mock())
    method.immediatedc = method.dxdevice = method.rtdevice = None
    seen, done = [], threading.Event()

    def frame_arrived():
        with method.lock:
            seen.append(method.frame_pool)
        done.set()

    def destroy_message(message, *args, **kwargs):
        if message == 'destroy windows capture':  # Logged while close() holds the lock.
            threading.Thread(target=frame_arrived, daemon=True).start()
            time.sleep(.05)

    released = []
    def release():  # D3D finishes the in-flight callback before the last texture goes away.
        released.append(done.wait(1))
    method.cputex = SimpleNamespace(Release=release)
    monkeypatch.setattr(module.logger, 'info', destroy_message)
    return module, method, seen, released


def test_wgc_close_releases_textures_after_a_pending_frame_callback(monkeypatch):
    from src.controls.capture_compat import install_wgc_close_outside_lock
    module, method, seen, released = wgc_closing_with_pending_frame(monkeypatch)
    monkeypatch.setattr(module.WindowsGraphicsCaptureMethod, 'close', module.WindowsGraphicsCaptureMethod.close)
    install_wgc_close_outside_lock()
    module.WindowsGraphicsCaptureMethod.close(method)
    assert released == [True]  # The original close released inside the lock and hung here.
    assert seen == [None]  # The late callback finds the pool detached and returns.
    assert method.cputex is None and method.capture_hwnd == 0 and method.capture_target_signature is None


def test_wgc_resized_target_is_closed_without_holding_the_capture_lock(monkeypatch):
    from src.controls.capture_compat import install_wgc_close_outside_lock
    module, method, seen, released = wgc_closing_with_pending_frame(monkeypatch)
    method._hwnd_window = SimpleNamespace(capture_target_signature=('resized',))
    restarted = []

    def framework_start_or_stop(self, *args, **kwargs):  # Holds the lock, as the framework does.
        with self.lock:
            if self.frame_pool is not None and self.capture_target_signature != ('resized',):
                self.close()
            restarted.append(self.frame_pool is None)
            return True

    monkeypatch.setattr(module.WindowsGraphicsCaptureMethod, 'close', module.WindowsGraphicsCaptureMethod.close)
    monkeypatch.setattr(module.WindowsGraphicsCaptureMethod, 'start_or_stop', framework_start_or_stop)
    install_wgc_close_outside_lock()
    assert module.WindowsGraphicsCaptureMethod.start_or_stop(method) is True
    assert released == [True]  # Closing inside start_or_stop's lock hung on the texture Release.
    assert seen == [None] and restarted == [True]


def test_wgc_close_patch_is_idempotent(monkeypatch):
    from ok.device.capture_methods import windows_graphics as module
    from src.controls.capture_compat import install_wgc_close_outside_lock
    monkeypatch.setattr(module.WindowsGraphicsCaptureMethod, 'close', module.WindowsGraphicsCaptureMethod.close)
    install_wgc_close_outside_lock()
    patched = module.WindowsGraphicsCaptureMethod.close
    install_wgc_close_outside_lock()
    assert module.WindowsGraphicsCaptureMethod.close is patched


def test_wgc_resize_releases_callback_frame_before_rebuilding_and_delivers_next_frame(monkeypatch):
    import threading
    from ok.device.capture_methods import windows_graphics as module
    from src.controls.capture_compat import install_wgc_close_outside_lock

    wgc = module.WindowsGraphicsCaptureMethod
    for name in ('close', 'start_or_stop', 'reset_framepool'):
        monkeypatch.setattr(wgc, name, getattr(wgc, name))
    method = object.__new__(wgc)
    method.lock, method.get_frame_lock = threading.RLock(), threading.RLock()
    method.exit_event = threading.Event()
    method.frame_requested, method.frame_event = threading.Event(), threading.Event()
    method._frame_cancel_generation = 0
    method.capture_hwnd, method.capture_target_signature = 1, ('target',)
    method._hwnd_window = SimpleNamespace(capture_target_signature=('target',))
    method.contexts = {}
    method.last_frame, method.last_frame_time = None, time.time()
    method.last_size = SimpleNamespace(Width=320, Height=240)
    method.cputex = method.session = method.item = None
    method.dxdevice = SimpleNamespace(Release=Mock())
    method.immediatedc = SimpleNamespace(Release=Mock())
    method.rtdevice = SimpleNamespace(Release=Mock())
    native_frame_released = threading.Event()
    expected = np.full((360, 640, 4), 61, np.uint8)
    old_frame = SimpleNamespace(ContentSize=SimpleNamespace(Width=640, Height=360),
                                Close=native_frame_released.set)
    new_frame = SimpleNamespace(ContentSize=SimpleNamespace(Width=640, Height=360), Close=Mock())
    old_pool = SimpleNamespace(TryGetNextFrame=lambda: old_frame,
                               Recreate=Mock(side_effect=AssertionError('callback COM recreation')))
    def close_pool():
        assert native_frame_released.is_set(), 'a checked-out native frame must be released first'
    old_pool.Close = Mock(side_effect=close_pool)
    method.frame_pool = old_pool
    starts = []
    recreated = []
    def recreate(device, pixel_format, count, size):
        assert native_frame_released.is_set()
        recreated.append((threading.get_ident(), size.Width, size.Height))
    def start(self, *args, **kwargs):
        if self.frame_pool is None:
            starts.append(threading.get_ident())
            self.frame_pool = SimpleNamespace(TryGetNextFrame=lambda: new_frame, Recreate=recreate)
            self.last_size = SimpleNamespace(Width=320, Height=240)  # DPI-scaled Item.Size differs.
            self.capture_target_signature = ('target',)
        return True
    monkeypatch.setattr(wgc, 'start_or_stop', start)
    original_convert = wgc.convert_dx_frame
    method.convert_dx_frame = lambda frame: (original_convert(method, frame)
                                             if frame is old_frame else expected)
    method.crop_image = lambda frame: frame
    monkeypatch.setattr(module, 'composite_hwnds', lambda frame, *args: frame)
    monkeypatch.setattr(module, 'WGC_FRAME_WAIT_TIMEOUT', 1)
    callback_errors = Mock()
    monkeypatch.setattr(module.logger, 'error', callback_errors)
    install_wgc_close_outside_lock()

    def arrive():
        for _ in range(2):
            if not method.frame_requested.wait(2):
                return
            method.frame_arrived_callback()
    worker = threading.Thread(target=arrive, daemon=True)
    worker.start()
    try:
        assert method.do_get_frame() is None  # Resize cancels, never publishes an old-sized frame.
        assert method.do_get_frame() is expected
    finally:
        worker.join(timeout=3)
    assert not worker.is_alive()
    assert starts == [threading.get_ident()]  # Rebuild runs on the requester, not the system callback.
    assert recreated == [(threading.get_ident(), 640, 360)]
    assert (method.last_size.Width, method.last_size.Height) == (640, 360)
    old_pool.Recreate.assert_not_called()
    old_pool.Close.assert_called_once()
    new_frame.Close.assert_called_once()
    callback_errors.assert_not_called()


def test_wgc_native_closed_event_releases_capture_and_cancels_pending_request(monkeypatch):
    from ok.rotypes import IInspectable
    from ok.rotypes.Windows.Foundation import TypedEventHandler
    from ok.rotypes.Windows.Graphics.Capture import GraphicsCaptureItem
    from src.controls.capture_compat import install_wgc_close_outside_lock

    module, method, seen, released = wgc_closing_with_pending_frame(monkeypatch)
    monkeypatch.setattr(module.WindowsGraphicsCaptureMethod, 'close', module.WindowsGraphicsCaptureMethod.close)
    install_wgc_close_outside_lock()
    method.frame_requested.set()
    handler = TypedEventHandler(GraphicsCaptureItem, IInspectable).delegate(method.close)

    handler.Invoke(None, None)  # WinRT passes sender and event args even when unused by close().

    assert method.frame_event.is_set() and not method.frame_requested.is_set()
    assert method.frame_pool is None and method.capture_hwnd == 0
    assert seen == [None] and released == [True]
    handler.Invoke(None, None)  # A later explicit/duplicate close must remain safe.
    assert released == [True]


def test_wgc_failed_pool_rebuild_discards_the_session_and_returns_no_frame(monkeypatch, caplog):
    import threading
    from ok.device.capture_methods import windows_graphics as module
    from src.controls.capture_compat import install_wgc_close_outside_lock

    wgc = module.WindowsGraphicsCaptureMethod
    for name in ('close', 'reset_framepool'):
        monkeypatch.setattr(wgc, name, getattr(wgc, name))
    signature = (101, 640, 360)
    window = SimpleNamespace(app_exit_event=threading.Event(), exists=True,
                             capture_target_signature=signature)
    pool_closed, session_closed = [], []

    def start(method):
        assert method.frame_pool is None
        method.frame_pool = SimpleNamespace(
            Close=lambda: pool_closed.append(True),
            Recreate=Mock(side_effect=OSError('WGC Recreate rejected the new frame size')),
        )
        method.session = SimpleNamespace(Close=lambda: session_closed.append(True))
        method.capture_target_signature = signature
        return True

    monkeypatch.setattr(wgc, 'start_or_stop', start)
    install_wgc_close_outside_lock()
    method = wgc(window)
    method.reset_framepool(SimpleNamespace(Width=640, Height=360))

    assert method.get_frame() is None
    assert not method.connected()
    assert pool_closed == session_closed == [True, True]
    assert 'WGC Recreate rejected the new frame size' in caplog.text


@pytest.mark.parametrize('backend', ['Windows Graphics Capture', 'BitBlt'])
def test_shared_executor_guard_rejects_frozen_frames_and_stops_inputs(monkeypatch, backend):
    import threading
    from ok import og
    from ok.task.TaskExecutor import TaskExecutor
    from src.runtime import frozen_capture
    from src.controls.capture_compat import install_executor_frozen_capture_guard

    frame = np.full((32, 32, 3), 80, np.uint8)
    current = [frame]
    clock = [100.0]
    method = SimpleNamespace(name=backend, close=Mock())
    battle = SimpleNamespace(stop_auto_battle=Mock())
    controller = SimpleNamespace(cancel_inputs=Mock())
    context = SimpleNamespace(_auto_battle_context=battle, controller=controller)
    monkeypatch.setattr(og, 'my_app', SimpleNamespace(context_if_ready=lambda: context))
    monkeypatch.setattr(frozen_capture, 'time', SimpleNamespace(time=lambda: clock[0]))

    def base_next(executor, *args, **kwargs):
        executor._frame = current[0]
        return current[0]

    monkeypatch.setattr(TaskExecutor, 'next_frame', base_next)
    install_executor_frozen_capture_guard()
    executor = object.__new__(TaskExecutor)
    executor._frame = None
    executor.device_manager = SimpleNamespace(capture_method=method)
    executor.paused, executor.exit_event = False, threading.Event()
    stop_assistant = Mock()
    executor.trigger_tasks = [SimpleNamespace(_stop_engine=stop_assistant)]

    assert executor.next_frame() is frame
    clock[0] = 116
    assert executor.next_frame() is None
    assert executor._frame is None
    stop_assistant.assert_called_once()
    battle.stop_auto_battle.assert_called_once()
    controller.cancel_inputs.assert_called_once()

    for clock[0] in (117, 131, 200):
        assert executor.next_frame() is None
        assert executor.frame is None
    assert method.close.call_count == (1 if backend == 'Windows Graphics Capture' else 0)

    stop_assistant.reset_mock()
    battle.stop_auto_battle.reset_mock()
    controller.cancel_inputs.reset_mock()
    for clock[0], value in ((201, 81), (211, 82), (221, 83), (231, 84)):
        current[0] = np.full_like(frame, value)
        assert executor.next_frame() is current[0]
        assert executor.frame is current[0]
    stop_assistant.assert_not_called()
    battle.stop_auto_battle.assert_not_called()
    controller.cancel_inputs.assert_not_called()


@pytest.mark.parametrize('close_fails', [False, True])
def test_frozen_frame_releases_inputs_despite_cleanup_failure(monkeypatch, close_fails):
    from ok import og
    from ok.task.TaskExecutor import TaskExecutor
    from src.runtime import frozen_capture
    from src.controls.capture_compat import install_executor_frozen_capture_guard

    frame = np.full((32, 32, 3), 80, np.uint8)
    clock = [100.0]
    close = Mock(side_effect=RuntimeError('capture close failed') if close_fails else None)
    stop_assistant = Mock(side_effect=RuntimeError('assistant stop failed'))
    battle = SimpleNamespace(stop_auto_battle=Mock(side_effect=RuntimeError('battle stop failed')))
    controller = SimpleNamespace(cancel_inputs=Mock())
    context = SimpleNamespace(_auto_battle_context=battle, controller=controller)
    monkeypatch.setattr(og, 'my_app', SimpleNamespace(context_if_ready=lambda: context))
    monkeypatch.setattr(frozen_capture, 'time', SimpleNamespace(time=lambda: clock[0]))

    def base_next(executor, *args, **kwargs):
        executor._frame = frame
        return frame

    monkeypatch.setattr(TaskExecutor, 'next_frame', base_next)
    install_executor_frozen_capture_guard()
    executor = SimpleNamespace(_frame=None, method=SimpleNamespace(
        name='Windows Graphics Capture', close=close),
        trigger_tasks=[SimpleNamespace(_stop_engine=stop_assistant)])
    assert TaskExecutor.next_frame(executor) is frame
    clock[0] = 116
    if close_fails:
        with pytest.raises(RuntimeError, match='capture close failed'):
            TaskExecutor.next_frame(executor)
    else:
        assert TaskExecutor.next_frame(executor) is None
    assert executor._frame is None
    battle.stop_auto_battle.assert_called_once()
    controller.cancel_inputs.assert_called_once()
