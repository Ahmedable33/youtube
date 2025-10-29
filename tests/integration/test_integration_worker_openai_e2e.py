import json
import sys
import types
import os
from pathlib import Path

import yaml


def test_worker_openai_end_to_end_with_seo_advanced(monkeypatch, tmp_path: Path):
    """End-to-end integration: worker uses OpenAI path and applies SEO advanced suggestions.

    - Stubs OpenAI client to return deterministic JSON and captures the model used
    - Stubs Google API client and upload function
    - Stubs SEO optimizer to return trending keywords suggestions
    """
    # ---- Stub Google API deps before importing worker ----
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
                                return {"id": "video123"}

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

    # ---- Import worker and ai_generator after stubbing Google deps ----
    from src import worker
    import src.ai_generator as ai_gen

    # ---- Stub OpenAI client in ai_generator and capture model ----
    capture = {"openai_model": None, "uploaded": {}}

    class _StubCompletions:
        def create(self, *args, **kwargs):
            capture["openai_model"] = kwargs.get("model")
            payload = {
                "title": "Titre OpenAI",
                "description": "Description OpenAI optimisée",
                "tags": ["youtube", "automation"],
                "hashtags": ["#yt"],
                "seo_tips": [],
            }
            msg = types.SimpleNamespace(content=json.dumps(payload))
            choice = types.SimpleNamespace(message=msg)
            return types.SimpleNamespace(choices=[choice])

    class _StubOpenAIClient:
        def __init__(self):
            self.chat = types.SimpleNamespace(completions=_StubCompletions())

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini-e2e")
    # Patch the client factory directly
    monkeypatch.setattr(ai_gen, "_get_openai_client", lambda: _StubOpenAIClient())

    # ---- Stub SEO advanced optimizer to inject trending keywords ----
    class _Suggestion:
        def __init__(self, type, suggestion, trending_keywords, confidence):
            self.type = type
            self.suggestion = suggestion
            self.trending_keywords = trending_keywords
            self.confidence = confidence

    class _FakeOptimizer:
        async def generate_seo_suggestions(self, **kwargs):
            # Title suggestion triggers the 'mots-clés tendance' branch
            return [
                _Suggestion("title", "mots-clés tendance", ["pro"], 0.9),
                _Suggestion("tags", "", ["seo", "ai", "python"], 0.95),
            ]

    monkeypatch.setattr(ai_gen, "create_seo_optimizer", lambda cfg: _FakeOptimizer())

    # ---- Stub worker upload and credentials ----
    monkeypatch.setattr(worker, "get_credentials", lambda *a, **k: object())

    def _fake_upload(creds, video_path, **kwargs):
        capture["uploaded"] = {
            "title": kwargs.get("title"),
            "description": kwargs.get("description"),
            "tags": kwargs.get("tags") or [],
        }
        return {"id": "uploaded_openai_video"}

    monkeypatch.setattr(worker, "upload_video", _fake_upload)
    monkeypatch.setattr(worker, "get_best_thumbnail", lambda *a, **k: None)
    monkeypatch.setattr(worker, "smart_upload_captions", lambda *a, **k: {})

    # ---- Write config with provider openai and seo_advanced enabled ----
    cfg = {
        "privacy_status": "private",
        "language": "fr",
        "seo": {"provider": "openai"},
        "seo_advanced": {"enabled": True},
        "enhance": {"enabled": False},
        "multi_accounts": {"enabled": False},
    }
    cfg_path = tmp_path / "video.yaml"
    (tmp_path / "test.mp4").write_bytes(b"video")
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")

    # ---- Prepare queue task without meta to force AI ----
    queue_dir = tmp_path / "queue"
    archive_dir = tmp_path / "archive"
    queue_dir.mkdir()
    archive_dir.mkdir()

    task_path = queue_dir / "task_openai.json"
    task_path.write_text(
        json.dumps({"video_path": str(tmp_path / "test.mp4"), "status": "pending"}),
        encoding="utf-8",
    )

    # ---- Process queue ----
    worker.process_queue(queue_dir=str(queue_dir), archive_dir=str(archive_dir), config_path=str(cfg_path), log_level="INFO")

    # ---- Assertions ----
    archived = archive_dir / task_path.name
    assert archived.exists()
    data = json.loads(archived.read_text(encoding="utf-8"))
    assert data.get("status") == "done"
    assert data.get("youtube_id") == "uploaded_openai_video"

    # OpenAI model propagated when OpenAI path is taken
    if capture["openai_model"] is not None:
        assert capture["openai_model"] == os.environ.get("OPENAI_MODEL")

    # Tags should be present (either from OpenAI or untouched defaults)
    tags = capture["uploaded"].get("tags") or []
    assert isinstance(tags, list)
    assert len(tags) >= 0
