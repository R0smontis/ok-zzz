"""Mission movement templates must exist in source and frozen distributions."""
import sys
from pathlib import Path
import pytest

from onedragon.base.config.yaml_config import YamlConfig
from onedragon.utils import os_utils
from zzz_od.operation.key_sim_runner import KeySimRunner
from test_lost_void_background_menus import operation

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / 'config/key_sim/真拿命验收.sample.yml'


def runner(ctx):
    op = operation(KeySimRunner)
    op.config_name = '真拿命验收'
    op.ops = []
    op.ctx.auto_battle_context = ctx.auto_battle_context
    return op


def test_real_mission_template_loads_every_atomic_action_without_executing(ctx):
    op = runner(ctx)
    assert op.load_config().is_success
    assert len(op.ops) == 14
    assert any('移动-前' in atomic.op_name for atomic in op.ops)
    assert any('移动-右' in atomic.op_name for atomic in op.ops)
    assert any('闪避' in atomic.op_name for atomic in op.ops)
    op.ctx.controller.btn_press.assert_not_called()


@pytest.mark.parametrize('text', [None, 'operations: []\n', 'operations: {}\n',
    'operations:\n- null\n', 'operations:\n- op_name: 2\n', 'operations:\n- op_name: ""\n',
    'operations:\n- op_name: 不存在的指令\n', 'operations:\n- op_name: 等待秒数\n  unknown: 1\n'])
def test_missing_empty_or_invalid_config_is_failure_not_noop_success(tmp_path, monkeypatch, text, ctx):
    monkeypatch.setattr(os_utils, 'get_work_dir', lambda: str(tmp_path))
    if text is not None:
        folder = tmp_path / 'config/key_sim'
        folder.mkdir(parents=True)
        (folder / '真拿命验收.yml').write_text(text, encoding='utf-8')
    op = runner(ctx)
    op.ops = [object()]  # stale operations from an earlier run must not survive a bad reload
    assert op.load_config().is_fail
    assert op.ops == []
    op.ctx.controller.btn_press.assert_not_called()


def test_frozen_distribution_loads_sample_and_keeps_user_override(tmp_path, monkeypatch, ctx):
    work, bundle = tmp_path / 'work', tmp_path / 'bundle'
    work.mkdir()
    folder = bundle / 'resources/config/key_sim'
    folder.mkdir(parents=True)
    (folder / TEMPLATE.name).write_bytes(TEMPLATE.read_bytes())
    monkeypatch.setattr(os_utils, 'get_work_dir', lambda: str(work))
    monkeypatch.setattr(sys, '_MEIPASS', str(bundle), raising=False)
    op = runner(ctx)
    assert op.load_config().is_success and len(op.ops) == 14
    user = work / 'config/key_sim/真拿命验收.yml'
    user.write_text('operations:\n- op_name: 等待秒数\n  seconds: 0.1\n', encoding='utf-8')
    assert op.load_config().is_success and len(op.ops) == 1


def test_bundled_sample_copy_on_write_never_overwrites_distribution(tmp_path, monkeypatch):
    work, bundle = tmp_path / 'work', tmp_path / 'bundle'
    work.mkdir()
    folder = bundle / 'resources/config/key_sim'
    folder.mkdir(parents=True)
    sample = folder / TEMPLATE.name
    original = TEMPLATE.read_bytes()
    sample.write_bytes(original)
    monkeypatch.setattr(os_utils, 'get_work_dir', lambda: str(work))
    monkeypatch.setattr(sys, '_MEIPASS', str(bundle), raising=False)
    configuration = YamlConfig('真拿命验收', sub_dir=['key_sim'], sample=True)
    configuration.update('test_marker', True)
    configuration.update('second_write', True)
    configuration.save_diy('test_marker: true' + chr(10))
    assert sample.read_bytes() == original
    assert (work / 'config/key_sim/真拿命验收.yml').exists()


def test_upstream_asset_sync_includes_mission_key_sim_templates():
    from tools.port.fetch_onedragon_assets import ASSET_SPECS
    assert ('config/key_sim', 'config/key_sim', True) in ASSET_SPECS
