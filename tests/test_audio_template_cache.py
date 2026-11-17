from pathlib import Path
import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest
from scipy.signal import correlate

from zzz_od.auto_battle import auto_battle_dodge_context as module


def context():
    result = module.AutoBattleDodgeContext.__new__(module.AutoBattleDodgeContext)
    result._audio_template = None
    result._audio_template_scaled = None
    result._audio_recorder = module.AudioRecorder()
    return result


def reference(ctx, template, audio):
    x = module.scale_by_std(template)
    y = module.scale_by_std(ctx._get_filter_wave(audio))
    a, b = (x, y) if len(x) > len(y) else (y, x)
    return np.max(correlate(a, b, mode='same', method='fft') / len(a))


@pytest.mark.parametrize('length', [16000, 24000])
@pytest.mark.parametrize('kind', ['silence', 'noise', 'warning'])
def test_cached_template_preserves_exact_correlation_and_decision(length, kind):
    ctx = context()
    ctx.init_audio_template()
    rng = np.random.default_rng(71)
    audio = np.zeros(length) if kind == 'silence' else rng.normal(0, .1, length)
    if kind == 'warning':
        raw = module.load_wav(str(Path(__file__).parents[1] / 'assets/template/dodge_audio/template_1.wav'), 32000)
        audio[:min(length, len(raw))] += raw[:min(length, len(raw))]
    original = audio.copy()
    expected = reference(ctx, ctx._audio_template, audio)
    actual = ctx.get_max_corr(ctx._audio_template, audio)
    assert actual == expected
    for threshold in [0.1, expected, np.nextafter(expected, -np.inf), np.nextafter(expected, np.inf)]:
        assert (actual > threshold) == (expected > threshold)
    np.testing.assert_array_equal(audio, original)
    assert not ctx._audio_template.flags.writeable
    assert not ctx._audio_template_scaled.flags.writeable
    # An unrelated template must not accidentally reuse the cached values.
    other = rng.normal(0, 1, 3000)
    assert ctx.get_max_corr(other, audio) == reference(ctx, other, audio)


def test_template_is_not_available_until_filtering_finishes(monkeypatch):
    ctx = context()
    entered, release = threading.Event(), threading.Event()
    def delayed_filter(wave):
        entered.set()
        assert release.wait(5)
        return wave.astype(np.float64)
    monkeypatch.setattr(ctx, '_get_filter_wave', delayed_filter)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(ctx.init_audio_template)
        try:
            assert entered.wait(5)
            assert ctx._audio_template is None
        finally:
            release.set()
        future.result(timeout=5)
    assert ctx._audio_template is not None
    np.testing.assert_array_equal(ctx._audio_template_scaled, module.scale_by_std(ctx._audio_template))


def test_failed_filter_leaves_template_retryable(monkeypatch):
    ctx = context()
    original = ctx._get_filter_wave
    def fail(_):
        raise RuntimeError('filter failed')
    monkeypatch.setattr(ctx, '_get_filter_wave', fail)
    with pytest.raises(RuntimeError, match='filter failed'):
        ctx.init_audio_template()
    assert ctx._audio_template is None
    monkeypatch.setattr(ctx, '_get_filter_wave', original)
    ctx.init_audio_template()
    assert ctx.get_max_corr(ctx._audio_template, np.zeros(16000)) == 0
