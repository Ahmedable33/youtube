import json
import sys
import types
from pathlib import Path


def test_worker_blocks_on_upload_limit(monkeypatch, tmp_path: Path):
    # Stub googleapiclient modules before importing worker
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
    # Provide required attributes used by src.uploader import

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

    # Minimal config to avoid side effects
    cfg = {
        "privacy_status": "private",
        "language": "fr",
        "enhance": {"enabled": False},
        "subtitles": {"enabled": False},
        "seo": {"provider": "none"},
        "multi_accounts": {"enabled": False},
    }
    cfg_path = tmp_path / "video.yaml"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

    # Prepare queue and archive dirs
    queue_dir = tmp_path / "queue"
    archive_dir = tmp_path / "queue_archive"
    queue_dir.mkdir()
    archive_dir.mkdir()

    # Create dummy video
    video = tmp_path / "video.mp4"
    video.write_bytes(b"\x00\x00fakevideo")

    # Create task
    task = {
        "video_path": str(video),
        "status": "pending",
        "meta": {
            "title": "Titre Worker",
            "description": "Desc Worker",
            "tags": ["w1", "w2"],
        },
        "skip_enhance": True
    }
    task_path = queue_dir / "task_001.json"
    task_path.write_text(json.dumps(task), encoding="utf-8")

    # Stubs
    monkeypatch.setattr(worker, "get_credentials", lambda *a, **k: object())
    monkeypatch.setattr(worker, "get_best_thumbnail", lambda *a, **k: None)
    monkeypatch.setattr(worker, "smart_upload_captions", lambda *a, **k: {})
    # Replace the exception class inside worker to a simple one we can raise easily

    class _DummyResumable(Exception):
        pass
    monkeypatch.setattr(worker, "ResumableUploadError", _DummyResumable, raising=False)

    def raise_limit_error(*args, **kwargs):
        # Raise the same class symbol that worker imported (now monkeypatched)
        raise worker.ResumableUploadError("uploadLimitExceeded: daily limit reached")

    monkeypatch.setattr(worker, "upload_video", raise_limit_error)

    # Run
    worker.process_queue(
        queue_dir=str(queue_dir),
        archive_dir=str(archive_dir),
        config_path=str(cfg_path),
        log_level="INFO",
    )

    # Verify task blocked and archived
    archived = archive_dir / task_path.name
    assert archived.exists(), "Task should be moved to archive"
    data = json.loads(archived.read_text(encoding="utf-8"))
    assert data.get("status") == "blocked"
    assert data.get("error") == "uploadLimitExceeded"
    assert "blocked_at" in data
