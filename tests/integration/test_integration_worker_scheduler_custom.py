import json
import sys
import types
from datetime import datetime, timedelta
import pytz
from pathlib import Path


def _stub_google_api_modules():
    ga = types.ModuleType("googleapiclient")
    ga_discovery = types.ModuleType("googleapiclient.discovery")
    ga_errors = types.ModuleType("googleapiclient.errors")
    ga_http = types.ModuleType("googleapiclient.http")

    class _StubResumableUploadError(Exception):
        pass

    class _StubHttpError(Exception):
        def __init__(self, *args, **kwargs):
            self.resp = types.SimpleNamespace(status=403)
            super().__init__(*args)

    def _stub_build(*args, **kwargs):
        class _Svc:
            pass

        return _Svc()

    class _StubMediaFileUpload:
        def __init__(self, *args, **kwargs):
            pass

    ga_errors.ResumableUploadError = _StubResumableUploadError
    ga_errors.HttpError = _StubHttpError
    ga_discovery.build = _stub_build
    ga_http.MediaFileUpload = _StubMediaFileUpload

    sys.modules["googleapiclient"] = ga
    sys.modules["googleapiclient.discovery"] = ga_discovery
    sys.modules["googleapiclient.errors"] = ga_errors
    sys.modules["googleapiclient.http"] = ga_http


def test_worker_custom_future_schedules(monkeypatch, tmp_path: Path):
    _stub_google_api_modules()
    from src import worker
    from src.scheduler import UploadScheduler

    # Minimal cfg
    cfg = {
        "privacy_status": "private",
        "language": "fr",
        "enhance": {"enabled": False},
        "seo": {"provider": "none"},
        "multi_accounts": {"enabled": False},
    }
    cfg_path = tmp_path / "video.json"

    queue_dir = tmp_path / "queue"
    archive_dir = tmp_path / "queue_archive"
    schedule_dir = tmp_path / "schedule"
    queue_dir.mkdir()
    archive_dir.mkdir()
    schedule_dir.mkdir()

    video = tmp_path / "video.mp4"
    video.write_bytes(b"\x00\x00fakevideo")
    cfg["video_path"] = str(video)
    cfg["title"] = "Titre"
    cfg["tags"] = []
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

    # Task requesting custom schedule in the future
    tz = pytz.timezone("Europe/Paris")
    future_dt = datetime.now(tz) + timedelta(hours=2)
    task = {
        "video_path": str(video),
        "status": "pending",
        "meta": {"title": "Titre", "description": "D", "tags": []},
        "skip_enhance": True,
        "schedule_mode": "custom",
        "custom_schedule_time": future_dt.isoformat(),
    }
    task_path = queue_dir / "task_001.json"
    task_path.write_text(json.dumps(task), encoding="utf-8")

    # Spy on schedule_task
    called = {}
    orig_schedule_task = UploadScheduler.schedule_task

    def spy_schedule(self, task_path_arg, scheduled_time=None, preferred_days=None):
        called["task_path"] = str(task_path_arg)
        called["scheduled_time"] = scheduled_time
        return orig_schedule_task(self, task_path_arg, scheduled_time, preferred_days)

    monkeypatch.setattr(UploadScheduler, "schedule_task", spy_schedule)

    # Run
    worker.process_queue(
        queue_dir=str(queue_dir),
        archive_dir=str(archive_dir),
        config_path=str(cfg_path),
        log_level="INFO",
    )

    # Original task moved to archive
    archived = archive_dir / task_path.name
    assert archived.exists()

    # Scheduled file created with an entry
    sched_file = schedule_dir / "scheduled_tasks.json"
    assert sched_file.exists()
    data = json.loads(sched_file.read_text(encoding="utf-8"))
    assert isinstance(data, list) and len(data) >= 1

    # Spy captured time close to our expected future time
    assert "scheduled_time" in called and called["scheduled_time"] is not None
    delta = abs((called["scheduled_time"] - future_dt).total_seconds())
    assert (
        delta < 120
    ), f"scheduled_time differs too much: {called['scheduled_time']} vs {future_dt}"


