import json
import sys
import types
from pathlib import Path


def test_multi_accounts_e2e(monkeypatch, tmp_path: Path):
    # Stub googleapiclient modules before importing worker (ResumableUploadError symbol present)
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
    # Stubs required by src.uploader import
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

    # Config with multi-accounts enabled
    cfg = {
        "privacy_status": "private",
        "language": "fr",
        "enhance": {"enabled": False},
        "subtitles": {"enabled": False},
        "seo": {"provider": "none"},
        "multi_accounts": {"enabled": True},
    }
    cfg_path = tmp_path / "video.yaml"

    # Prepare dirs
    queue_dir = tmp_path / "queue"
    archive_dir = tmp_path / "queue_archive"
    queue_dir.mkdir()
    archive_dir.mkdir()

    video = tmp_path / "video.mp4"
    video.write_bytes(b"\x00\x00fakevideo")
    cfg["video_path"] = str(video)
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

    task = {
        "video_path": str(video),
        "status": "pending",
        "meta": {"title": "T", "description": "D", "tags": ["a"]},
        "skip_enhance": True,
        # Simuler un chat_id pour vérifier mapping direct
        "chat_id": "chat-42",
    }
    task_path = queue_dir / "task_001.json"
    task_path.write_text(json.dumps(task), encoding="utf-8")

    # Build a fake MultiAccountManager
    class FakeAccount:
        def __init__(self, account_id, name):
            self.account_id = account_id
            self.name = name

    class FakeManager:
        def __init__(self):
            self._recorded = []
        def get_chat_account(self, chat_id):
            assert chat_id == "chat-42"
            return FakeAccount("acc-main", "Compte Principal")
        def get_best_account_for_upload(self):
            return FakeAccount("acc-main", "Compte Principal")
        def get_credentials_for_account(self, account_id):
            assert account_id == "acc-main"
            return object()
        def record_upload(self, account_id, api_calls_used):
            self._recorded.append((account_id, api_calls_used))

    fake_manager = FakeManager()

    def _fake_create_manager():
        return fake_manager

    monkeypatch.setattr(worker, "create_multi_account_manager", _fake_create_manager)
    # Ensure worker doesn't try OAuth flow elsewhere
    monkeypatch.setattr(worker, "get_credentials", lambda *a, **k: object())
    # Raw YAML check will be forced via sys.modules['yaml'] injection below

    # Upload stub
    monkeypatch.setattr(worker, "upload_video", lambda *a, **k: {"id": "vid_multi_1"})

    # Avoid other side effects
    monkeypatch.setattr(worker, "get_best_thumbnail", lambda *a, **k: None)
    monkeypatch.setattr(worker, "smart_upload_captions", lambda *a, **k: {})

    # Ensure inline `import yaml` inside worker sees multi_accounts enabled
    fake_yaml = types.ModuleType("yaml")
    fake_yaml.safe_load = lambda _text: {"multi_accounts": {"enabled": True}}
    monkeypatch.setitem(sys.modules, 'yaml', fake_yaml)

    # Run worker
    worker.process_queue(
        queue_dir=str(queue_dir),
        archive_dir=str(archive_dir),
        config_path=str(cfg_path),
        log_level="INFO",
    )

    # Verify
    archived = archive_dir / task_path.name
    assert archived.exists()
    data = json.loads(archived.read_text(encoding="utf-8"))
    assert data.get("status") == "done"
    assert data.get("youtube_id") == "vid_multi_1"
    # Manager should have recorded quota usage
    assert ("acc-main", 1600) in fake_manager._recorded
