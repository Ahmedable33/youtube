import json
import sys
import types
from pathlib import Path


def test_worker_multi_accounts_no_account_archives_error(monkeypatch, tmp_path: Path):
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

    # Force multi-accounts enabled via fake yaml module
    fake_yaml = types.ModuleType("yaml")
    fake_yaml.safe_load = lambda _text: {"multi_accounts": {"enabled": True}}
    monkeypatch.setitem(sys.modules, 'yaml', fake_yaml)

    # Fake manager that returns no account
    class _FakeManager:
        def get_chat_account(self, chat_id: str):
            return None

        def get_best_account_for_upload(self):
            return None

        def get_credentials_for_account(self, account_id: str):
            raise RuntimeError("should not be called")

        def record_upload(self, account_id: str, api_calls_used: int):
            pass

    monkeypatch.setattr(worker, "create_multi_account_manager", lambda: _FakeManager())

    # Prepare dirs
    queue_dir = tmp_path / "queue"
    archive_dir = tmp_path / "queue_archive"
    queue_dir.mkdir()
    archive_dir.mkdir()

    # Create dummy video and task
    video = tmp_path / "video.mp4"
    video.write_bytes(b"\x00\x00fakevideo")

    task = {
        "video_path": str(video),
        "status": "pending",
        "meta": {"title": "T", "description": "D", "tags": ["x"]},
        "skip_enhance": True,
        # chat_id optional; without chat_id, the worker uses get_best_account_for_upload()
    }
    task_path = queue_dir / "task_001.json"
    task_path.write_text(json.dumps(task), encoding="utf-8")

    # Run (no config_path needed)
    worker.process_queue(
        queue_dir=str(queue_dir),
        archive_dir=str(archive_dir),
        config_path=None,
        log_level="INFO",
    )

    # Task should be archived as error due to no account available
    archived = archive_dir / task_path.name
    assert archived.exists(), "Task should be archived when no account available"
    data = json.loads(archived.read_text(encoding="utf-8"))
    assert data.get("status") == "error"
    assert data.get("error") == "No YouTube account available"
