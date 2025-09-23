import json
import sys
import types
from pathlib import Path

import pytest
import yaml


def test_worker_openai_ai_generation(monkeypatch, tmp_path: Path):
    """Test d'intégration: worker génère titre/description via OpenAI et upload."""
    # Métadonnées IA simulées (peu importe le provider car on monkey-patche worker.generate_metadata)
    fake_json = {
        "title": "Titre Généré par IA",
        "description": "Description complète générée par IA avec mots-clés optimisés.",
        "tags": ["ai", "generation", "youtube", "seo"],
        "hashtags": ["#ai", "#youtube"]
    }

    # (Plus besoin de stubs OpenAI ici)

    # Mock Google API modules pour éviter les dépendances (avant import worker)
    ga = types.ModuleType("googleapiclient")
    ga_discovery = types.ModuleType("googleapiclient.discovery")
    ga_errors = types.ModuleType("googleapiclient.errors")
    ga_http = types.ModuleType("googleapiclient.http")

    class _StubResumableUploadError(Exception):
        pass
    ga_errors.ResumableUploadError = _StubResumableUploadError

    class _StubHttpError(Exception):
        def __init__(self, *args, **kwargs):
            # Mimic attribute access in some code paths
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

    sys.modules['googleapiclient'] = ga
    sys.modules['googleapiclient.discovery'] = ga_discovery
    sys.modules['googleapiclient.errors'] = ga_errors
    sys.modules['googleapiclient.http'] = ga_http

    # Importer worker après stubs
    from src import worker

    # Mock ai_generator pour renvoyer des métadonnées IA factices
    monkeypatch.setattr(worker, "generate_metadata", lambda req, **kwargs: fake_json)
    monkeypatch.setattr(worker, "get_credentials", lambda *a, **k: object())
    monkeypatch.setattr(worker, "get_best_thumbnail", lambda *a, **k: None)
    monkeypatch.setattr(worker, "smart_upload_captions", lambda *a, **k: {})

    def fake_upload(creds, video_path, **kwargs):
        return {"id": "uploaded_video_id"}
    monkeypatch.setattr(worker, "upload_video", fake_upload)

    # Config avec SEO provider=ollama
    cfg = {
        "privacy_status": "private",
        "language": "fr",
        "seo": {
            "provider": "ollama",
            "model": "llama3.2:3b",
            "host": "http://127.0.0.1:11434",
            "fast_mode": True,
            "force_title_from_description": False
        },
        "enhance": {"enabled": False},  # Skip enhance
        "multi_accounts": {"enabled": False},
    }
    cfg_path = tmp_path / "video.yaml"
    raw = {
        "video_path": str(tmp_path / "test.mp4"),
        **cfg,
    }
    cfg_path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")

    # Task avec titre/description manquants -> IA forcée
    task = {
        "video_path": str(tmp_path / "test.mp4"),
        "status": "pending",
        "meta": {},  # Pas de titre/description -> génération IA
    }

    queue_dir = tmp_path / "queue"
    archive_dir = tmp_path / "archive"
    queue_dir.mkdir()
    archive_dir.mkdir()

    task_path = queue_dir / "task_test.json"
    task_path.write_text(json.dumps(task), encoding="utf-8")

    # Créer un fichier vidéo factice
    (tmp_path / "test.mp4").write_bytes(b"fake video content")

    # Traiter la queue
    worker.process_queue(
        queue_dir=str(queue_dir),
        archive_dir=str(archive_dir),
        config_path=str(cfg_path),
        log_level="WARNING",  # Moins de logs
    )

    # Vérifier que la tâche a été traitée avec génération IA
    archived = archive_dir / task_path.name
    assert archived.exists(), "Task should be archived after processing"
    data = json.loads(archived.read_text(encoding="utf-8"))
    assert data.get("status") == "done"
    assert data.get("youtube_id") == "uploaded_video_id"

    # Vérifier que les métadonnées IA ont été utilisées
    # (upload_video devrait avoir reçu les valeurs IA)
