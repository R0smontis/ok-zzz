"""ONNX inference policy, DirectML serialization, and observable CPU fallback."""
import ctypes
from functools import lru_cache
import logging
import threading
import time

from ok import ConfigOption, og
import onnxruntime as ort
from onnxruntime.capi.onnxruntime_pybind11_state import InvalidArgument
from onedragon.utils import gpu_executor

log = logging.getLogger(__name__)
recognition_config = ConfigOption('识别计算设置', {'计算设备': 'GPU优先', '识别帧率上限': 30},
    description='闪避、YOLO和OCR的计算设备；修改后重启程序生效。GPU不可用时自动使用CPU。',
    config_type={'计算设备': {'type': 'drop_down', 'options': ['GPU优先', 'CPU']},
                 '识别帧率上限': {'type': 'drop_down', 'options': [20, 30, 40, 50, 60],
                     'localized_choices': True,
                     'option_labels': {fps: f'{fps} 帧/秒' for fps in (20, 30, 40, 50, 60)}}},
    config_description={'计算设备': 'GPU运行YOLO/OCR；CPU辅助计算限制2线程并禁用空转；截图和小区域模板仍使用CPU',
                        '识别帧率上限': '任务识别的最高帧率，默认30帧；20帧更省CPU，40～60帧响应更快；不限制调试录像帧率'})
_status = {}
_status_lock = threading.Lock()


def gpu_requested():
    manager = getattr(og, 'global_config', None)
    if manager is None:
        return True
    return manager.get_config(recognition_config).get('计算设备', 'GPU优先') != 'CPU'


def recognition_interval():
    manager = getattr(og, 'global_config', None)
    fps = 30 if manager is None else manager.get_config(recognition_config).get('识别帧率上限', 30)
    try:
        fps = int(fps)
    except (TypeError, ValueError):
        fps = 30
    return 1 / (fps if fps in (20, 30, 40, 50, 60) else 30)


@lru_cache(maxsize=1)
def directml_adapter():
    """Select the dedicated adapter by DXGI index, rather than assuming GPU 0."""
    try:
        class Guid(ctypes.Structure):
            _fields_ = [('a', ctypes.c_uint32), ('b', ctypes.c_uint16), ('c', ctypes.c_uint16),
                        ('d', ctypes.c_ubyte*8)]
        class Description(ctypes.Structure):
            _fields_ = [('name', ctypes.c_wchar*128), ('vendor', ctypes.c_uint), ('device', ctypes.c_uint),
                        ('subsys', ctypes.c_uint), ('revision', ctypes.c_uint),
                        ('video_memory', ctypes.c_size_t), ('system_memory', ctypes.c_size_t),
                        ('shared_memory', ctypes.c_size_t), ('luid_low', ctypes.c_uint32),
                        ('luid_high', ctypes.c_int32), ('flags', ctypes.c_uint)]
        def method(pointer, index, result, *args):
            table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            return ctypes.WINFUNCTYPE(result, ctypes.c_void_p, *args)(table[index])
        factory = ctypes.c_void_p()
        iid = Guid(0x770aae78, 0xf26f, 0x4dba, (ctypes.c_ubyte*8)(0xa8,0x29,0x25,0x3c,0x83,0xd1,0xb3,0x87))
        hr = ctypes.WinDLL('dxgi.dll').CreateDXGIFactory1(ctypes.byref(iid), ctypes.byref(factory))
        if hr != 0:
            raise RuntimeError(f'DXGI HRESULT {hr}')
        adapters = []
        try:
            for index in range(16):
                adapter = ctypes.c_void_p()
                hr = method(factory, 12, ctypes.c_long, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p))(
                    factory, index, ctypes.byref(adapter))
                if hr != 0:
                    break
                try:
                    desc = Description()
                    hr = method(adapter, 10, ctypes.c_long, ctypes.POINTER(Description))(adapter, ctypes.byref(desc))
                    if hr == 0 and not desc.flags & 2:
                        adapters.append({'device_id': index, 'name': desc.name, 'video_memory': desc.video_memory})
                finally:
                    method(adapter, 2, ctypes.c_ulong)(adapter)
        finally:
            method(factory, 2, ctypes.c_ulong)(factory)
        if adapters:
            return max(adapters, key=lambda item: item['video_memory'])
    except Exception as exc:
        log.warning('读取GPU适配器失败，使用DirectML默认适配器：%s', exc)
    return {'device_id': 0, 'name': '默认GPU', 'video_memory': 0}


