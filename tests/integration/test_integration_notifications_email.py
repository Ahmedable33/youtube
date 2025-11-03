"""Integration test: worker sends email after successful upload"""

from __future__ import annotations

from pathlib import Path
import json
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


def test_worker_sends_email_after_upload(tmp_path: Path, monkeypatch):
    _stub_googleapiclient()
    from src import worker

    # Config minimale YAML-like JSON for simplicity
    cfg = {
        "privacy_status": "public",
        "language": "fr",
        "enhance": {"enabled": False},
        "subtitles": {"enabled": False},
        "seo": {"provider": "none"},
        "multi_accounts": {"enabled": False},
        "vision": {"enabled": False},
        "notifications": {
            "email": {
                "enabled": True,
                "host": "smtp.example.com",
                "port": 587,
                "tls": True,
                "username": "user@example.com",
                "password": "secret",
                "from": "sender@example.com",
                "to": ["rcpt@example.com"],
            }
        },
    }
    cfg_path = tmp_path / "video.yaml"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

    # Préparer dirs
    queue_dir = tmp_path / "queue"
    archive_dir = tmp_path / "queue_archive"
    queue_dir.mkdir()
    archive_dir.mkdir()

    # Vidéo factice
    video = tmp_path / "video.mp4"
    video.write_bytes(b"\x00\x00fakevideo")

    # Tâche de base
    task = {
        "video_path": str(video),
        "status": "pending",
        "meta": {
            "title": "Email After Upload",
            "description": "Desc",
            "tags": ["x"],
        },
        "skip_enhance": True,
    }
    task_path = queue_dir / "task_001.json"
    task_path.write_text(json.dumps(task), encoding="utf-8")
    mock_server = MagicMock()

    class _SMTP:
        def __init__(self, host, port, timeout):
            assert host == "smtp.example.com"
            assert port == 587

        def __enter__(self):
            return mock_server

        def __exit__(self, *args):
            return False

    def mock_upload(*args, **kwargs):
        return {"id": "vid_email"}

    # Stubs
    monkeypatch.setattr(worker, "get_credentials", lambda *a, **k: object())
    monkeypatch.setattr(worker, "get_best_thumbnail", lambda *a, **k: None)
    monkeypatch.setattr(worker, "upload_video", mock_upload)

    with patch("smtplib.SMTP", _SMTP):
        with patch("pathlib.Path.exists", return_value=True):
            # Run worker
            worker.process_queue(
                queue_dir=str(queue_dir),
                archive_dir=str(archive_dir),
                config_path=str(cfg_path),
                log_level="INFO",
            )

    # Verify email sent once
    assert mock_server.send_message.call_count == 1
