"""Redemption codes published upstream between ok-zzz releases.

OneDragon's CI rewrites config/redemption_codes.sample.yml whenever new codes appear, and its
users receive them with the next git update. ok-zzz has no git update, so the 兑换码 app reads
the same file from upstream when it runs and keeps the last copy for the daily status check.
"""
import os
import time
import urllib.request

import yaml

from onedragon.utils import os_utils
from onedragon.utils.log_utils import log

SOURCES = (
    'https://raw.githubusercontent.com/OneDragon-Anything/ZenlessZoneZero-OneDragon/main/config/redemption_codes.sample.yml',
    'https://cnb.cool/OneDragon-Anything/ZenlessZoneZero-OneDragon/-/git/raw/main/config/redemption_codes.sample.yml',
)
REFRESH_SECONDS = 6 * 3600


def _cache_path() -> str:
    return os.path.join(os_utils.get_path_under_work_dir('cache'), 'redemption_codes.yml')


def _parse(text) -> dict[str, int]:
    data = yaml.safe_load(text)
    codes = data.get('codes') if isinstance(data, dict) else None
    if not isinstance(codes, dict):
        return {}
    return {str(code).strip(): int(end) for code, end in codes.items()
            if str(code).strip() and str(end).isdigit()}


def cached_codes() -> dict[str, int]:
    """The last published codes; never touches the network."""
    try:
        with open(_cache_path(), encoding='utf-8') as fp:
            return _parse(fp.read())
    except (OSError, ValueError, yaml.YAMLError):
        return {}


def refresh(timeout: float = 5) -> dict[str, int]:
    """Download the published codes unless the cache is recent; the cache answers on any failure."""
    path = _cache_path()
    try:
        if time.time() - os.path.getmtime(path) < REFRESH_SECONDS:
            return cached_codes()
    except OSError:
        pass
    for url in SOURCES:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                text = response.read().decode('utf-8')
            codes = _parse(text)
        except Exception as error:
            log.info('获取最新兑换码失败 %s：%s', url, error)
            continue
        if not codes:
            continue
        with open(path, 'w', encoding='utf-8') as fp:
            fp.write(text)
        log.info('已获取最新兑换码 %d 个', len(codes))
        return codes
    return cached_codes()
