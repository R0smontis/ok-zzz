"""重复加载必须保持独立，文件变化和解析失败不能沿用旧流水线。"""
import os
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest
import yaml

from onedragon.base.cv_process.cv_service import CvService


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(CvService, 'PIPELINE_DIR', str(tmp_path / 'pipelines'))
    monkeypatch.setattr(CvService, 'TEMPLATE_DIR', str(tmp_path / 'templates'))
    return CvService(SimpleNamespace(ocr=None, template_loader=None))


def write_pipeline(service, threshold):
    path = os.path.join(service.PIPELINE_DIR, 'threshold.yml')
    previous = os.stat(path) if os.path.exists(path) else None
    with open(path, 'w', encoding='utf-8') as stream:
        yaml.safe_dump([{'step': '灰度化'}, {'step': '二值化',
                       'params': {'method': 'BINARY', 'threshold_value': threshold}}],
                       stream, allow_unicode=True)
    if previous is not None:
        os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns + 1_000_000_000))
    return path


def mask(pipeline):
    source = np.repeat(np.array([[50, 150, 250]], dtype=np.uint8)[..., None], 3, axis=2)
    return pipeline.execute(source, debug_mode=False).mask_image.tolist()


def test_repeated_loads_and_edits_keep_independent_execution(service):
    write_pipeline(service, 100)
    edited = service.load_pipeline('threshold')
    original = service.load_pipeline('threshold')
    edited.steps[1].params['threshold_value'] = 200
    assert mask(edited) == [[0, 0, 255]]
    assert mask(original) == mask(service.load_pipeline('threshold')) == [[0, 255, 255]]


def test_external_same_size_edit_is_seen_on_next_execution(service):
    path = write_pipeline(service, 100)
    assert mask(service.load_pipeline('threshold')) == [[0, 255, 255]]
    old_size = os.stat(path).st_size
    write_pipeline(service, 200)
    assert os.stat(path).st_size == old_size
    assert mask(service.load_pipeline('threshold')) == [[0, 0, 255]]


def test_size_change_invalidates_even_if_timestamp_is_preserved(service):
    path = write_pipeline(service, 100)
    service.load_pipeline('threshold')
    previous = os.stat(path)
    write_pipeline(service, 25)
    os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    assert mask(service.load_pipeline('threshold')) == [[255, 255, 255]]


def test_save_rename_and_delete_keep_file_semantics(service):
    write_pipeline(service, 100)
    pipeline = service.load_pipeline('threshold')
    pipeline.steps[1].params['threshold_value'] = 200
    assert service.save_pipeline('threshold', pipeline)
    assert mask(service.load_pipeline('threshold')) == [[0, 0, 255]]
    service.rename_pipeline('threshold', 'renamed')
    assert service.load_pipeline('threshold') is None
    assert mask(service.load_pipeline('renamed')) == [[0, 0, 255]]
    service.delete_pipeline('renamed')
    assert service.load_pipeline('renamed') is None


def test_invalid_yaml_and_external_deletion_never_reuse_cached_success(service):
    path = write_pipeline(service, 100)
    service.load_pipeline('threshold')
    with open(path, 'w', encoding='utf-8') as stream:
        stream.write('[invalid: [')
    assert service.load_pipeline('threshold') is None
    write_pipeline(service, 200)
    assert mask(service.load_pipeline('threshold')) == [[0, 0, 255]]
    os.remove(path)
    assert service.load_pipeline('threshold') is None


def test_concurrent_loads_do_not_share_editable_step_state(service):
    write_pipeline(service, 100)
    with ThreadPoolExecutor(max_workers=4) as executor:
        pipelines = list(executor.map(lambda _: service.load_pipeline('threshold'), range(8)))
    pipelines[0].steps[1].params['threshold_value'] = 200
    assert mask(pipelines[0]) == [[0, 0, 255]]
    assert all(mask(pipeline) == [[0, 255, 255]] for pipeline in pipelines[1:])
