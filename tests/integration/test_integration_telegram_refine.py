import json
import sys
import types
from pathlib import Path

import pytest
import yaml


def _stub_google_clients():
    ga = types.ModuleType("googleapiclient")
    ga_discovery = types.ModuleType("googleapiclient.discovery")
    ga_errors = types.ModuleType("googleapiclient.errors")
    ga_http = types.ModuleType("googleapiclient.http")

    class _StubResumableUploadError(Exception):
        pass

    ga_errors.ResumableUploadError = _StubResumableUploadError

    class _StubHttpError(Exception):
        def __init__(self, *args, **kwargs):
            self.resp = types.SimpleNamespace(status=400)
            super().__init__(*args)

    ga_errors.HttpError = _StubHttpError

    def _stub_build(*args, **kwargs):
        class _Svc:
            def videos(self):
                class _Videos:
                    def insert(self, **kwargs):
                        class _Insert:
                            def execute(self):
                                return {"id": "test_video_id"}

                        return _Insert()

                return _Videos()

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


@pytest.fixture(autouse=True)
def stub_google():
    _stub_google_clients()
    yield


def _run_worker_with_task(tmp_path: Path, task: dict, ai_meta: dict):
    # Write config with Ollama provider
    cfg = {
        "privacy_status": "private",
        "language": "fr",
        "seo": {
            "provider": "ollama",
            "model": "llama3.2:3b",
            "host": "http://127.0.0.1:11434",
            "fast_mode": False,
            "num_predict": 200,
            "force_title_from_description": False,
        },
        "enhance": {"enabled": False},
        "multi_accounts": {"enabled": False},
    }
    cfg_path = tmp_path / "video.yaml"
    raw = {"video_path": str(tmp_path / "test.mp4"), **cfg}
    cfg_path.write_text(
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    # Prepare queue and archive
    queue_dir = tmp_path / "queue"
    archive_dir = tmp_path / "archive"
    queue_dir.mkdir()
    archive_dir.mkdir()

    # Write task
    task_path = queue_dir / "task_telegram.json"
    task_path.write_text(json.dumps(task), encoding="utf-8")

    # Create fake video file
    (tmp_path / "test.mp4").write_bytes(b"fake video content")

    # Import worker and monkeypatch
    from src import worker

    # Monkeypatch AI and YouTube upload
    worker_generate_called = {"count": 0}

    def fake_gen(req, **kwargs):
        worker_generate_called["count"] += 1
        return ai_meta

    def fake_creds(*a, **k):
        return object()

    captured_upload = {"kwargs": None}

    def fake_upload(creds, video_path, **kwargs):
        captured_upload["kwargs"] = kwargs
        return {"id": "uploaded_video_id"}

    # Apply patches
    worker.generate_metadata = fake_gen
    worker.get_credentials = fake_creds
    worker.get_best_thumbnail = lambda *a, **k: None
    worker.smart_upload_captions = lambda *a, **k: {}
    worker.upload_video = fake_upload

    # Run
    worker.process_queue(
        queue_dir=str(queue_dir),
        archive_dir=str(archive_dir),
        config_path=str(cfg_path),
        log_level="WARNING",
    )

    # Return archived task and captured call
    archived = archive_dir / task_path.name
    data = json.loads(archived.read_text(encoding="utf-8"))
    return data, captured_upload["kwargs"], worker_generate_called["count"]


def test_refine_title_and_tags_when_title_only(tmp_path: Path):
    task = {
        "source": "telegram",
        "chat_id": 123,
        "video_path": str(tmp_path / "test.mp4"),
        "status": "pending",
        "meta": {
            "title": "Mon titre original",
            "description": None,
            "tags": ["ancien", "tag"],
        },
    }
    ai_meta = {
        "title": "Titre percutant IA",
        "description": "Description générée par IA",
        "tags": ["nouveau", "tags", "seo"],
    }
    data, upload_kwargs, calls = _run_worker_with_task(tmp_path, task, ai_meta)

    assert data.get("status") == "done"
    assert data.get("youtube_id") == "uploaded_video_id"
    # upload_video must have received the refined title and tags
    assert upload_kwargs["title"] == "Titre percutant IA"
    assert set(upload_kwargs["tags"]) == {"nouveau", "tags", "seo"}
    # Because no user description, worker should fill from AI
    assert upload_kwargs["description"].startswith("Description générée")
    # Ensure AI was called
    assert calls >= 1


def test_refine_title_and_tags_when_title_and_description(tmp_path: Path):
    task = {
        "source": "telegram",
        "chat_id": 456,
        "video_path": str(tmp_path / "test.mp4"),
        "status": "pending",
        "meta": {
            "title": "Titre fourni",
            "description": "Desc utilisateur à conserver",
            "tags": ["anciens", "mots"],
        },
    }
    ai_meta = {
        "title": "Titre IA plus accrocheur",
        "description": "Description IA (ne doit pas remplacer)",
        "tags": ["visibilite", "clics"],
    }
    data, upload_kwargs, calls = _run_worker_with_task(tmp_path, task, ai_meta)

    assert data.get("status") == "done"
    # The title/tags should be from AI, but description should remain the user's
    assert upload_kwargs["title"] == "Titre IA plus accrocheur"
    assert set(upload_kwargs["tags"]) == {"visibilite", "clics"}
    assert upload_kwargs["description"] == "Desc utilisateur à conserver"
    assert calls >= 1
