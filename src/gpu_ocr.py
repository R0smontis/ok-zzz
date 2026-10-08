"""Project-owned ONNX OCR backend; keep ok-script and onnxocr unchanged."""
from onnxocr.onnx_paddleocr import ONNXPaddleOcr
from onnxocr.predict_base import PredictBase
from onnxocr.predict_det import TextDetector
from onnxocr.predict_rec import TextRecognizer
from onnxocr.predict_cls import TextClassifier
from pathlib import Path
from src.inference import create_session, gpu_requested


class GpuPredictBase(PredictBase):
    def __init__(self, model_dir, use_openvino=False, use_npu=False, logger=None, *args):
        self.is_openvino = False
        self.session = create_session(model_dir, gpu=True, label=f'OCR-{Path(model_dir).parent.name}')


class GpuTextDetector(TextDetector, GpuPredictBase):
    pass


class GpuTextRecognizer(TextRecognizer, GpuPredictBase):
    pass


class GpuTextClassifier(TextClassifier, GpuPredictBase):
    pass


class GpuPaddleOcr(ONNXPaddleOcr):
    def __init__(self, **kwargs):
        kwargs.update(use_openvino=False, use_npu=False)
        super().__init__(**kwargs)

    def _initialize_models(self, params):
        self.text_detector = GpuTextDetector(params)
        self.text_recognizer = GpuTextRecognizer(params)
        self.use_angle_cls = params.use_angle_cls
        self.drop_score = params.drop_score
        if self.use_angle_cls:
            self.text_classifier = GpuTextClassifier(params)
        self.args = params
        self.crop_image_res_index = 0


def install_gpu_ocr():
    from src.performance_policy import limit_loaded_blas
    limit_loaded_blas()
    import cv2
    # Agent checks already run concurrently; avoid a full OpenCV worker pool
    # per recognition operation, which otherwise oversubscribes CPU cores.
    cv2.setNumThreads(2)
    from ok.task.TaskExecutor import TaskExecutor
    if getattr(TaskExecutor._create_ocr_lib, '_zzz_gpu', False) is True:
        return
    original = TaskExecutor._create_ocr_lib

    def create(executor, name):
        options = executor.config['ocr'][name]
        if options.get('lib') != 'onnxocr' or not gpu_requested():
            return original(executor, name)
        params = dict(options.get('params') or {})
        params.update(use_angle_cls=False)
        return GpuPaddleOcr(**params)
    create._zzz_gpu = True
    TaskExecutor._create_ocr_lib = create