def runtime_status():
    with _status_lock:
        return {name: dict(status) for name, status in _status.items()}


class ManagedSession:
    def __init__(self, model_path, *, gpu, label, profile=False):
        self.model_path = str(model_path)
        self.label = label
        self.gpu = gpu
        self._fallback_lock = threading.Lock()
        self.profile = profile
        self.fallback_reason = None
        available = ort.get_available_providers()
        candidates = [provider for provider in ('CUDAExecutionProvider', 'DmlExecutionProvider')
                      if gpu and provider in available]
        self.session = None
        for provider in [*candidates, 'CPUExecutionProvider']:
            try:
                session = self._create(provider)
                if provider not in session.get_providers():
                    raise RuntimeError(f'{provider}未成功启动，会话实际为{session.get_providers()}')
                self.session = session
                break
            except Exception as exc:
                if provider == 'CPUExecutionProvider':
                    raise
                self.fallback_reason = str(exc)
                log.warning('%s GPU初始化失败：%s', label, exc)
        if gpu and not candidates:
            self.fallback_reason = '未安装可用的GPU推理后端'
        self._publish()

    def _create(self, provider):
        options = ort.SessionOptions()
        options.enable_profiling = self.profile
        # GPU sessions still create CPU fallback pools. The default per-core
        # pools spin while idle and compete with the game and flash recognition.
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        options.add_session_config_entry('session.intra_op.allow_spinning', '0')
        options.add_session_config_entry('session.inter_op.allow_spinning', '0')
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        providers = [provider]
        if provider == 'DmlExecutionProvider':
            options.enable_mem_pattern = False
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            providers = [(provider, {'device_id': str(directml_adapter()['device_id'])}), 'CPUExecutionProvider']
        elif provider != 'CPUExecutionProvider':
            providers.append('CPUExecutionProvider')
        return gpu_executor.create_onnx_session(
            lambda: ort.InferenceSession(self.model_path, sess_options=options, providers=providers), [provider])

    def _publish(self):
        providers = self.session.get_providers()
        status = {'requested': 'GPU' if self.gpu else 'CPU', 'providers': providers,
                  'fallback_reason': self.fallback_reason,
                  'cpu_threads': 2, 'cpu_spinning': False}
        if 'DmlExecutionProvider' in providers:
            status['adapter'] = directml_adapter()['name']
        with _status_lock:
            _status[self.label] = status
        log.info('%s 推理后端：%s%s', self.label, providers,
                 f'；GPU回退原因：{self.fallback_reason}' if self.fallback_reason else '')
        from src.diagnostics.recorder import record_event
        record_event('inference_backend', model=self.label, **status)

    def __getattr__(self, name):
        return getattr(self.session, name)

    def run(self, output_names, input_feed=None, **kwargs):
        started = time.perf_counter()
        session = self.session
        try:
            result = gpu_executor.run_session(session, output_names, input_feed, **kwargs)
        except Exception as exc:
            if isinstance(exc, InvalidArgument):
                raise
            if not any(provider in session.get_providers() for provider in ('CUDAExecutionProvider', 'DmlExecutionProvider')):
                raise
            with self._fallback_lock:
                if self.session is session:
                    self.fallback_reason = f'GPU推理失败：{exc}'
                    self.session = self._create('CPUExecutionProvider')
                    self._publish()
            result = self.session.run(output_names, input_feed, **kwargs)
        with _status_lock:
            _status[self.label]['last_inference_ms'] = round((time.perf_counter()-started)*1000, 2)
        return result


def create_session(model_path, *, gpu=True, label=None, profile=False):
    return ManagedSession(model_path, gpu=gpu, label=label or str(model_path), profile=profile)
