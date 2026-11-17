"""Mask owned RGB frames without mutating capture buffers or older screenshots."""
import cv2
import numpy as np
import pytest

from src.runtime.frame_geometry import normalize_bgr
from zzz_od.const.game_const import YOLO_DEFAULT_COLOR
from zzz_od.controller.zzz_controller import ZzzController
from zzz_od.screen_area.screen_normal_world import ScreenNormalWorldEnum


def controller():
    result = ZzzController.__new__(ZzzController)
    result.standard_width, result.standard_height = 1920, 1080
    result._last_frame_request = 0
    return result


@pytest.mark.parametrize('size', [(1920, 1080), (2560, 1440)])
@pytest.mark.parametrize('layout', ['bgr', 'bgra', 'bgra_view', 'gray'])
def test_screenshot_preserves_capture_pixels_and_previous_results(size, layout):
    width, height = size
    rng = np.random.default_rng(53)
    source = rng.integers(0, 256, (height, width, 4), np.uint8)
    if layout == 'bgr':
        source = np.ascontiguousarray(source[:, :, :3])
    elif layout == 'bgra_view':
        source = source[:, :, :3]
    elif layout == 'gray':
        source = cv2.cvtColor(source, cv2.COLOR_BGRA2GRAY)
    before = source.copy()
    source.setflags(write=False)
    op = controller()
    op.frame_provider = lambda: (123., source)
    expected = op.fill_uid_black(normalize_bgr(source))

    _, frame = op.screenshot()

    np.testing.assert_array_equal(frame, expected)
    np.testing.assert_array_equal(source, before)
    assert not np.shares_memory(frame, source)
    assert frame.flags.writeable
    previous = frame.copy()
    op._last_frame_request = 0
    _, next_frame = op.screenshot()
    next_frame[:] = 0
    np.testing.assert_array_equal(frame, previous)
    np.testing.assert_array_equal(source, before)


def test_uid_mask_keeps_copy_by_default():
    op = controller()
    source = np.zeros((1080, 1920, 3), np.uint8)
    source.setflags(write=False)
    result = op.fill_uid_black(source)
    assert not np.shares_memory(source, result)
    rect = ScreenNormalWorldEnum.UID.value.rect
    expected = np.zeros_like(source)
    expected[rect.y1:rect.y2+1, rect.x1:rect.x2+1] = YOLO_DEFAULT_COLOR
    np.testing.assert_array_equal(result, expected)
    assert not np.any(source)


def test_uid_mask_can_update_an_owned_frame_without_copying():
    op = controller()
    owned = np.zeros((1080, 1920, 3), np.uint8)
    expected = op.fill_uid_black(owned)
    assert op.fill_uid_black(owned, new_image=False) is owned
    np.testing.assert_array_equal(owned, expected)
