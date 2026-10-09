"""GPU routing, actual OCR MRO, and fallback behavior without game input."""
from types import SimpleNamespace
from unittest.mock import Mock
import threading
import time
import pytest
from src.runtime import inference


def fake_session(provider, *, fail=False):
    return SimpleNamespace(get_providers=lambda: [provider],
                           get_inputs=lambda: [SimpleNamespace(name='x', shape=[1,3,None,None])],
                           get_outputs=lambda: [SimpleNamespace(name='out')],
                           run=Mock(side_effect=RuntimeError('device removed')) if fail else Mock(return_value=['result']))


@pytest.fixture
def session_factory(monkeypatch):
    created = []
    def create(path, *, sess_options, providers):
        provider = providers[0][0] if isinstance(providers[0], tuple) else providers[0]
        session = fake_session(provider)
        created.append((provider, sess_options, providers, session))
        return session
    monkeypatch.setattr(inference.ort, 'InferenceSession', create)
    monkeypatch.setattr(inference.ort, 'get_available_providers', lambda: ['DmlExecutionProvider','CPUExecutionProvider'])
    monkeypatch.setattr(inference, 'directml_adapter', lambda: {'device_id': 1, 'name': 'Dedicated GPU'})
    return created


def test_gpu_uses_dedicated_adapter_sequential_options_and_shared_executor(session_factory):
    session = inference.create_session('dummy.onnx', gpu=True, label='test-gpu')
    provider, options, providers, raw = session_factory[0]
    assert provider == 'DmlExecutionProvider'
    assert providers[0][1]['device_id'] == '1'
    assert options.enable_mem_pattern is False
    assert options.execution_mode == inference.ort.ExecutionMode.ORT_SEQUENTIAL
    assert options.intra_op_num_threads == 2
    assert options.inter_op_num_threads == 1
    assert options.get_session_config_entry('session.intra_op.allow_spinning') == '0'
    assert options.get_session_config_entry('session.inter_op.allow_spinning') == '0'
    raw.run.side_effect = lambda *args, **kwargs: [threading.current_thread().name]
    assert session.run([], {})[0].startswith('od_gpu')
    assert inference.runtime_status()['test-gpu']['adapter'] == 'Dedicated GPU'


def test_cpu_preference_skips_gpu_and_runtime_does_not_claim_gpu(session_factory):
    session = inference.create_session('dummy.onnx', gpu=False, label='test-cpu')
    assert session.get_providers() == ['CPUExecutionProvider']
    assert len(session_factory) == 1
    options = session_factory[0][1]
    assert options.intra_op_num_threads == 2
    assert options.get_session_config_entry('session.intra_op.allow_spinning') == '0'
    assert session.run([], {}) == ['result']
    assert inference.runtime_status()['test-cpu']['requested'] == 'CPU'
    assert inference.runtime_status()['test-cpu']['cpu_spinning'] is False


def test_missing_gpu_provider_records_fallback_reason(session_factory, monkeypatch):
    monkeypatch.setattr(inference.ort, 'get_available_providers', lambda: ['CPUExecutionProvider'])
    session = inference.create_session('dummy.onnx', label='no-gpu')
    assert session.get_providers() == ['CPUExecutionProvider']
    assert inference.runtime_status()['no-gpu']['fallback_reason']


def test_gpu_initialization_failure_retries_cpu(session_factory, monkeypatch):
    original = inference.ort.InferenceSession
    def create(path, **kwargs):
        if isinstance(kwargs['providers'][0], tuple):
            raise RuntimeError('GPU unavailable')
        return original(path, **kwargs)
    monkeypatch.setattr(inference.ort, 'InferenceSession', create)
    session = inference.create_session('dummy.onnx', label='init-failure')
    assert session.get_providers() == ['CPUExecutionProvider']
    assert session.run([], {}) == ['result']
    assert 'GPU unavailable' in inference.runtime_status()['init-failure']['fallback_reason']


def test_runtime_gpu_failure_retries_input_once_and_keeps_cpu(session_factory):
    session = inference.create_session('dummy.onnx', label='runtime-failure')
    session.session.run.side_effect = RuntimeError('device removed')
    assert session.run([], {'x': [1]}) == ['result']
    assert session.get_providers() == ['CPUExecutionProvider']
    assert session.run([], {'x': [2]}) == ['result']
    assert len(session_factory) == 2
    assert session_factory[1][3].run.call_count == 2
    assert 'device removed' in inference.runtime_status()['runtime-failure']['fallback_reason']


def test_ocr_models_initialize_directly_with_gpu_sessions(session_factory):
    from src.runtime.gpu_ocr import GpuPaddleOcr
    ocr = GpuPaddleOcr(use_angle_cls=True)
    assert len(session_factory) == 3  # No temporary CPU OCR sessions.
    assert all(provider == 'DmlExecutionProvider' for provider, *_ in session_factory)
    for predictor in (ocr.text_detector, ocr.text_recognizer, ocr.text_classifier):
        assert not predictor.is_openvino
        assert predictor.run([], {}) == ['result']


