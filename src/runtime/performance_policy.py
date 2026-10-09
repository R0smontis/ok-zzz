"""Bound native CPU pools; GPU inference retains its own serialized executor."""
import os

_limits = None


def configure_native_threads():
    # Run before numpy/scipy/Qt imports at normal startup. Small recognition
    # operations should not create a worker per logical processor.
    for name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        os.environ[name] = '2'
    os.environ['OMP_WAIT_POLICY'] = 'PASSIVE'
    os.environ['KMP_BLOCKTIME'] = '0'


def limit_loaded_blas():
    # Development launchers and dependencies may have imported BLAS already.
    # Keep the controller alive rather than repeatedly changing global limits
    # inside competing recognition threads.
    global _limits
    if _limits is None:
        from threadpoolctl import threadpool_limits
        _limits = threadpool_limits(limits=2, user_api='blas')
