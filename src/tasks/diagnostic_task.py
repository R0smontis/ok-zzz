"""Passive diagnostic recording alongside resident assistants or stage scripts."""
import math

from ok import TriggerTask
from onedragon.utils import os_utils
from src.diagnostics import install_frame_observer, recorder, runtime_snapshot, VIDEO_FPS, VIDEO_RESOLUTIONS
from src.tasks.zzz_base_task import ZzzBaseTask


class DiagnosticRecordingTask(ZzzBaseTask, TriggerTask):
    recording_controls = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '🛠️ 画面与日志诊断'
        self.description = '持续录制直到手动停止；支持暂停和继续，保存画面、运行事件、用户键鼠日志及ZIP'
        self.visible = False
        self.debug_tool = True
        self.trigger_interval = 0.1
        self.default_config.update({'_enabled': False, '录制方式': '截图和视频',
                                    '录制时长秒': 0, '截图间隔秒': 1.0, '视频帧率': 10,
                                    '视频分辨率': '720P',
                                    '记录用户输入': True, '_recording_controls_version': 0})
        self.config_type.update({
            '录制方式': {'type': 'drop_down', 'options': ['截图', '视频', '截图和视频']},
            '视频帧率': {'type': 'drop_down', 'options': list(VIDEO_FPS), 'localized_choices': True,
                         'option_labels': {fps: f'{fps} 帧/秒' for fps in VIDEO_FPS}},
            '视频分辨率': {'type': 'drop_down', 'options': list(VIDEO_RESOLUTIONS), 'localized_choices': True,
                           'option_labels': {name: f'{name}（{w}×{h}）' for name, (w, h) in VIDEO_RESOLUTIONS.items()}},
        })
        self.config_description.update({
            '录制方式': '保存游戏截图、视频及运行日志；编码器不可用时继续保存截图与日志',
            '录制时长秒': '0表示不限时，持续到手动停止；也可填写5秒以上的定时长度，暂停不计时',
            '截图间隔秒': '0.2～5 秒，最多 300 张截图；不影响现有任务的识别间隔',
            '视频帧率': '输出每秒5～60帧；画面取自任务截图，采集不足时复用最新画面并标注帧龄',
            '视频分辨率': '选择输出视频大小，最高1920×1080；保留画面比例，时间信息显示在画面下方',
            '记录用户输入': '记录游戏前台时的物理键鼠按下/释放/移动/滚轮；切到其它窗口时不记录，结束录制即停止监听',
        })

    def validate_config(self, key, value):
        if key in ('录制时长秒', '截图间隔秒'):
            low, high = (5, math.inf) if key == '录制时长秒' else (0.2, 5)
            try:
                number = float(value)
                valid = not isinstance(value, bool) and math.isfinite(number) and (low <= number <= high
                    or (key == '录制时长秒' and number == 0))
            except (TypeError, ValueError):
                valid = False
            if not valid:
                return '录制时长请填写0（不限时）或至少5秒' if key == '录制时长秒' else f'{key}应在 {low}～{high} 之间'
        elif key == '视频帧率' and (isinstance(value, bool) or not isinstance(value, int) or value not in VIDEO_FPS):
            return '视频帧率请选择 5、10、15、24、30 或 60'
        elif key == '视频分辨率' and value not in VIDEO_RESOLUTIONS:
            return '视频分辨率请选择 480P、720P 或 1080P'
        elif key == '录制方式' and value not in ('截图', '视频', '截图和视频'):
            return '请选择有效录制方式'

    def on_create(self):
        super().on_create()
        # The user's new recording policy applies to existing installations too.
        if self.config.get('_recording_controls_version', 0) < 2:
            self.config['录制时长秒'] = 0
            self.config['_recording_controls_version'] = 2
        # Never resume recording automatically from a previous saved checkbox.
        self._enabled = False
        self.config['_enabled'] = False
        install_frame_observer(self.executor)

    def enable(self):
        if self.enabled:
            return
        for key in ('录制时长秒', '截图间隔秒', '录制方式', '视频帧率', '视频分辨率'):
            error = self.validate_config(key, self.config[key])
            if error:
                self.log_error(error, notify=True)
                return
        try:
            folder = recorder.start(os_utils.get_work_dir(), duration=self.config['录制时长秒'],
                image_interval=self.config['截图间隔秒'], mode=self.config['录制方式'],
                fps=self.config['视频帧率'], resolution=self.config['视频分辨率'],
                snapshot_provider=lambda: runtime_snapshot(self.executor),
                on_finished=self._on_recording_finished,
                input_hwnd_provider=self._input_hwnd,
                input_enabled_provider=lambda: bool(self.config.get('记录用户输入', False)))
            self.enable_passive_trigger()
            self.info.update({'诊断状态': '录制中（未运行时按 F9 开始采集）', '保存目录': folder})
        except Exception as exc:
            self.log_error(f'诊断录制启动失败：{exc}', notify=True)

    def disable(self):
        if self.enabled:
            recorder.stop()
        super().disable()
        self._refresh_info()

    @property
    def recording_status(self):
        return recorder.status

    def pause(self):
        if recorder.pause():
            self._refresh_info()
            self._notify_controls()

    def unpause(self):
        if recorder.resume():
            self._refresh_info()
            self._notify_controls()

    def _notify_controls(self):
        from ok.core.events import communicate
        communicate.task.emit(self)

    def _refresh_info(self):
        status = recorder.status
        self.info.update({'诊断状态': status['state'], '截图样本': status.get('images', 0),
                          '已录制秒': status.get('elapsed', 0),
                          '录制时长秒': status.get('duration', self.config['录制时长秒']),
                          '视频帧数': status.get('video_frames', 0), '事件记录': status.get('events', 0),
                          '视频规格': f'{status.get("resolution", self.config["视频分辨率"])} '
                                      f'{status.get("fps", self.config["视频帧率"])} 帧/秒',
                          '用户输入记录': status.get('user_inputs', 0),
                          '保存目录': status.get('folder'), '诊断包': status.get('archive'),
                          '错误': status.get('error') or status.get('input_error') or '无'})

    def _input_hwnd(self):
        window = getattr(getattr(self.executor, 'device_manager', None), 'hwnd_window', None)
        return getattr(window, 'hwnd', 0)

    def _on_recording_finished(self):
        self._refresh_info()
        super().disable()

    def should_trigger(self):
        self.trigger_interval = 1 / int(self.config['视频帧率'])
        return self.enabled and not recorder.paused and super().should_trigger()

    def run(self):
        self._refresh_info()
        if not recorder.active and not recorder.paused:
            super().disable()
        # Frames are observed in executor.next_frame, including during onetime tasks.

    def on_destroy(self):
        recorder.stop('软件退出', wait=True)
        super().on_destroy()
