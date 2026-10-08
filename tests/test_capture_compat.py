from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from src.capture_compat import blank_frame, install_capture_compat, install_window_position_compat


@pytest.mark.parametrize('build,expected', [(18362, False), (19041, True), (19045, True), (20348, True)])
def test_wgc_does_not_require_optional_border_suppression(monkeypatch, build, expected):
    from ok.util import window
    from ok.device.capture_methods import update
    from ok.rotypes import roapi
    from src.capture_compat import install_windows_graphics_compat
    original = Mock(return_value=True)
    monkeypatch.setattr(window, 'windows_graphics_available', original)
    monkeypatch.setattr(update, 'windows_graphics_available', original)
    monkeypatch.setattr(window, 'WINDOWS_BUILD_NUMBER', build)
    factory = Mock()
    monkeypatch.setattr(roapi, 'GetActivationFactory', factory)
    import ok.rotypes.Windows.Graphics.Capture  # Import may initialize runtime factories.
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
    from src.capture_compat import install_wgc_blank_frame_guard
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
