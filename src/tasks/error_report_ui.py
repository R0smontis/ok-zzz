"""「发送错误报告」: a button on failure notifications and on the debug page.

Error notifications (a task's log_error(notify=True) or the executor's exception message) are
recorded as failures; their InfoBar gets the button. Clicking builds the local report, explains
what it contains, and only on confirmation opens the GitHub issue form and the report folder.
"""
import functools
import os
import subprocess
import time
from datetime import datetime

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, InfoBar, InfoBarPosition, MessageBox, PushButton
from PySide6.QtCore import Qt

from src.diagnostics.error_report import build_report, issue_url, registry

BUTTON_TEXT = '发送错误报告'
ERROR_BAR_MS = 20000
_pending = {'failure': None}


def _og():
    from ok import og
    return og


def _version():
    og = _og()
    config = getattr(og, 'config', None) or {}
    try:
        return config.get('version')
    except Exception:
        return None


def _repository():
    og = _og()
    try:
        return og.config['links']['default']['github']
    except Exception:
        from src.config import config
        return config['links']['default']['github']


def _work_dir():
    from onedragon.utils import os_utils
    return os_utils.get_work_dir()


def _task_for(title):
    executor = getattr(_og(), 'executor', None)
    if executor is None:
        return None
    tasks = list(executor.get_all_tasks()) if hasattr(executor, 'get_all_tasks') else []
    if title:
        found = next((t for t in tasks if getattr(t, 'name', None) == title), None)
        if found is not None:
            return found
    return getattr(executor, 'current_task', None)


def record_notification(message, title=None, images=None):
    """Record an error notification as a failure (GUI thread)."""
    og = _og()
    executor = getattr(og, 'executor', None)
    task = _task_for(title)
    frame = images[0] if images else getattr(executor, '_frame', None)
    runtime = {}
    try:
        from src.diagnostics.recorder import runtime_snapshot
        runtime = runtime_snapshot(executor) if executor is not None else {}
    except Exception:
        pass
    name = title or getattr(task, 'name', None)
    return registry.record(message, task_name=name, task=task, frame=frame, runtime=runtime)


def open_report_dialog(parent, failure):
    """Build the report, explain it, and on confirmation open the issue form and the folder."""
    try:
        archive = build_report(failure, _work_dir(), version=_version())
    except Exception as error:
        InfoBar.error(title='错误报告生成失败', content=str(error), orient=Qt.Horizontal,
                      isClosable=True, position=InfoBarPosition.TOP, duration=8000, parent=parent)
        return None
    box = MessageBox(BUTTON_TEXT, (
        f'已在本机生成错误报告：\n{archive}\n\n'
        '点击「前往提交」会打开 GitHub 新建问题页面（已填好错误信息）和报告所在文件夹，'
        '请把 ZIP 拖到问题描述里再提交；需要登录 GitHub 账号。\n\n'
        '报告包含：失败时的游戏画面（UID 已遮挡）、最近日志（已移除用户目录与密钥）、'
        '该任务的设置、软件版本与系统信息。不包含账号、密码和游戏账号配置。'), parent)
    box.yesButton.setText('前往提交')
    box.cancelButton.setText('取消')
    if box.exec():
        QDesktopServices.openUrl(QUrl(issue_url(failure, _repository(), archive, _version())))
        reveal(archive)
    return archive


def reveal(path):
    try:
        subprocess.Popen(['explorer', '/select,', os.path.normpath(str(path))])
    except OSError:
        pass


def report_button(parent, failure):
    button = PushButton(BUTTON_TEXT, parent)
    button.clicked.connect(lambda: open_report_dialog(parent.window() if parent else None, failure))
    return button


def install_error_reports():
    """Record error notifications and add the report button to their InfoBar (idempotent)."""
    from ok.ui.qt.MainWindow import MainWindow
    from ok.ui.qt.util import app as app_util
    if getattr(MainWindow.show_notification, '_zzz_error_reports', False):
        return
    original_show = MainWindow.show_notification
    original_bar = app_util.show_info_bar

    @functools.wraps(original_show)
    def show_notification(window, message, title=None, error=False, tray=False, show_tab=None,
                          params=None, images=None):
        failure = None
        if error:
            try:
                text = message.format(**params) if params else message
                failure = record_notification(text, title, images)
            except Exception:
                failure = None
        _pending['failure'] = failure
        try:
            return original_show(window, message, title, error, tray, show_tab, params, images)
        finally:
            _pending['failure'] = None

    @functools.wraps(original_bar)
    def show_info_bar(window, message, title=None, error=False):
        failure = _pending['failure']
        if not (error and failure is not None):
            return original_bar(window, message, title, error)
        from PySide6.QtCore import QCoreApplication
        title = QCoreApplication.translate('app', title) if title else '错误：'
        bar = InfoBar.error(title=title, content=QCoreApplication.translate('app', message),
                            orient=Qt.Horizontal, isClosable=True, position=InfoBarPosition.TOP,
                            duration=ERROR_BAR_MS, parent=window)
        bar.addWidget(report_button(bar, failure))
        return bar

    show_notification._zzz_error_reports = True
    MainWindow.show_notification = show_notification
    app_util.show_info_bar = show_info_bar


class ErrorReportPanel(QWidget):
    """Debug-page entry: the latest failure and the same button, for a bar that already faded."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.description = BodyLabel('任务运行失败后，可生成错误报告并提交给开发者；'
                                     '报告先保存在本机，确认后才会打开提交页面。', self)
        self.description.setWordWrap(True)
        layout.addWidget(self.description)
        self.status_label = BodyLabel('', self)
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.status_label)
        row = QHBoxLayout()
        self.send_button = PushButton(BUTTON_TEXT, self)
        self.send_button.clicked.connect(self.send)
        row.addWidget(self.send_button)
        row.addStretch(1)
        layout.addLayout(row)
        registry.listeners.append(self._on_failure)
        self.destroyed.connect(lambda *_: self._detach())
        self.refresh()

    def _detach(self):
        try:
            registry.listeners.remove(self._on_failure)
        except ValueError:
            pass

    def _on_failure(self, _failure):
        try:
            self.refresh()
        except RuntimeError:
            self._detach()  # Qt object already deleted.

    def refresh(self):
        failure = registry.latest()
        self.send_button.setEnabled(failure is not None)
        if failure is None:
            self.status_label.setText('本次运行暂无失败记录')
            return
        first = failure.message.splitlines()[0] if failure.message else ''
        when = datetime.fromtimestamp(failure.time).strftime('%H:%M:%S')
        self.status_label.setText(f'最近失败：{when} {failure.task_name}：{first[:120]}')

    def send(self):
        failure = registry.latest()
        if failure is not None:
            return open_report_dialog(self.window(), failure)
