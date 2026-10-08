from pathlib import Path

import cv2
import numpy as np
import pytest
from src.frame_geometry import bgra_view, normalize_bgr


def test_large_frame_downscales_to_rgb_exactly(ctx):
    from zzz_od.yolo.flash_classifier import FlashClassifier
    frame = cv2.imread(str(Path(__file__).parent/'fixtures/combat_recording/yellow_warning.png'))
    large = cv2.resize(frame, (2560, 1440))
    out = normalize_bgr(large)
    expected = cv2.cvtColor(cv2.resize(large, (1920, 1080), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
    assert out.shape == (1080, 1920, 3)
    assert np.array_equal(out, expected)
    model = FlashClassifier(model_download_url='', model_name=ctx.model_config.flash_classifier, gpu=True)
    assert model.run(out).class_idx == 2


def test_channel_swap_and_gray_and_invalid_input():
    frame = np.full((1440, 2560, 3), [1, 2, 3], np.uint8)
    assert np.array_equal(normalize_bgr(frame)[0, 0], [3, 2, 1])
    assert normalize_bgr(np.zeros((1080, 1920), np.uint8)).shape == (1080, 1920, 3)
    assert normalize_bgr(None) is None


def _wgc_like(width, height):
    # ok-script WGC: packed BGRA copy, cropped by crop_image, alpha sliced off by get_frame.
    bgra = np.random.default_rng(width).integers(0, 256, (height + 40, width + 16, 4), np.uint8)
    return bgra[32:32 + height, 8:8 + width, :3]


@pytest.mark.parametrize('size', [(2560, 1440), (2048, 1152), (1920, 1080), (1280, 720)])
def test_strided_bgra_frame_matches_contiguous_normalization(size):
    view = _wgc_like(*size)
    assert bgra_view(view) is not None
    assert np.array_equal(normalize_bgr(view), normalize_bgr(np.ascontiguousarray(view)))


def test_view_without_trailing_alpha_byte_uses_plain_path():
    height, width = 720, 1280
    buffer = np.random.default_rng(3).integers(0, 256, height * width * 4 - 1, np.uint8)
    view = np.lib.stride_tricks.as_strided(buffer, (height, width, 3), (width * 4, 4, 1))
    assert bgra_view(view) is None
    assert np.array_equal(normalize_bgr(view), normalize_bgr(np.ascontiguousarray(view)))
