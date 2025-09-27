import json
import sys
import types
from pathlib import Path


def test_subtitles_e2e(monkeypatch, tmp_path: Path):
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
    sys.modules["googleapiclient"] = ga
    sys.modules["googleapiclient.discovery"] = ga_discovery
    sys.modules["googleapiclient.errors"] = ga_errors
    sys.modules["googleapiclient.http"] = ga_http

    from src import worker

    # Config with subtitles enabled (fr + en), auto-detect and translate to english
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
            "auto_detect": True,
            "translate_to_english": True,
            "upload_to_youtube": True,
            "draft_mode": False,
            "replace_existing": True,
        },
        "seo": {"provider": "none"},
        "multi_accounts": {"enabled": False},
    }
    cfg_path = tmp_path / "video.yaml"

    # Prepare queue/dirs
    queue_dir = tmp_path / "queue"
    archive_dir = tmp_path / "queue_archive"
    queue_dir.mkdir()
    archive_dir.mkdir()

    video = tmp_path / "video.mp4"
    video.write_bytes(b"\x00\x00fakevideo")
    cfg["video_path"] = str(video)
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

    # Task
    task = {
        "video_path": str(video),
        "status": "pending",
        "meta": {"title": "T", "description": "D", "tags": ["a"]},
        "skip_enhance": True,
    }
    task_path = queue_dir / "task_001.json"
    task_path.write_text(json.dumps(task), encoding="utf-8")

    # Ensure worker uses our full cfg (including 'subtitles') instead of normalized one
    monkeypatch.setattr(worker, "load_config", lambda _p: cfg)
    # Stubs for upload & subtitles
    monkeypatch.setattr(worker, "get_credentials", lambda *a, **k: object())
    monkeypatch.setattr(worker, "get_best_thumbnail", lambda *a, **k: None)

    # subtitle_generator stubs
    monkeypatch.setattr(worker, "is_whisper_available", lambda: True)
    monkeypatch.setattr(worker, "detect_language", lambda *_a, **_k: "fr")

    def _fake_generate_subtitles(
        video_path, output_path, language, model, translate_to_english=False
    ):
        Path(output_path).write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nHELLO\n", encoding="utf-8"
        )

    monkeypatch.setattr(worker, "generate_subtitles", _fake_generate_subtitles)

    uploaded_ref = {}

    def _fake_upload_captions(
        credentials, video_id, subtitle_files, replace_existing, is_draft
    ):
        # Capture what was uploaded
        uploaded_ref["files"] = dict(subtitle_files)
        # Return success for all langs provided
        return {
            lang: {"success": True, "action": "insert", "caption_id": f"cap_{lang}"}
            for lang in subtitle_files
        }

    monkeypatch.setattr(worker, "smart_upload_captions", _fake_upload_captions)

    # Upload stub
    monkeypatch.setattr(worker, "upload_video", lambda *a, **k: {"id": "vid_sub_1"})

    # Run worker
    worker.process_queue(
        queue_dir=str(queue_dir),
        archive_dir=str(archive_dir),
        config_path=str(cfg_path),
        log_level="INFO",
    )

    # Verify SRT files and task metadata
    archived = archive_dir / task_path.name
    assert archived.exists()
    subs_dir = video.parent / "subtitles"
    assert (subs_dir / f"{video.stem}_fr.srt").exists()
    assert (subs_dir / f"{video.stem}_en.srt").exists()
    # Verify upload was attempted with both languages
    assert "files" in uploaded_ref
    assert set(uploaded_ref["files"].keys()) >= {"fr", "en"}