def test_framework_ocr_routes_to_gpu_only_for_onnxocr(monkeypatch):
    from src.runtime import gpu_ocr
    from ok.task.TaskExecutor import TaskExecutor
    original = Mock(return_value='original')
    monkeypatch.setattr(TaskExecutor, '_create_ocr_lib', original)
    gpu_ocr.install_gpu_ocr()
    monkeypatch.setattr(gpu_ocr, 'gpu_requested', lambda: True)
    factory = Mock(return_value='gpu')
    monkeypatch.setattr(gpu_ocr, 'GpuPaddleOcr', factory)
    executor = SimpleNamespace(config={'ocr': {'default': {'lib': 'onnxocr', 'params': {'use_npu': True}}}})
    assert TaskExecutor._create_ocr_lib(executor, 'default') == 'gpu'
    assert factory.call_args.kwargs['use_angle_cls'] is False
    monkeypatch.setattr(gpu_ocr, 'gpu_requested', lambda: False)
    assert TaskExecutor._create_ocr_lib(executor, 'default') == 'original'
    executor.config['ocr']['default']['lib'] = 'paddleocr'
    monkeypatch.setattr(gpu_ocr, 'gpu_requested', lambda: True)
    assert TaskExecutor._create_ocr_lib(executor, 'default') == 'original'


def test_old_model_gpu_flags_upgrade_once_and_cpu_setting_overrides(monkeypatch, tmp_path):
    from onedragon.utils import os_utils
    from zzz_od.config.model_config import ModelConfig
    monkeypatch.setattr(os_utils, 'get_work_dir', lambda: str(tmp_path))
    config = ModelConfig(SimpleNamespace())
    assert config.flash_classifier_gpu and config.lost_void_det_gpu and config.hollow_zero_event_gpu
    config.flash_classifier_gpu = False
    assert not ModelConfig(SimpleNamespace()).flash_classifier_gpu
    config.flash_classifier_gpu = True
    monkeypatch.setattr(inference, 'gpu_requested', lambda: False)
    assert not config.flash_classifier_gpu and not config.lost_void_det_gpu


def test_diagnostic_snapshot_contains_actual_gpu_backend_and_cached_team(monkeypatch):
    from src.diagnostics.recorder import runtime_snapshot
    from ok import og
    party = SimpleNamespace(agent_list=[SimpleNamespace(agent=SimpleNamespace(agent_name='克拉蕾'),
        matched_template_id='claret', energy=50, special_ready=True, ultimate_ready=False)],
        should_check_all_agents=False, check_agent_diff_times=7, agent_update_time=123)
    battle = SimpleNamespace(auto_op=None, last_check_in_battle=True,
                             agent_context=SimpleNamespace(team_info=party))
    context = SimpleNamespace(run_context=SimpleNamespace(current_app_id=None, current_application=None),
                              controller=SimpleNamespace(background_mode=True), auto_battle_context=battle)
    monkeypatch.setattr(og, 'my_app', SimpleNamespace(_context=context))
    monkeypatch.setattr(inference, '_status', {'OCR-det': {'providers': ['DmlExecutionProvider'], 'last_inference_ms': 10}})
    executor = SimpleNamespace(paused=False, get_all_tasks=lambda: [], _last_frame_time=time.time())
    snapshot = runtime_snapshot(executor)
    assert snapshot['recognition']['OCR-det']['providers'] == ['DmlExecutionProvider']
    assert snapshot['battle']['team'][0]['agent'] == '克拉蕾'
    assert snapshot['battle']['team'][0]['energy'] == 50
    assert snapshot['battle']['team_rejected_checks'] == 7


@pytest.mark.parametrize('name,expected', [('red_warning', 1), ('yellow_warning', 2)])
def test_real_warning_frames_classify_correctly_on_gpu(ctx, name, expected):
    from pathlib import Path
    import cv2
    from zzz_od.controller.zzz_controller import ZzzController
    from zzz_od.yolo.flash_classifier import FlashClassifier
    model = FlashClassifier(model_download_url='', model_name=ctx.model_config.flash_classifier, gpu=True)
    bgr = cv2.imread(str(Path(__file__).parent/'fixtures/combat_recording'/f'{name}.png'))
    controller = ZzzController.__new__(ZzzController)
    controller.standard_width, controller.standard_height = 1920, 1080
    prediction = model.run(controller.normalize_frame(bgr))
    assert prediction.class_idx == expected and prediction.confidence >= .9
    if 'DmlExecutionProvider' in inference.ort.get_available_providers():
        assert model.session.get_providers()[0] == 'DmlExecutionProvider'
