import json
import sys
import types
from pathlib import Path


def test_worker_integration_end_to_end(monkeypatch, tmp_path: Path):
    # Stub googleapiclient modules before importing worker
    ga = types.ModuleType("googleapiclient")
    ga_discovery = types.ModuleType("googleapiclient.discovery")
    ga_errors = types.ModuleType("googleapiclient.errors")
    ga_http = types.ModuleType("googleapiclient.http")
    class _StubResumableUploadError(Exception):
        pass
    ga_errors.ResumableUploadError = _StubResumableUploadError
    sys.modules['googleapiclient'] = ga
    sys.modules['googleapiclient.discovery'] = ga_discovery
    sys.modules['googleapiclient.errors'] = ga_errors
    sys.modules['googleapiclient.http'] = ga_http

    from src import worker

    # Create minimal config file (disable subtitles, disable multi-accounts)
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

    # Create task with user-provided metadata to avoid AI generation
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

    # Stub credentials and upload
    monkeypatch.setattr(worker, "get_credentials", lambda *a, **k: object())
    monkeypatch.setattr(worker, "get_best_thumbnail", lambda *a, **k: None)
    monkeypatch.setattr(worker, "smart_upload_captions", lambda *a, **k: {})

    def fake_upload(creds, **kwargs):
        return {"id": "vid_worker_123"}

    monkeypatch.setattr(worker, "upload_video", fake_upload)

    # Run the worker once
    worker.process_queue(
        queue_dir=str(queue_dir),
        archive_dir=str(archive_dir),
        config_path=str(cfg_path),
        log_level="INFO",
    )

    # Verify task moved to archive and marked done
    archived = archive_dir / task_path.name
    assert archived.exists(), "Task should be moved to archive"
    data = json.loads(archived.read_text(encoding="utf-8"))
    assert data.get("status") == "done"
    assert data.get("youtube_id") == "vid_worker_123"
