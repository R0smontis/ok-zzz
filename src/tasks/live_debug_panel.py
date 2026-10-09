"""Live-monitor actions and preview on the existing debug sidebar page."""
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy
from qfluentwidgets import PrimaryPushButton, PushButton, ComboBox, BodyLabel
from ok import og


class LiveDebugPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.service = None
        self.last_frame = 0
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout = QVBoxLayout(self)
        self.description = BodyLabel('实时查看游戏画面、识别结果、任务进度和日志；接管控制会停止自动任务。', self)
        self.description.setWordWrap(True)
        layout.addWidget(self.description)
        buttons = QHBoxLayout()
        self.start_button = PrimaryPushButton('开始监控', self)
        self.mode = ComboBox(self)
        self.mode.addItems(['手柄后台', '窗口消息后台'])
        self.acquire_button = PushButton('接管控制', self)
        self.release_button = PushButton('释放控制', self)
        self.stop_button = PushButton('停止监控', self)
        for widget in (self.start_button, self.stop_button):
            buttons.addWidget(widget)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        control_buttons = QHBoxLayout()
        for widget in (self.mode, self.acquire_button, self.release_button):
            control_buttons.addWidget(widget)
        control_buttons.addStretch(1)
        layout.addLayout(control_buttons)
        self.status_label = BodyLabel('未启动', self)
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.status_label)
        self.preview = QLabel(self)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(120)
        self.preview.setMaximumHeight(270)
        self.preview.setToolTip('调试截图坐标统一为1920×1080；监控不改变前台窗口和系统光标')
        layout.addWidget(self.preview)
        self.start_button.clicked.connect(self.start)
        self.stop_button.clicked.connect(self.stop)
        self.acquire_button.clicked.connect(self.acquire)
        self.release_button.clicked.connect(self.release)
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        # A read-only endpoint is available after normal software startup.
        if callable(getattr(getattr(og, 'my_app', None), '_window_provider', None)):
            self.start()

    def start(self):
        if self.service is not None and self.service.started:
            return
        from src.live.service import LiveDebugService
        from src.live.runtime import GameRuntime, GuiCalls
        from onedragon.utils import os_utils
        try:
            self.gui = GuiCalls(self)
            adapter = GameRuntime(og.my_app, self.gui)
            self.service = LiveDebugService(adapter, Path(os_utils.get_work_dir()) / 'debug/live')
            adapter.service = self.service
            self.service.start()
            og.my_app.live_debug = self.service
            og.executor._live_debug = self.service
        except Exception as error:
            self.status_label.setText(f'实时监控启动失败：{error}')
        self.refresh()

    def stop(self):
        if self.service is not None:
            self.service.stop()
        self.preview.clear()
        self.last_frame = 0
        self.refresh()

    def acquire(self):
        try:
            self.service.submit({'op': 'acquire', 'mode': 'gamepad' if self.mode.currentIndex() == 0 else 'messages'})
        except Exception as error:
            self.status_label.setText(str(error))

    def release(self):
        if self.service is not None:
            self.service.release('用户释放控制')
        self.refresh()

    def refresh(self):
        service = self.service
        started = service is not None and service.started
        self.start_button.setEnabled(not started)
        self.stop_button.setEnabled(started)
        self.acquire_button.setEnabled(started and not service.owned)
        self.release_button.setEnabled(started and service.owned)
        if not started:
            self.status_label.setText('监控已停止')
            return
        status = service.status()
        frame = status['frame']
        self.status_label.setText(('已接管控制' if status['control'] else '只读监控') +
            f' · {service.url}\n' + (status['capture_error'] or
            (f'画面 #{frame["id"]} · {frame["source_size"][0]}×{frame["source_size"][1]} · '
             f'帧龄 {frame["age_seconds"]} 秒' if frame else '等待游戏画面')))
        # Show command failures in-place without modal interruptions.
        errors = [e for e in service.event_list()['events'] if e['kind'] == 'command_result'
                  and e['job']['state'] == 'error']
        if errors:
            self.status_label.setToolTip(errors[-1]['job']['error'])
            if __import__('time').time()-errors[-1]['time'] < 10:
                self.status_label.setText(self.status_label.text()+'\n'+errors[-1]['job']['error'])
        # Hidden pages keep monitoring, but need no JPEG/Qt preview work.
        if (self.isVisible() and not self.window().isMinimized()
                and frame and frame['id'] != self.last_frame):
            try:
                data, frame_id = service.screenshot(frame['id'], preview=True)
                image = QImage.fromData(data)
                self.preview.setPixmap(QPixmap.fromImage(image).scaled(
                    max(120, self.width()-24), 270, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                self.last_frame = frame_id
            except Exception:
                self.preview.clear()
