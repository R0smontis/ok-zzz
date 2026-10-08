"""Best-match selection retains threshold, ordering and non-finite semantics."""
import cv2
import numpy as np
import pytest

from onedragon.utils.cv2_utils import match_template


@pytest.mark.parametrize('scores,threshold,ignore_inf,expected', [
    ([[.5, .9], [.9, .8]], .9, False, (1, 0, .9)),
    ([[.5, .6], [.7, .8]], .9, False, None),
    ([[np.nan, np.inf], [.8, .9]], .8, True, (1, 1, .9)),
    ([[np.nan, np.inf], [np.inf, .9]], .8, False, (1, 0, np.inf)),
    ([[np.nan, np.inf], [-np.inf, np.nan]], 0, True, None),
    ([[np.nan, -np.inf], [-np.inf, np.nan]], -np.inf, False, (1, 0, -np.inf)),
])
def test_best_match_filters_before_selecting_first_maximum(monkeypatch, scores, threshold, ignore_inf, expected):
    monkeypatch.setattr(cv2, 'matchTemplate', lambda *args, **kwargs: np.array(scores, dtype=np.float32))
    result = match_template(np.zeros((3, 3), np.uint8), np.zeros((2, 2), np.uint8),
                            threshold, ignore_inf=ignore_inf)
    if expected is None:
        assert result.max is None and list(result) == []
    else:
        x, y, confidence = expected
        assert len(result) == 1
        assert (result.max.x, result.max.y, result.max.w, result.max.h) == (x, y, 2, 2)
        assert result.max.confidence == pytest.approx(confidence)


def test_repeated_actual_template_keeps_first_peak_and_all_matches():
    template = np.random.default_rng(12).integers(0, 255, (8, 8), dtype=np.uint8)
    source = np.zeros((32, 60), np.uint8)
    source[3:11, 4:12] = template
    source[19:27, 40:48] = template
    best = match_template(source, template, .999)
    all_matches = match_template(source, template, .999, only_best=False)
    assert (best.max.x, best.max.y) == (4, 3)
    assert [(m.x, m.y) for m in all_matches] == [(4, 3), (40, 19)]


def test_template_larger_than_source_is_not_a_match():
    result = match_template(np.zeros((2, 2), np.uint8), np.zeros((3, 3), np.uint8), .8)
    assert result.max is None and list(result) == []
