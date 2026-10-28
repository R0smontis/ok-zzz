# -*- coding: utf-8 -*-
# 移植自 ZenlessZoneZero-OneDragon (GPL-3.0)
# 来源: https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
# 路径: zzz_od/auto_battle/auto_battle_dodge_context.py
# 本文件随 ok-zzz 以 GPL-3.0 继续分发。
from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from enum import Enum
from typing import TYPE_CHECKING

import numpy as np
from cv2.typing import MatLike

from onedragon.base.conditional_operation.state_recorder import StateRecord
from onedragon.base.operation.context_notify_event import ContextNotifyEvent
from onedragon.utils import cal_utils, os_utils, thread_utils, yolo_config_utils
from onedragon.utils.log_utils import log
from zzz_od.context.zzz_context import ZContext
from zzz_od.yolo.flash_classifier import FlashClassifier

if TYPE_CHECKING:
    from zzz_od.auto_battle.auto_battle_operator import AutoBattleOperator


# 创建一个线程池执行器，用于异步执行任务
_dodge_check_executor = ThreadPoolExecutor(thread_name_prefix='od_dodge_check', max_workers=16)


# ok-zzz: the three helpers below replace librosa and scikit-learn, which only served these calls
# and brought numba, llvmlite and scikit-learn (~200 MB) into the package.

def to_mono(channels: np.ndarray) -> np.ndarray:
    """(channels, samples) -> samples, averaging channels like librosa.to_mono."""
    channels = np.asarray(channels)
    return channels if channels.ndim == 1 else np.mean(channels, axis=tuple(range(channels.ndim - 1)))


def scale_by_std(x: np.ndarray) -> np.ndarray:
    """x / std(x) like sklearn.preprocessing.scale(x, with_mean=False), keeping a flat signal unchanged."""
    x = np.asarray(x)
    dtype = x.dtype if np.issubdtype(x.dtype, np.floating) else np.float64
    x = x.astype(dtype, copy=False)
    std = float(np.std(x))
    if std < 10 * np.finfo(dtype).eps:
        std = 1.0
    return x / std


