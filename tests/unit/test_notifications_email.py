"""Unit tests for email notifications in worker"""
from __future__ import annotations

import importlib
import os
import sys
import types
from unittest.mock import MagicMock, patch


def _stub_googleapiclient():
    ga = types.ModuleType("googleapiclient")
    ga_discovery = types.ModuleType("googleapiclient.discovery")
    ga_errors = types.ModuleType("googleapiclient.errors")
    ga_http = types.ModuleType("googleapiclient.http")
    sys.modules["googleapiclient"] = ga
    sys.modules["googleapiclient.discovery"] = ga_discovery
    sys.modules["googleapiclient.errors"] = ga_errors
    sys.modules["googleapiclient.http"] = ga_http


def test_notify_email_sends_message(monkeypatch):
    _stub_googleapiclient()
    worker = importlib.import_module("src.worker")

    email_cfg = {
        "enabled": True,
        "host": "smtp.example.com",
        "port": 587,
        "tls": True,
        "username": "user@example.com",
        "password": "secret",
        "from": "sender@example.com",
        "to": ["rcpt1@example.com", "rcpt2@example.com"],
    }

    mock_server = MagicMock()

    class _SMTP:
        def __init__(self, host, port, timeout):
            assert host == "smtp.example.com"
            assert port == 587
            assert timeout == 15
        def __enter__(self):
            return mock_server
        def __exit__(self, *args):
            return False

    with patch("smtplib.SMTP", _SMTP):
        worker._notify_email(email_cfg, "Sujet", "Corps")

    # TLS, login, send_message must be called
    mock_server.starttls.assert_called()
    mock_server.login.assert_called_with("user@example.com", "secret")
    assert mock_server.send_message.call_count == 1


def test_notify_email_uses_env_password(monkeypatch):
    _stub_googleapiclient()
    worker = importlib.import_module("src.worker")

    os.environ["SMTP_PASSWORD"] = "env_secret"
    email_cfg = {
        "enabled": True,
        "host": "smtp.example.com",
        "port": 587,
        "tls": True,
        "username": "user@example.com",
        "password_env": "SMTP_PASSWORD",
        "from": "sender@example.com",
        "to": "rcpt@example.com",
    }

    mock_server = MagicMock()

    class _SMTP:
        def __init__(self, host, port, timeout):
            pass
        def __enter__(self):
            return mock_server
        def __exit__(self, *args):
            return False

    with patch("smtplib.SMTP", _SMTP):
        worker._notify_email(email_cfg, "Sujet", "Corps")

    mock_server.login.assert_called_with("user@example.com", "env_secret")
    assert mock_server.send_message.call_count == 1
