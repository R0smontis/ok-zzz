"""Error reports: recorded from failure notifications, built locally, sent only on confirmation."""
import json
import os
import zipfile
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QWidget

from src.diagnostics import error_report
from src.diagnostics.error_report import FailureRegistry, build_report, issue_url


def frame_with_uid():
    frame = np.full((1080, 1920, 3), 90, np.uint8)
    frame[1065:1080, 1830:1920] = 255  # UID text area
    return frame


def test_one_failure_reported_twice_is_one_record():
    registry = FailureRegistry()
    task = SimpleNamespace(name='🐉 一条龙日常', info={'执行结果': '失败'}, config={'启用应用': ['邮件']})
    # The task's log_error(notify) carries the screenshot but no title; the executor then names it.
    first = registry.record('一条龙运行失败：体力刷本', task=task, frame=frame_with_uid(), now=100)
    second = registry.record('一条龙运行失败：体力刷本', task_name='🐉 一条龙日常', now=101)
    assert first is second and registry.all() == [first]
    assert first.task_name == '🐉 一条龙日常' and first.frame is not None
    assert first.config == {'启用应用': ['邮件']}
    registry.record('其它错误', task_name='⚡ 体力刷本', now=200)
    assert len(registry.all()) == 2 and registry.latest().task_name == '⚡ 体力刷本'


def test_report_masks_uid_and_strips_secrets(tmp_path):
    home = os.path.expanduser('~')
    (tmp_path/'logs').mkdir()
    (tmp_path/'debug/live').mkdir(parents=True)
    (tmp_path/'debug/live/session.json').write_text(json.dumps({'token': 'SESSIONTOKEN12345'}))
    (tmp_path/'logs/ok-script.log').write_text(
        f'INFO path {home}\\ok-zzz\nINFO password=hunter22 used\nINFO live SESSIONTOKEN12345\nERROR 体力刷本失败\n',
        encoding='utf-8')
    failure = error_report.Failure(time=1792400000, task_name='⚡ 体力刷本', message='恶名狩猎失败',
        task_class='App_ChargePlan', config={'plan_list': '[]', 'password': 'pw', 'account': 'me'},
        frame=frame_with_uid())
    archive = build_report(failure, tmp_path, version='v0.2.2')
    assert archive.parent == tmp_path/'debug/reports' and archive.suffix == '.zip'
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        top = names[0].split('/')[0]
        log = bundle.read(f'{top}/logs/ok-script.log').decode('utf-8')
        report = json.loads(bundle.read(f'{top}/report.json'))
        import cv2
        image = cv2.imdecode(np.frombuffer(bundle.read(f'{top}/screenshot.jpg'), np.uint8), cv2.IMREAD_COLOR)
    assert home not in log and '%USERPROFILE%' in log
    assert 'hunter22' not in log and 'SESSIONTOKEN12345' not in log and '体力刷本失败' in log
    assert report['task_config'] == {'plan_list': '[]', 'password': '***', 'account': '***'}
    assert report['system']['version'] == 'v0.2.2' and report['error'] == '恶名狩猎失败'
    assert image[1062:1080, 1820:1920].max() < 20  # UID masked
    assert image[500, 500].mean() > 60
    assert not any('session.json' in n or 'game_account' in n for n in names)
    assert failure.frame[1070, 1900].max() == 255  # The recorded frame itself is untouched.


def test_issue_link_is_prefilled_and_short(tmp_path):
    failure = error_report.Failure(time=1792400000, task_name='🐉 一条龙日常', message='失败：' + 'x' * 2000)
    url = issue_url(failure, 'https://github.com/R0smontis/ok-zzz/', tmp_path/'r.zip', 'v0.2.2')
    parsed = urlparse(url)
    assert parsed.path == '/R0smontis/ok-zzz/issues/new'
    query = parse_qs(parsed.query)
    assert query['title'][0].startswith('[错误报告] 🐉 一条龙日常：失败')
    body = query['body'][0]
    assert 'r.zip' in body and 'v0.2.2' in body and len(body) < 1500
    assert len(url) < 8000


@pytest.fixture
def reporting_ui(tmp_path, monkeypatch):
    qt = QApplication.instance() or QApplication([])
    from ok import og
    from onedragon.utils import os_utils
    from src.tasks import error_report_ui as ui
    registry = FailureRegistry()
    monkeypatch.setattr(ui, 'registry', registry)
    monkeypatch.setattr(error_report, 'registry', registry)
    task = SimpleNamespace(name='🐉 一条龙日常', info={}, config={'启用应用': ['邮件']})
    monkeypatch.setattr(og, 'executor', SimpleNamespace(get_all_tasks=lambda: [task], current_task=None,
                                                        _frame=frame_with_uid()))
    monkeypatch.setattr(og, 'app', SimpleNamespace(tr=lambda text: text))
    monkeypatch.setattr(og, 'config', {'version': 'v0.2.2',
                                       'links': {'default': {'github': 'https://github.com/o/r'}}})
    monkeypatch.setattr(os_utils, 'get_work_dir', lambda: str(tmp_path))
    opened, revealed = [], []
    monkeypatch.setattr(ui.QDesktopServices, 'openUrl', lambda url: opened.append(url.toString()))
    monkeypatch.setattr(ui, 'reveal', lambda path: revealed.append(path))
    window = QWidget()
    window.resize(1000, 700)
    window.navigate_tab = lambda *_: None
    yield ui, registry, window, opened, revealed
    window.deleteLater()
    qt.processEvents()


def test_error_notification_bar_offers_the_report_button(reporting_ui, monkeypatch):
    from ok.ui.qt.MainWindow import MainWindow
    from qfluentwidgets import PushButton
    ui, registry, window, _, _ = reporting_ui
    monkeypatch.setattr(MainWindow, 'show_notification', MainWindow.show_notification)
    from ok.ui.qt.util import app as app_util
    monkeypatch.setattr(app_util, 'show_info_bar', app_util.show_info_bar)
    ui.install_error_reports()
    MainWindow.show_notification(window, '一条龙运行失败', '🐉 一条龙日常', True)
    buttons = [b for b in window.findChildren(PushButton) if b.text() == ui.BUTTON_TEXT]
    assert len(buttons) == 1
    assert registry.latest().task_name == '🐉 一条龙日常' and registry.latest().frame is not None
    MainWindow.show_notification(window, 'Start Success.', None, False)  # Not a failure: no button.
    assert len([b for b in window.findChildren(PushButton) if b.text() == ui.BUTTON_TEXT]) == 1
    assert len(registry.all()) == 1


@pytest.mark.parametrize('confirm', [True, False])
def test_report_is_only_sent_after_confirmation(reporting_ui, monkeypatch, tmp_path, confirm):
    ui, registry, window, opened, revealed = reporting_ui
    panel = ui.ErrorReportPanel(window)
    assert not panel.send_button.isEnabled()
    ui.record_notification('一条龙运行失败：体力刷本', '🐉 一条龙日常')
    assert panel.send_button.isEnabled() and '体力刷本' in panel.status_label.text()
    monkeypatch.setattr(ui.MessageBox, 'exec', lambda self: confirm)
    archive = panel.send()
    assert archive.exists() and archive.parent == tmp_path/'debug/reports'  # Built locally either way.
    if confirm:
        assert len(opened) == 1 and opened[0].startswith('https://github.com/o/r/issues/new?')
        assert revealed == [archive]
    else:
        assert opened == [] and revealed == []
