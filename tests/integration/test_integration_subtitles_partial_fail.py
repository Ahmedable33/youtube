import json
import sys
import types
from pathlib import Path


def test_subtitles_replace_existing_partial_failure(monkeypatch, tmp_path: Path):
    # Stub googleapiclient modules before importing worker (symbols for uploader)
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

    sys.modules['googleapiclient'] = ga
    sys.modules['googleapiclient.discovery'] = ga_discovery
    sys.modules['googleapiclient.errors'] = ga_errors
    sys.modules['googleapiclient.http'] = ga_http

    from src import worker

    # Config enabling subtitles with replace_existing True
    cfg = {
        "privacy_status": "private",
        "language": "fr",
        "enhance": {"enabled": False},
        "title": "Titre Test",
        "tags": [],
        "subtitles": {
            "enabled": True,
            "whisper_model": "base",
            "languages": ["fr", "en"],
            "auto_detect_language": True,
            "translate_to_english": True,
            "upload_to_youtube": True,
            "draft_mode": False,
            "replace_existing": True,
        },
        "seo": {"provider": "none"},
        "multi_accounts": {"enabled": False},
    }
    cfg_path = tmp_path / "video.yaml"

    queue_dir = tmp_path / "queue"
    archive_dir = tmp_path / "queue_archive"
    queue_dir.mkdir(); archive_dir.mkdir()

    video = tmp_path / "video.mp4"
    video.write_bytes(b"\x00\x00fakevideo")
    cfg["video_path"] = str(video)
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

    task = {
        "video_path": str(video),
        "status": "pending",
        "meta": {"title": "T", "description": "D", "tags": ["a"]},
        "skip_enhance": True,
    }
    task_path = queue_dir / "task_001.json"
    task_path.write_text(json.dumps(task), encoding="utf-8")

    # Ensure worker uses our cfg dict directly
    monkeypatch.setattr(worker, "load_config", lambda _p: cfg)

    # Stubs for credentials, upload, thumbnails
    monkeypatch.setattr(worker, "get_credentials", lambda *a, **k: object())
    monkeypatch.setattr(worker, "upload_video", lambda *a, **k: {"id": "vid_sub_partial"})
    monkeypatch.setattr(worker, "get_best_thumbnail", lambda *a, **k: None)

    # Subtitles generation stubs
    monkeypatch.setattr(worker, "is_whisper_available", lambda: True)
    monkeypatch.setattr(worker, "detect_language", lambda *_a, **_k: "fr")

    def _fake_generate_subtitles(video_path, output_path, language, model, translate_to_english=False):
        Path(output_path).write_text("1\n00:00:00,000 --> 00:00:01,000\nHELLO\n", encoding="utf-8")

    monkeypatch.setattr(worker, "generate_subtitles", _fake_generate_subtitles)

    # smart_upload_captions returns partial success: fr OK, en FAIL
    def _fake_smart_upload(credentials, video_id, subtitle_files, replace_existing, is_draft):
        return {
            "fr": {"success": True, "action": "updated", "caption_id": "cap_fr"},
            "en": {"success": False, "error": "quota exceeded"},
        }

    monkeypatch.setattr(worker, "smart_upload_captions", _fake_smart_upload)

    # Run
    worker.process_queue(
        queue_dir=str(queue_dir),
        archive_dir=str(archive_dir),
        config_path=str(cfg_path),
        log_level="INFO",
    )

    # Verify task is done and uploaded id present
    archived = archive_dir / task_path.name
    assert archived.exists()
    data = json.loads(archived.read_text(encoding="utf-8"))
    assert data.get("status") == "done"
    assert data.get("youtube_id") == "vid_sub_partial"

    # Verify subtitles field records generated langs and only successful uploads
    subs = data.get("subtitles", {})
    assert set(subs.get("generated", [])) >= {"fr", "en"}
    assert subs.get("uploaded") == ["fr"] or set(subs.get("uploaded", [])) == {"fr"}
