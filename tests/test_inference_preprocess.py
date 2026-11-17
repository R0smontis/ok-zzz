"""Model inputs retain pixels, padding, layout and numeric precision."""
import cv2
import numpy as np
import pytest

from onedragon.yolo.onnx_utils import scale_input_image_u


@pytest.mark.parametrize('shape,target', [
    ((108, 192), (64, 64)),
    ((192, 108), (64, 64)),
    ((32, 32), (32, 32)),
    ((17, 29), (63, 47)),
])
@pytest.mark.parametrize('dtype', [np.uint8, np.float32, np.uint16])
@pytest.mark.parametrize('layout', ['packed', 'bgra_view', 'reversed_rows', 'reversed_channels'])
def test_letterbox_preserves_exact_model_input(shape, target, dtype, layout):
    base = np.random.default_rng(91).integers(0, 256, (*shape, 4), dtype=np.uint8).astype(dtype)
    image = base[:, :, :3]
    if layout == 'packed':
        image = np.ascontiguousarray(image)
    elif layout == 'reversed_rows':
        image = image[::-1]
    elif layout == 'reversed_channels':
        image = image[:, :, ::-1]
    original = image.copy()
    image.setflags(write=False)
    width, height = target
    ratio = min(height / shape[0], width / shape[1])
    sh, sw = int(round(shape[0] * ratio)), int(round(shape[1] * ratio))
    if (height, width) == shape:
        expected_image = image
    else:
        expected_image = np.full((height, width, 3), 114, dtype=np.uint8)
        expected_image[:sh, :sw] = cv2.resize(image, (sw, sh), interpolation=cv2.INTER_LINEAR)
    expected = np.empty((1, 3, height, width), dtype=np.float32)
    expected[0] = expected_image.transpose(2, 0, 1)
    expected /= np.float32(255)

    tensor, actual_h, actual_w = scale_input_image_u(image, width, height)

    np.testing.assert_array_equal(tensor, expected)
    np.testing.assert_array_equal(image, original)
    assert (actual_h, actual_w) == (sh, sw)
    assert tensor.dtype == np.float32
    assert tensor.flags.c_contiguous
    assert not np.shares_memory(tensor, image)


def test_all_byte_values_keep_exact_normalization():
    image = np.repeat(np.arange(256, dtype=np.uint8).reshape(16, 16, 1), 3, axis=2)
    expected = image.transpose(2, 0, 1).astype(np.float32) / np.float32(255)
    tensor, _, _ = scale_input_image_u(image, 16, 16)
    np.testing.assert_array_equal(tensor[0], expected)
