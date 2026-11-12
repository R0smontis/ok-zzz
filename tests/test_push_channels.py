"""推送渠道契约：validate_config 必须返回二元组，SMTP 连接必须带超时。

回归背景：删除 push_merged 时把 validate_config 末尾的 `return True, "配置验证通过"`
一并删掉，push() 解包 None 抛 TypeError，导致 SMTP / OneBot 推送全部失败。
"""
import pytest

import onedragon.base.push.channel.smtp as smtp_module
from onedragon.base.push.channel.one_bot import OneBot
from onedragon.base.push.channel.smtp import Smtp

SMTP_CONFIG = {
    'SERVER': 'smtp.example.com:465',
    'SSL': 'true',
    'STARTTLS': 'false',
    'EMAIL': 'sender@example.com',
    'PASSWORD': 'secret',
    'NAME': 'OkZzz',
}
ONEBOT_CONFIG = {'URL': 'http://127.0.0.1:5700', 'USER': '10001', 'GROUP': ''}


@pytest.mark.parametrize('channel_cls', [Smtp, OneBot])
def test_validate_config_accepts_valid_config(channel_cls):
    config = SMTP_CONFIG if channel_cls is Smtp else ONEBOT_CONFIG

    ok, msg = channel_cls().validate_config(config)

    assert ok is True
    assert isinstance(msg, str)


def test_validate_config_rejects_missing_server():
    ok, msg = Smtp().validate_config({**SMTP_CONFIG, 'SERVER': ''})

    assert ok is False
    assert isinstance(msg, str)


def test_smtp_connection_uses_timeout(monkeypatch):
    calls = []

    class _Recorder:
        def __init__(self, host, port, **kwargs):
            calls.append((host, port, kwargs))
            raise OSError('recorded')

    monkeypatch.setattr(smtp_module.smtplib, 'SMTP_SSL', _Recorder)
    monkeypatch.setattr(smtp_module.smtplib, 'SMTP', _Recorder)

    ok, _ = Smtp().push(SMTP_CONFIG, '标题', '内容')

    assert ok is False
    assert calls[0][2].get('timeout') == 30