def test_worker_custom_past_processes_immediately(monkeypatch, tmp_path: Path):
    _stub_google_api_modules()
    from src import worker

    # Minimal cfg
    cfg = {
        "privacy_status": "private",
        "language": "fr",
        "enhance": {"enabled": False},
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

    # Task with custom schedule time in the past
    tz = pytz.timezone("Europe/Paris")
    past_dt = datetime.now(tz) - timedelta(hours=2)
    task = {
        "video_path": str(video),
        "status": "pending",
        "meta": {"title": "Titre", "description": "D", "tags": []},
        "skip_enhance": True,
        "schedule_mode": "custom",
        "custom_schedule_time": past_dt.isoformat(),
    }
    task_path = queue_dir / "task_001.json"
    task_path.write_text(json.dumps(task), encoding="utf-8")

    # Stubs
    monkeypatch.setattr(worker, "get_credentials", lambda *a, **k: object())
    monkeypatch.setattr(worker, "upload_video", lambda *a, **k: {"id": "vid_now"})
    monkeypatch.setattr(worker, "get_best_thumbnail", lambda *a, **k: None)
    monkeypatch.setattr(worker, "smart_upload_captions", lambda *a, **k: {})

    # Run
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
    assert data.get("youtube_id") == "vid_now"


def test_worker_processes_scheduled_task_marks_completed(monkeypatch, tmp_path: Path):
    _stub_google_api_modules()
    from src import worker
    from src.scheduler import UploadScheduler

    # Minimal cfg
    cfg = {
        "privacy_status": "private",
        "language": "fr",
        "enhance": {"enabled": False},
        "seo": {"provider": "none"},
        "multi_accounts": {"enabled": False},
    }
    cfg_path = tmp_path / "video.json"

    queue_dir = tmp_path / "queue"
    archive_dir = tmp_path / "queue_archive"
    schedule_dir = tmp_path / "schedule"
    queue_dir.mkdir()
    archive_dir.mkdir()
    schedule_dir.mkdir()

    video = tmp_path / "video.mp4"
    video.write_bytes(b"\x00\x00fakevideo")
    cfg["video_path"] = str(video)
    cfg["title"] = "Titre"
    cfg["tags"] = []
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

    # Create a scheduled task file directly to simulate a ready scheduled task in queue
    scheduled_task = {
        "video_path": str(video),
        "status": "pending",
        "meta": {"title": "Titre", "description": "D", "tags": []},
        "skip_enhance": True,
        "scheduled_task_id": "sched_test_123",
    }
    sched_task_path = queue_dir / "scheduled_001.json"
    sched_task_path.write_text(json.dumps(scheduled_task), encoding="utf-8")

    # Spy mark_task_completed
    called = {}

    def spy_mark_completed(self, task_id: str):
        called["task_id"] = task_id
        return True

    monkeypatch.setattr(UploadScheduler, "mark_task_completed", spy_mark_completed)

    # Stubs
    monkeypatch.setattr(worker, "get_credentials", lambda *a, **k: object())
    monkeypatch.setattr(worker, "upload_video", lambda *a, **k: {"id": "vid_sched"})
    monkeypatch.setattr(worker, "get_best_thumbnail", lambda *a, **k: None)
    monkeypatch.setattr(worker, "smart_upload_captions", lambda *a, **k: {})

    # Run
    worker.process_queue(
        queue_dir=str(queue_dir),
        archive_dir=str(archive_dir),
        config_path=str(cfg_path),
        log_level="INFO",
    )

    # Verify uploaded and finalized
    archived = archive_dir / sched_task_path.name
    assert archived.exists()
    data = json.loads(archived.read_text(encoding="utf-8"))
    assert data.get("status") == "done"
    assert data.get("youtube_id") == "vid_sched"
    # And mark_task_completed called
    assert called.get("task_id") == "sched_test_123"
