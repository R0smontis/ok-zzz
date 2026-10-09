"""Run with Python, or use ok-zzz.exe --live-client with --output."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.live.client import run

if __name__ == '__main__':
    raise SystemExit(run())
