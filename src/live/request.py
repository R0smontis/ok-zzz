"""How live debugging gets switched on: never by default, only on an explicit request.

People start it on the debug page. Agents have two entries that need no clicks:
- launch the app with ``--live-debug`` (or set ``OK_ZZZ_LIVE_DEBUG=1``);
- while it runs, create ``debug/live/request`` in its work directory
  (``tools/live_debug.py --root <work dir> enable`` does this and waits for the session).
The running app checks for the file twice a second, deletes it and starts monitoring.
"""
import os
import sys
import time
from pathlib import Path

LAUNCH_FLAG = '--live-debug'
ENV_FLAG = 'OK_ZZZ_LIVE_DEBUG'
REQUEST_NAME = 'request'


def requested_at_launch(argv=None, environ=None) -> bool:
    argv = sys.argv if argv is None else argv
    environ = os.environ if environ is None else environ
    return LAUNCH_FLAG in argv or str(environ.get(ENV_FLAG, '')).strip().lower() in ('1', 'true', 'yes')


def request_path(folder) -> Path:
    return Path(folder) / REQUEST_NAME


def write_request(folder) -> Path:
    """Ask a running app (whose live folder this is) to start monitoring."""
    path = request_path(folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(time.time()), encoding='utf-8')
    return path


def take_request(folder) -> bool:
    """Consume a pending request; True when one was present."""
    path = request_path(folder)
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return path.exists()  # Still unreadable or locked: honour it, the next start clears the state.
