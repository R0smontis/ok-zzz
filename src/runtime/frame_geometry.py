"""Canonical recognition pixels and current client pixels share one transform."""
from dataclasses import dataclass

import cv2
import numpy as np
from numpy.lib.array_utils import byte_bounds


@dataclass(frozen=True)
class FrameGeometry:
    width: int
    height: int
    standard_width: int = 1920
    standard_height: int = 1080

    def __post_init__(self):
        if min(self.width, self.height, self.standard_width, self.standard_height) <= 0:
            raise ValueError('Frame dimensions must be positive')

    def to_client(self, x, y):
        return (x*self.width/self.standard_width, y*self.height/self.standard_height)

    def to_standard(self, x, y):
        return (x*self.standard_width/self.width, y*self.standard_height/self.height)

    def snapshot(self):
        return {'source': [self.width, self.height],
                'recognition': [self.standard_width, self.standard_height],
                'scale': [self.width/self.standard_width, self.height/self.standard_height]}


def bgra_view(frame):
    """Return the packed 4-channel view behind ok-script's `bgra[..., :3]` frame, else None.

    OpenCV processes the 3-of-4 channel view about twice as slowly as the packed buffer.
    """
    if (frame is None or frame.size == 0 or frame.dtype != np.uint8 or frame.ndim != 3
            or frame.shape[2] != 3 or frame.strides[2] != 1 or frame.strides[1] != 4):
        return None
    root = frame
    while isinstance(root.base, np.ndarray):
        root = root.base
    # The alpha byte after the last pixel must lie inside the owning buffer.
    if byte_bounds(frame)[1] + 1 > byte_bounds(root)[1]:
        return None
    return np.lib.stride_tricks.as_strided(frame, (*frame.shape[:2], 4), frame.strides, writeable=False)


def resize_for_recognition(frame, width=1920, height=1080):
    if frame is None or frame.size == 0 or frame.ndim not in (2, 3):
        return None
    if frame.shape[:2] == (height, width):
        return frame
    interpolation = cv2.INTER_AREA if frame.shape[1] > width or frame.shape[0] > height else cv2.INTER_CUBIC
    return cv2.resize(frame, (width, height), interpolation=interpolation)


def normalize_bgr(frame, width=1920, height=1080):
    bgra = bgra_view(frame)
    if bgra is not None:
        # Resize is per channel, so swapping first yields the same pixels at about half the CPU.
        return resize_for_recognition(cv2.cvtColor(bgra, cv2.COLOR_BGRA2RGB), width, height)
    normalized = resize_for_recognition(frame, width, height)
    if normalized is None:
        return None
    if normalized.ndim == 2:
        return cv2.cvtColor(normalized, cv2.COLOR_GRAY2RGB)
    if normalized.shape[2] not in (3, 4):
        return None
    return cv2.cvtColor(normalized, cv2.COLOR_BGR2RGB)
