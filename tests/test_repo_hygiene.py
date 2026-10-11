"""Source files must not be hidden by .gitignore, or a fresh clone fails to import them."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(shutil.which('git') is None or not (ROOT / '.git').exists(),
                                reason='needs a git checkout')


def _check_ignore(paths):
    # NUL-separated bytes: text-mode stdin on Windows would turn '\n' into '\r\n'.
    result = subprocess.run(['git', 'check-ignore', '--no-index', '-z', '--stdin'], cwd=ROOT,
                            input='\0'.join(paths).encode('utf-8'), capture_output=True)
    return [p for p in result.stdout.decode('utf-8').split('\0') if p]


def test_no_source_file_is_ignored():
    sources = [p.relative_to(ROOT).as_posix() for p in (ROOT / 'src').rglob('*.py') if '__pycache__' not in p.parts]
    assert not _check_ignore(sources)


def test_runtime_output_folders_stay_ignored():
    paths = ['debug/live/session.json', 'build/ok-zzz/x.toc', 'dist/ok-zzz/ok-zzz.exe']
    assert _check_ignore(paths) == paths
