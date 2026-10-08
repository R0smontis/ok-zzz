"""Bound per-kind recognition work without queueing old screenshots."""
import threading
from collections import Counter


class SingleFlightChecks:
    def __init__(self):
        self._lock = threading.Lock()
        self._pending = {}
        self._submitted = Counter()
        self._skipped = Counter()

    def submit(self, name, executor, function, *args, sync=False):
        while True:
            with self._lock:
                previous = self._pending.get(name)
                if previous is None or previous.done():
                    future = executor.submit(function, *args)
                    self._pending[name] = future
                    self._submitted[name] += 1
                    return future
                if not sync:
                    self._skipped[name] += 1
                    return None
            # A synchronous encounter probe needs this screenshot's results.
            # Wait outside the scheduling lock, then submit the fresh image.
            try:
                previous.result()
            except Exception:
                pass  # The caller already registered the error callback.

    def snapshot(self):
        with self._lock:
            return {'pending': [name for name, future in self._pending.items() if not future.done()],
                    'submitted': dict(self._submitted), 'skipped_busy': dict(self._skipped)}
