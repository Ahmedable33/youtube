import json
import sys
import types
from pathlib import Path


def test_worker_auto_schedules_not_upload(monkeypatch, tmp_path: Path):
    # Stub googleapiclient minimal to satisfy imports if any occur indirectly
    ga = types.ModuleType("googleapiclient")
    ga_discovery = types.ModuleType("googleapiclient.discovery")
    ga_errors = types.ModuleType("googleapiclient.errors")
    ga_http = types.ModuleType("googleapiclient.http")
    sys.modules['googleapiclient'] = ga
    sys.modules['googleapiclient.discovery'] = ga_discovery
    sys.modules['googleapiclient.errors'] = ga_errors
    sys.modules['googleapiclient.http'] = ga_http

    from src import worker
    from src.scheduler import UploadScheduler

    # Minimal config
    cfg = {
        "privacy_status": "private",
        "language": "fr",
        "enhance": {"enabled": False},
        "seo": {"provider": "none"},
        "multi_accounts": {"enabled": False},
    }
    cfg_path = tmp_path / "video.yaml"

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

    # Task that requests auto scheduling
    task = {
        "video_path": str(video),
        "status": "pending",
        "meta": {"title": "Titre", "description": "D", "tags": []},
        "skip_enhance": True,
        "schedule_mode": "auto",
    }
    task_path = queue_dir / "task_001.json"
    task_path.write_text(json.dumps(task), encoding="utf-8")

    # Monkeypatch load_config to avoid ConfigError and ensure minimal cfg
    monkeypatch.setattr(worker, "load_config", lambda _p: cfg)

    # Spy on UploadScheduler.schedule_task
    scheduled = {}
    orig_schedule_task = UploadScheduler.schedule_task
    def spy_schedule(self, task_path_arg, scheduled_time=None, preferred_days=None):
        scheduled["called_with"] = str(task_path_arg)
        return orig_schedule_task(self, task_path_arg, scheduled_time, preferred_days)
    monkeypatch.setattr(UploadScheduler, "schedule_task", spy_schedule)

    # Run worker
    worker.process_queue(
        queue_dir=str(queue_dir),
        archive_dir=str(archive_dir),
        config_path=str(cfg_path),
        log_level="INFO",
    )

    # The task should be moved to archive as 'scheduled_*.json' is created by scheduler and original removed
    archived = archive_dir / task_path.name
    assert archived.exists(), "Original task should be moved to archive after scheduling"
    assert "called_with" in scheduled

    # Check that a scheduled_tasks.json exists and has at least one entry
    sched_file = schedule_dir / "scheduled_tasks.json"
    assert sched_file.exists(), "Scheduled tasks file should be created"
    data = json.loads(sched_file.read_text(encoding="utf-8"))
    assert isinstance(data, list) and len(data) >= 1
