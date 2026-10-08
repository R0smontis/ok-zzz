"""Recording actions on the diagnostic card, independent of game-task controls."""
from importlib import import_module

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QWidget
from qfluentwidgets import FluentIcon, PrimaryPushButton, PushButton
from ok.ui.qt.common.OKIcon import OKIcon


class DiagnosticControls(QWidget):
    def __init__(self, card):
        super().__init__(card.button_container)
        self.card = card
        self.task = card.task
        self.start_button = PrimaryPushButton(FluentIcon.PLAY, '开始录制', self)
        self.pause_button = PushButton(FluentIcon.PAUSE, '暂停录制', self)
        self.stop_button = PushButton(OKIcon.STOP, '停止录制', self)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        for button in (self.start_button, self.pause_button, self.stop_button):
            layout.addWidget(button)
        self.start_button.clicked.connect(self.task.enable)
        self.pause_button.clicked.connect(self._toggle_pause)
        self.stop_button.clicked.connect(self.task.disable)
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def _toggle_pause(self):
        if self.task.recording_status.get('paused'):
            self.task.unpause()
        else:
            self.task.pause()
        self.refresh()

    @staticmethod
    def _time_label(value):
        minutes, seconds = divmod(max(0, int(value)), 60)
        return f'{minutes:02d}:{seconds:02d}'

    def refresh(self):
        status = self.task.recording_status
        state = status['state']
        recording = state == '录制中'
        paused = state == '已暂停'
        self.start_button.setEnabled(not (recording or paused or state == '保存中'))
        self.pause_button.setEnabled(recording or paused)
        self.stop_button.setEnabled(recording or paused)
        self.pause_button.setText('继续录制' if paused else '暂停录制')
        self.pause_button.setIcon(FluentIcon.PLAY if paused else FluentIcon.PAUSE)
        if state != '未开始':
            elapsed = self._time_label(status.get('elapsed', 0))
            duration = status.get('duration', 0)
            self.card.card.contentLabel.setText(f'{state} · {elapsed}' +
                (f' / {self._time_label(duration)}' if duration else ' · 不限时'))
        else:
            duration = self._time_label(self.task.config['录制时长秒'])
            self.card.card.contentLabel.setText(f'待录制 · 上限 {duration}' if self.task.config['录制时长秒']
                                               else '待录制 · 不限时，手动停止')
        self.card.card.contentLabel.setToolTip(self.task.description)
        self.stop_button.setToolTip('结束本轮录制并保存诊断包')
        self.pause_button.setToolTip('暂停画面和事件记录，冻结录制计时；游戏任务继续运行')


def install_diagnostic_controls():
    """Patch only marked recording cards; leave the dependency and other tasks intact."""
    task_card = import_module('ok.ui.qt.tasks.TaskCard').TaskCard
    if getattr(task_card, '_zzz_recording_controls', False):
        return
    original_init = task_card.__init__
    original_update = task_card.update_buttons
    original_dispose = task_card.dispose

    def initialize(self, task, onetime):
        original_init(self, task, onetime)
        if not getattr(task, 'recording_controls', False):
            return
        switch = self.enable_button
        switch.checkedChanged.disconnect(self.check_changed)
        self.all_buttons.remove(switch)
        self.button_layout.removeWidget(switch)
        switch.hide()
        switch.setParent(None)
        switch.deleteLater()
        self.enable_button = None
        self.recording_controls = DiagnosticControls(self)
        self.all_buttons.append(self.recording_controls)
        self._rebuild_button_layout()

    def update(self, task):
        controls = getattr(self, 'recording_controls', None)
        if controls is None:
            return original_update(self, task)
        if task is self.task:
            controls.refresh()

    def dispose(self):
        controls = getattr(self, 'recording_controls', None)
        if controls is not None:
            controls.timer.stop()
        original_dispose(self)

    task_card.__init__ = initialize
    task_card.update_buttons = update
    task_card.dispose = dispose
    task_card._zzz_recording_controls = True
