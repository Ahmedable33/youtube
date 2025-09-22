import json
import sys
import types
from pathlib import Path


def test_worker_multi_tasks_stops_on_upload_limit(monkeypatch, tmp_path: Path):
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

    # Minimal config
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

    # Prepare dirs
    queue_dir = tmp_path / "queue"
    archive_dir = tmp_path / "queue_archive"
    queue_dir.mkdir()
    archive_dir.mkdir()

    # Create shared dummy video
    video = tmp_path / "video.mp4"
    video.write_bytes(b"\x00\x00fakevideo")

    # Create two tasks
    t1 = {
        "video_path": str(video),
        "status": "pending",
        "meta": {"title": "T1", "description": "D1", "tags": ["a"]},
        "skip_enhance": True,
    }
    t2 = {
        "video_path": str(video),
        "status": "pending",
        "meta": {"title": "T2", "description": "D2", "tags": ["b"]},
        "skip_enhance": True,
    }
    p1 = queue_dir / "task_001.json"
    p2 = queue_dir / "task_002.json"
    p1.write_text(json.dumps(t1), encoding="utf-8")
    p2.write_text(json.dumps(t2), encoding="utf-8")

    # Stubs
    monkeypatch.setattr(worker, "get_credentials", lambda *a, **k: object())
    monkeypatch.setattr(worker, "get_best_thumbnail", lambda *a, **k: None)
    monkeypatch.setattr(worker, "smart_upload_captions", lambda *a, **k: {})

    # Replace the exception class inside worker to a simple one we can raise easily
    class _DummyResumable(Exception):
        pass
    monkeypatch.setattr(worker, "ResumableUploadError", _DummyResumable, raising=False)

    calls = {"count": 0}
    def upload_side_effect(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            # First task triggers uploadLimitExceeded
            raise worker.ResumableUploadError("uploadLimitExceeded: daily limit reached")
        # Would succeed for subsequent calls, but worker should stop before calling again
        return {"id": "vid_ok"}

    monkeypatch.setattr(worker, "upload_video", upload_side_effect)

    # Run
    worker.process_queue(
        queue_dir=str(queue_dir),
        archive_dir=str(archive_dir),
        config_path=str(cfg_path),
        log_level="INFO",
    )

    # First task should be archived as blocked
    a1 = archive_dir / p1.name
    assert a1.exists(), "First task should be archived after uploadLimitExceeded"
    d1 = json.loads(a1.read_text(encoding="utf-8"))
    assert d1.get("status") == "blocked"
    assert d1.get("error") == "uploadLimitExceeded"

    # Second task should remain in queue (not processed), worker stopped
    assert (queue_dir / p2.name).exists(), "Second task should remain in queue"
    # And upload should have been attempted only once
    assert calls["count"] == 1
