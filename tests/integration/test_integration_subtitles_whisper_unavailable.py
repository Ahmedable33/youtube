import json
import sys
import types
from pathlib import Path


def test_worker_subtitles_whisper_unavailable(monkeypatch, tmp_path: Path):
    # Stub googleapiclient modules
    ga = types.ModuleType("googleapiclient")
    ga_discovery = types.ModuleType("googleapiclient.discovery")
    ga_errors = types.ModuleType("googleapiclient.errors")
    ga_http = types.ModuleType("googleapiclient.http")
    class _StubResumableUploadError(Exception):
        pass
    ga_errors.ResumableUploadError = _StubResumableUploadError
    class _StubHttpError(Exception):
        def __init__(self, *args, **kwargs):
            self.resp = types.SimpleNamespace(status=403)
            super().__init__(*args)
    ga_errors.HttpError = _StubHttpError
    def _stub_build(*args, **kwargs):
        class _Svc:
            pass
        return _Svc()
    ga_discovery.build = _stub_build
    class _StubMediaFileUpload:
        def __init__(self, *args, **kwargs):
            pass
    ga_http.MediaFileUpload = _StubMediaFileUpload
    sys.modules['googleapiclient'] = ga
    sys.modules['googleapiclient.discovery'] = ga_discovery
    sys.modules['googleapiclient.errors'] = ga_errors
    sys.modules['googleapiclient.http'] = ga_http

    from src import worker

    # Config enabling subtitles
    cfg = {
        "privacy_status": "private",
        "language": "fr",
        "enhance": {"enabled": False},
        "subtitles": {
            "enabled": True,
            "languages": ["fr", "en"],
            "auto_detect_language": True,
            "translate_to_english": True,
            "upload_to_youtube": True,
            "draft_mode": False,
            "replace_existing": False,
        },
        "seo": {"provider": "none"},
        "multi_accounts": {"enabled": False},
    }
    cfg_path = tmp_path / "video.json"

    queue_dir = tmp_path / "queue"
    archive_dir = tmp_path / "queue_archive"
    queue_dir.mkdir()
    archive_dir.mkdir()

    video = tmp_path / "video.mp4"
    video.write_bytes(b"\x00\x00fakevideo")
    cfg["video_path"] = str(video)
    cfg["title"] = "Titre"
    cfg["tags"] = []
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

    task = {
        "video_path": str(video),
        "status": "pending",
        "meta": {"title": "T", "description": "D", "tags": ["a"]},
        "skip_enhance": True,
    }
    task_path = queue_dir / "task_001.json"
    task_path.write_text(json.dumps(task), encoding="utf-8")

    # Monkeypatch creds, upload, and make whisper unavailable
    monkeypatch.setattr(worker, "get_credentials", lambda *a, **k: object())
    monkeypatch.setattr(worker, "upload_video", lambda *a, **k: {"id": "vid_no_whisper"})
    monkeypatch.setattr(worker, "is_whisper_available", lambda: False)

    worker.process_queue(
        queue_dir=str(queue_dir),
        archive_dir=str(archive_dir),
        config_path=str(cfg_path),
        log_level="INFO",
    )

    archived = archive_dir / task_path.name
    assert archived.exists()
    data = json.loads(archived.read_text(encoding="utf-8"))
    assert data.get("status") == "done"
    assert data.get("youtube_id") == "vid_no_whisper"
    # When whisper is unavailable, _process_subtitles returns early, no 'subtitles' field required
    assert "subtitles" not in data or isinstance(data.get("subtitles"), dict)