def load_wav(path: str, sample_rate: int) -> np.ndarray:
    """Mono float32 samples at `sample_rate`, like librosa.load(path, sr=sample_rate)."""
    import math
    import warnings
    from scipy.io import wavfile
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', wavfile.WavFileWarning)  # Extra metadata chunks.
        source_rate, data = wavfile.read(path)
    if np.issubdtype(data.dtype, np.integer):
        info = np.iinfo(data.dtype)
        offset = (info.max + 1) / 2 if info.min == 0 else 0  # 8-bit WAV is unsigned.
        data = (data.astype(np.float64) - offset) / (info.max + 1 - offset)
    samples = to_mono(np.asarray(data, dtype=np.float64).T)
    if source_rate != sample_rate:
        from scipy.signal import resample_poly
        divisor = math.gcd(int(source_rate), int(sample_rate))
        samples = resample_poly(samples, sample_rate // divisor, source_rate // divisor)
    return samples.astype(np.float32)


class AudioRecorder:
    """
    音频录制类，用于录制和处理音频数据。
    """

    def __init__(self, error_callback: Callable[[RuntimeError], None] | None = None):
        self.running: bool = False  # 标记录制是否正在运行
        self._run_lock = threading.Lock()  # 用于线程安全的锁
        self._error_callback: Callable[[RuntimeError], None] | None = error_callback

        self._sample_rate = 32000  # 采样率
        self._used_channel = 2  # 使用的音频通道数
        self._sample_len = 0.01  # 每次采样的长度（秒）
        self._chunk_size = int(self._sample_rate * self._sample_len)  # 每个音频块的大小

        self.trigger_threshold = 0.1  # 触发阈值

        self._filter_degree = 4  # 四阶bathworth多项式, 越大阻带区域滤波程度越大
        self._cut_off = 1000  # Hz,截止频率,对该频率一下的声音进行滤波,若需要识别人声可适当降低

        # Butterworth高通滤波系数在首次识别声音时计算：scipy.signal 导入约 0.7 秒，不应拖慢界面启动
        self._filter_coefficients: tuple[np.ndarray, np.ndarray] | None = None

        self.latest_audio = np.empty(shape=(0,), dtype=np.float64)  # 存储最新的音频数据
        self._update_audio_lock = threading.Lock()

    @property
    def filter_coefficients(self) -> tuple[np.ndarray, np.ndarray]:
        if self._filter_coefficients is None:
            from scipy.signal import butter
            self._filter_coefficients = butter(self._filter_degree, self._cut_off, btype='highpass',
                                               output='ba', fs=self._sample_rate)
        return self._filter_coefficients

    def start_running_async(self) -> None:
        """
        异步启动音频录制。
        """
        with self._run_lock:
            if self.running:
                return

            self.running = True

        self.latest_audio = np.zeros(int(self._sample_rate // 2))  # 初始化音频数据缓冲区，长度为0.5秒
        future = _dodge_check_executor.submit(self._record_loop)
        future.add_done_callback(thread_utils.handle_future_result)

    def _record_loop(self) -> None:
        """
        音频录制循环，持续录制音频数据。
        """
        # 这个在全局导入的话 会导致QT的选择文件无法使用
        import warnings

        import soundcard as sc
        from soundcard.mediafoundation import SoundcardRuntimeWarning

        warnings.filterwarnings('ignore', category=SoundcardRuntimeWarning)

        try:
            _mic = sc.get_microphone(id=str(sc.default_speaker().name), include_loopback=True)
            _recorder = _mic.recorder(samplerate=self._sample_rate, channels=self._used_channel)
            with _recorder as audio_recorder:
                while self.running:
                    stream_data = audio_recorder.record(numframes=self._chunk_size)
                    if self._used_channel > 1:
                        stream_data = to_mono(stream_data.T)
                    else:
                        stream_data = stream_data.T

                    with self._update_audio_lock:
                        # 更新 latest_audio
                        self.latest_audio[:-len(stream_data)] = self.latest_audio[len(stream_data):]
                        self.latest_audio[-len(stream_data):] = stream_data
        except RuntimeError as e:
            log.warning('音频录制异常，已停止声音闪避识别', exc_info=True)
            if self._error_callback is not None:
                self._error_callback(e)
        finally:
            self.running = False

    def stop_running(self) -> None:
        """
        停止音频录制。
        """
        self.running = False

    def clear_audio(self) -> None:
        """
        清楚当前录音
        """
        with self._update_audio_lock:
            self.latest_audio = np.zeros(int(self._sample_rate // 2))


class YoloStateEventEnum(Enum):
    """
    YOLO状态事件枚举类，定义不同的闪避识别事件。
    """
    DODGE_YELLOW = '闪避识别-黄光'
    DODGE_RED = '闪避识别-红光'
    DODGE_AUDIO = '闪避识别-声音'


class AutoBattleDodgeContext:
    """
    战斗闪避上下文类，用于管理和处理闪避识别相关的逻辑。
    """

    def __init__(self, ctx: ZContext):
        self.ctx: ZContext = ctx  # 上下文对象

        self._flash_model: FlashClassifier | None = None  # 闪避分类器
        self._audio_recorder: AudioRecorder = AudioRecorder(self._on_audio_record_error)  # 音频录制器
        self._audio_template: np.ndarray | None = None  # 音频模板
        self._audio_template_lock = threading.Lock()
        self._audio_template_future: Future | None = None

        # 识别锁，保证每种类型只有一个实例在进行识别
        self._check_dodge_flash_lock = threading.Lock()
        self._check_audio_lock = threading.Lock()

        # 识别间隔
        self._check_dodge_interval: float | list[float] = 0
        self._check_audio_interval: float = 0.02

        # 上一次识别的时间
        self._last_check_dodge_time: float = 0
        self._last_check_audio_time: float = 0

        # 音频事件去重时间间隔
        self._audio_event_interval: float = 0.1
        self._last_audio_event_time: float = 0
        # Trigger assistant may veto repeated or stale recognition results.
        self.event_listener = None
        self._reset_warning_gate()

    def _reset_warning_gate(self):
        self._last_flash = None
        self._last_flash_time = 0.0
        self._flash_absent_since = None
        self._last_visual_warning_time = 0.0
        self._last_event_time = 0.0

    def _publish_warning(self, state_name, screenshot_time):
        """Dungeon warnings must interrupt character actions through the same priority scene."""
        battle = self.ctx.auto_battle_context
        service = battle.state_record_service
        op = battle.auto_op
        enabled = battle.realtime_dodge_enabled_provider
        realtime = (op is not None and op.is_running and op._sub_dir == ['auto_battle']
                    and (enabled is None or enabled()))
        if not realtime:
            # Encounter detection also runs while the battle operator is stopped.
            if state_name is not None:
                service.update_state(StateRecord(state_name, screenshot_time))
            return state_name is not None
        from src.diagnostics.recorder import record_event
        now = time.time()
        hud = service.get_state_recorder('按键可用-普通攻击')
        if not (0 <= now-screenshot_time <= .25 and hud is not None
                and 0 <= now-hud.last_record_time <= .25):
            if state_name is not None:
                record_event('script_warning_rejected', warning=state_name,
                             reason='画面过期或攻击按钮不可见', captured_at=screenshot_time)
            return False
        if state_name is None:
            if self._flash_absent_since is None:
                self._flash_absent_since = screenshot_time
            return False
        if state_name == YoloStateEventEnum.DODGE_AUDIO.value:
            if 0 <= screenshot_time-self._last_visual_warning_time < .35:
                return False
        else:
            if (self._flash_absent_since is not None
                    and screenshot_time-self._flash_absent_since >= .08):
                self._last_flash = None
            repeated = (self._last_flash == state_name
                        and screenshot_time-self._last_flash_time < .3)
            self._last_flash = state_name
            self._last_flash_time = screenshot_time
            self._flash_absent_since = None
            self._last_visual_warning_time = screenshot_time
            if repeated:
                return False
        if screenshot_time-self._last_event_time < .1:
            return False
        self._last_event_time = screenshot_time
        from zzz_od.auto_battle.atomic_op.realtime_response import WARNING_CODES
        service.batch_update_states([
            StateRecord(state_name, screenshot_time),
            StateRecord('自定义-实时闪避事件', screenshot_time, value=WARNING_CODES[state_name]),
        ])
        return True

    def _on_audio_record_error(self, error: RuntimeError) -> None:
        """音频录制异常时通知当前运行界面。"""
        self.ctx.dispatch_event(
            ContextNotifyEvent.EVENT_ID,
            ContextNotifyEvent.warning(
                title='声音闪避已停用',
                content=f'音频录制异常，请检查音频设备/独占模式/默认输出设备：{error}',
            ),
        )

    def init_auto_op(
            self,
            auto_op: AutoBattleOperator,
    ) -> None:
        """
        加载自动战斗操作器时的动作
        """
        self._check_dodge_interval = auto_op.check_dodge_interval
        self._check_audio_interval = 0.02

        use_gpu = self.ctx.model_config.flash_classifier_gpu
        model_settings = (self.ctx.model_config.flash_classifier, use_gpu)
        if self._flash_model is None or getattr(self, '_flash_model_settings', None) != model_settings:
            self._flash_model = FlashClassifier(
                model_download_url=self.ctx.model_config.get_model_download_base_url(
                    'flash_classifier',
                ),
                model_name=self.ctx.model_config.flash_classifier,
                backup_model_name=self.ctx.model_config.flash_classifier_backup,
                model_parent_dir_path=yolo_config_utils.get_model_category_dir('flash_classifier'),
                gh_proxy=self.ctx.env_config.is_gh_proxy,
                gh_proxy_url=self.ctx.env_config.gh_proxy_url if self.ctx.env_config.is_gh_proxy else None,
                personal_proxy=self.ctx.env_config.personal_proxy if self.ctx.env_config.is_personal_proxy else None,
                gpu=use_gpu
            )
            self._flash_model_settings = model_settings

    def init_battle_dodge_context(
            self,
    ) -> None:
        """
        初始化上下文，在运行前调用。
        """
        # 上一次识别的时间
        self._last_check_dodge_time = 0
        self._last_check_audio_time = 0
        self._reset_warning_gate()

        # 异步加载音频模板
        with self._audio_template_lock:
            if self._audio_template is None and (
                    self._audio_template_future is None or self._audio_template_future.done()):
                self._audio_template_future = _dodge_check_executor.submit(self.init_audio_template)
                self._audio_template_future.add_done_callback(thread_utils.handle_future_result)

    def init_audio_template(self) -> None:
        """
        加载音频模板。
        """
        if self._audio_template is not None:
            return
        log.info('加载声音模板中')
        self._audio_template = load_wav(os.path.join(
            os_utils.get_path_under_work_dir('assets', 'template', 'dodge_audio'),
            'template_1.wav'
        ), 32000)

        self._audio_template = self._get_filter_wave(self._audio_template)  # 滤波

        log.info('加载声音模板完成')

    def check_dodge_flash(self, screen: MatLike, screenshot_time: float, audio_future: Future[bool] | None = None) -> bool:
        """
        识别画面是否有闪光。
        :param screen: 屏幕截图
        :param screenshot_time: 截图时间
        :param audio_future: 音频识别结果的Future对象
        :return: 是否应该闪避 （识别到闪光或者声音）
        """
        if not self._check_dodge_flash_lock.acquire(blocking=False):
            return False

        try:
            if screenshot_time - self._last_check_dodge_time < cal_utils.random_in_range(self._check_dodge_interval):
                # 还没有达到识别间隔
                return False

            self._last_check_dodge_time = screenshot_time

            result = self._flash_model.run(screen)
            state_name: str | None = None
            if result.class_idx == 1:
                state_name = YoloStateEventEnum.DODGE_RED.value
            elif result.class_idx == 2:
                state_name = YoloStateEventEnum.DODGE_YELLOW.value
            elif audio_future is not None:
                audio_result = audio_future.result()
                if audio_result:
                    state_name = YoloStateEventEnum.DODGE_AUDIO.value

            should_dodge = state_name is not None
            from src.diagnostics.recorder import record_event
            record_event('dodge_detection', event=state_name, class_idx=int(result.class_idx),
                         confidence=getattr(result, 'confidence', None),
                         captured_at=screenshot_time, age=time.time()-screenshot_time)
            listener = self.event_listener
            if listener is not None:
                # The assistant publishes while holding its lifecycle lock,
                # so disable/config changes cannot race a delayed publication.
                return listener(state_name, screenshot_time)
            return self._publish_warning(state_name, screenshot_time)
        except Exception:
            log.error('识别画面闪光失败', exc_info=True)
            return False
        finally:
            self._check_dodge_flash_lock.release()

    def check_dodge_audio(self, screenshot_time: float) -> bool:
        """
        识别音频是否有闪避提示。
        :param screenshot_time: 截图时间
        :return: 是否识别到音频提示
        """
        if not self._check_audio_lock.acquire(blocking=False):
            return False

        try:
            if screenshot_time - self._last_check_audio_time < cal_utils.random_in_range(self._check_audio_interval):
                # 还没有达到识别间隔
                return False
            if self._audio_template is None:
                return False
            self._last_check_audio_time = screenshot_time

            if self._audio_recorder.latest_audio.size == 0:
                return False

            corr = self.get_max_corr(self._audio_template, self._audio_recorder.latest_audio)
            # log.debug('声音相似度 %.2f' % corr)

            # 事件去重逻辑
            if corr > self._audio_recorder.trigger_threshold:
                if screenshot_time - self._last_audio_event_time < self._audio_event_interval:
                    return False
                self._last_audio_event_time = screenshot_time
                self._audio_recorder.clear_audio()
                return True

            return False
        except Exception:
            log.error('识别画面闪光失败', exc_info=True)
            return False
        finally:
            self._check_audio_lock.release()

    def get_max_corr(self, x: np.ndarray, y: np.ndarray):
        """
        计算两个音频信号的最大相关性。
        :param x: 音频信号x
        :param y: 音频信号y
        :return: 最大相关性系数
        """
        y = self._get_filter_wave(y)  # 滤波

        # 标准化
        wx = scale_by_std(x)
        wy = scale_by_std(y)

        from scipy.signal import correlate
        if wx.shape[0] > wy.shape[0]:
            correlation = correlate(wx, wy, mode='same', method='fft') / wx.shape[0]
        else:
            correlation = correlate(wy, wx, mode='same', method='fft') / wy.shape[0]

        max_corr = np.max(correlation)

        return max_corr

    def _get_filter_wave(self, x: np.ndarray):
        """
        音频滤波。
        :param x: 音频信号x
        :return: 滤波后波形
        """
        from scipy.signal import filtfilt
        b, a = self._audio_recorder.filter_coefficients
        return filtfilt(b, a, x)

    def start_context_async(self) -> None:
        """
        启动上下文，启动音频录制。
        """
        self._audio_recorder.start_running_async()

    def stop_context(self) -> None:
        """
        停止上下文，停止音频录制。
        """
        self._audio_recorder.stop_running()

    def after_app_shutdown(self) -> None:
        """
        App关闭后进行的操作 关闭一切可能资源操作
        """
        self.stop_context()
        self.event_listener = None
        _dodge_check_executor.shutdown(wait=False, cancel_futures=True)
