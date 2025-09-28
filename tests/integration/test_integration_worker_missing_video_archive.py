import json
import sys
import types
from pathlib import Path


def test_worker_missing_video_archives_error(monkeypatch, tmp_path: Path):
    # Stub googleapiclient modules to satisfy src.uploader imports inside worker
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
    sys.modules["googleapiclient"] = ga
    sys.modules["googleapiclient.discovery"] = ga_discovery
    sys.modules["googleapiclient.errors"] = ga_errors
    sys.modules["googleapiclient.http"] = ga_http

    from src import worker

    # Prepare queue and archive dirs
    queue_dir = tmp_path / "queue"
    archive_dir = tmp_path / "queue_archive"
    queue_dir.mkdir()
    archive_dir.mkdir()

    # Create task with missing video path
    missing = tmp_path / "missing.mp4"  # do not create the file
    task = {
        "video_path": str(missing),
        "status": "pending",
        "meta": {"title": "Titre", "description": "D", "tags": []},
        "skip_enhance": True,
    }
    task_path = queue_dir / "task_001.json"
    task_path.write_text(json.dumps(task), encoding="utf-8")

    # Run worker without config_path to avoid ConfigError noise
    worker.process_queue(
        queue_dir=str(queue_dir),
        archive_dir=str(archive_dir),
        config_path=None,
        log_level="INFO",
    )

    # Verify task archived as error
    archived = archive_dir / task_path.name
    assert archived.exists(), "Missing video task should be archived"
    data = json.loads(archived.read_text(encoding="utf-8"))
    assert data.get("status") == "error"
    assert "Video not found" in data.get("error", "")
