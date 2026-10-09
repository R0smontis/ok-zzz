from types import SimpleNamespace
from unittest.mock import Mock
import os

from src.runtime import performance_policy as policy


def test_native_pool_policy_is_bounded_and_passive(monkeypatch):
    for key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS', 'OMP_WAIT_POLICY', 'KMP_BLOCKTIME'):
        monkeypatch.setenv(key, '16')
    policy.configure_native_threads()
    assert os.environ['OPENBLAS_NUM_THREADS'] == os.environ['OMP_NUM_THREADS'] == '2'
    assert os.environ['MKL_NUM_THREADS'] == os.environ['NUMEXPR_NUM_THREADS'] == '2'
    assert os.environ['OMP_WAIT_POLICY'] == 'PASSIVE'
    assert os.environ['KMP_BLOCKTIME'] == '0'


def test_loaded_blas_is_limited_once_for_all_recognition_threads(monkeypatch):
    import threadpoolctl
    limit = Mock(return_value=object())
    monkeypatch.setattr(policy, '_limits', None)
    monkeypatch.setattr(threadpoolctl, 'threadpool_limits', limit)
    policy.limit_loaded_blas(); policy.limit_loaded_blas()
    limit.assert_called_once_with(limits=2, user_api='blas')
