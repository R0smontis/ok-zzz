"""Exercise the real launcher in an isolated D-drive install, not the user's app.

Usage: python tools/launcher/smoke.py EXE PYTHON_INSTALL EMPTY_FIXTURE_DIR
The fixture's loopback Git server deliberately accepts HTTP and never replies.
"""
import json
import shutil
import socketserver
import subprocess
import sys
import threading
import time
from pathlib import Path


class StalledGit(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.settimeout(60)
        try:
            self.request.recv(65536)
            time.sleep(45)
            self.server.disconnected.set()
        except OSError:
            pass


class Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True
    disconnected = None


def run(executable, python_install, root):
    root.mkdir(parents=True, exist_ok=False)
    app_dir = root / 'data/apps/ok-zzz'
    working = app_dir / 'working'
    python_dir = app_dir / 'python'
    working.mkdir(parents=True)
    python_dir.mkdir()
    for name in ('python.exe', 'pythonw.exe', 'python312.dll', 'python3.dll',
                 'vcruntime140.dll', 'vcruntime140_1.dll'):
        shutil.copy2(python_install / name, python_dir / name)
    # Only stdlib modules used by the fixture; no third-party import or user config.
    (python_dir / 'Lib').mkdir()
    shutil.copytree(python_install / 'Lib/encodings', python_dir / 'Lib/encodings')
    shutil.copy2(executable, root / 'ok-zzz.exe')
    subprocess.run(['git', 'init', str(app_dir / 'repo')], check=True, capture_output=True)
    with Server(('127.0.0.1', 0), StalledGit) as server:
        server.disconnected = threading.Event()
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f'http://127.0.0.1:{server.server_address[1]}/repo.git'
        profile = {'name': 'Global', 'git_url': url, 'main_script': 'main.py',
                   'requires_python': '3.12', 'requirements': 'requirements.lock.txt',
                   'admin': False, 'use_pythonw': True, 'show_add_defender': False}
        subprocess.run(['git', '-C', str(app_dir / 'repo'), 'remote', 'add', 'origin', url],
                       check=True, capture_output=True)
        (working / 'pyappify.yml').write_text(
            'name: ok-zzz\nprofiles:\n  - ' + '\n    '.join(
                f'{key}: {json.dumps(value)}' for key, value in profile.items()) + '\n',
            encoding='utf-8')
        state = {'name': 'ok-zzz', 'current_version': 'v0.2.5', 'installed': True,
                 'auto_start': True, 'current_profile': 'Global', 'profiles': [profile],
                 'available_versions': ['v0.2.5'], 'update_method': 'AUTO_UPDATE'}
        (app_dir / 'app.json').write_text(json.dumps(state), encoding='utf-8')
        # An invalid executable exercises startup failure without creating
        # shortcuts, a real assistant process, or any user preference.
        (python_dir / 'pythonw.exe').write_bytes(b'fixture: invalid executable')
        (working / 'main.py').write_text('pass\n', encoding='utf-8')
        process = subprocess.Popen([str(root / 'ok-zzz.exe')], cwd=root)
        try:
            deadline = time.monotonic() + 70
            text = ''
            while time.monotonic() < deadline:
                logs = list((root / 'logs').glob('app.*'))
                text = '\n'.join(path.read_text(encoding='utf-8', errors='replace') for path in logs)
                if 'Automatic start failed:' in text:
                    break
                if process.poll() is not None:
                    raise AssertionError(f'Launcher exited: {process.returncode}\n{text[-5000:]}')
                time.sleep(0.2)
            for expected in ('Update check failed:', 'Scheduling auto-start',
                             'Auto-starting app', 'Failed to spawn command',
                             'Automatic start failed:'):
                if expected not in text:
                    raise AssertionError(f'Missing {expected!r}\n{text[-7000:]}')
            if server.disconnected.is_set():
                raise AssertionError('Git only returned after the server closed; transport timeout did not fire')
            print('PASS: stalled Git returned; installed auto-start attempted; child failure reported.')
            print(f'Isolated evidence: {root / "logs"}')
        finally:
            # Only this fixture launcher is terminated; never enumerate/stop user apps.
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
            server.shutdown()


if __name__ == '__main__':
    run(*(Path(value).resolve() for value in sys.argv[1:]))
