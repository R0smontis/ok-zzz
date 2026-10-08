"""Carry an executor's input permission into its worker thread."""
from contextvars import ContextVar
import threading

# Manual live-debug input owns a separate background backend. All automatic
# controller paths share this gate, including running application workers.
debug_control_owned = threading.Event()

execution_input_guard = ContextVar('execution_input_guard', default=None)
execution_action = ContextVar('execution_action', default=None)


def execution_input_allowed() -> bool:
    guard = execution_input_guard.get()
    return not debug_control_owned.is_set() and (guard is None or guard())
