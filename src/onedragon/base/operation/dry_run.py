"""Debug dry-run gate: stop an application before it enters a named node.

Used by the live-debug interface to walk a feature up to its entrance and verify
recognition without the step that spends resources or cannot be undone. The gate is
process-wide, empty by default, and cleared when the debug command that set it ends.
"""
import threading

_lock = threading.Lock()
_stop_before: frozenset[str] = frozenset()
_hits: list[dict] = []


def set_stop_before(nodes) -> None:
    global _stop_before
    with _lock:
        _stop_before = frozenset(str(n) for n in nodes or ())
        _hits.clear()


def stop_before() -> frozenset[str]:
    return _stop_before


def record_hit(operation: str, node: str) -> None:
    with _lock:
        _hits.append({'operation': operation, 'node': node})


def hits() -> list[dict]:
    with _lock:
        return list(_hits)
