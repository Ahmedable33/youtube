import json
import sys
import types
from pathlib import Path

import main as cli
import src.video_enhance as ve


class _FakeProc:
    def __init__(self, *args, **kwargs):
        # Simulate ffmpeg's stderr stream with Duration and time lines
        # Patterns expected by video_enhance._DURATION_RE and _TIME_RE
        self._stderr_lines = [
            "ffmpeg version N-12345\n",
            "Duration: 00:00:10,00\n",
            "frame=  100 fps=30 time=00:00:05,00 bitrate=2000kbits/s\n",
            "frame=  200 fps=30 time=00:00:10,00 bitrate=2000kbits/s\n",
        ]
        self.stderr = iter(self._stderr_lines)
        class _Stdout:
            def read(self_inner):
                return ""
        self.stdout = _Stdout()

    def wait(self):
        return 0


def _install_ffmpeg_monkeypatch(monkeypatch):
    # Pretend ffmpeg exists
    monkeypatch.setattr(ve.shutil, "which", lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None)
    # Replace subprocess.Popen used inside enhance_video
    monkeypatch.setattr(ve.subprocess, "Popen", _FakeProc)


def test_cli_enhance_with_mock_ffmpeg(monkeypatch, tmp_path, capsys):
    _install_ffmpeg_monkeypatch(monkeypatch)

    inp = tmp_path / "in.mp4"
    inp.write_bytes(b"\x00\x00fake")
    out = tmp_path / "out.mp4"

    rc = cli.main([
        "enhance",
        "--input", str(inp),
        "--output", str(out),
        "--quality", "youtube",
        "--scale", "1080p",
        "--denoise",
        "--log-level", "INFO",
    ])
    assert rc == 0
    # The CLI prints the output path on success
    printed = capsys.readouterr().out.strip()
    assert printed == str(out)


def test_worker_enhance_with_mock_ffmpeg(monkeypatch, tmp_path: Path):
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

    _install_ffmpeg_monkeypatch(monkeypatch)

    # Config enabling enhancement
    cfg = {
        "privacy_status": "private",
        "language": "fr",
        "title": "Titre Test",
        "tags": [],
        "enhance": {"enabled": True, "quality": "youtube", "scale": "1080p"},
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
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

    task = {
        "video_path": str(video),
        "status": "pending",
        "meta": {"title": "T", "description": "D", "tags": ["a"]},
        # skip_enhance omitted -> allow enhancement
    }
    task_path = queue_dir / "task_001.json"
    task_path.write_text(json.dumps(task), encoding="utf-8")

    # Capture the video_path passed to upload_video (should be enhanced path)
    captured = {}
    def fake_upload(creds, video_path, **kwargs):
        captured["video_path"] = video_path
        return {"id": "vid_enh_1"}

    # Stubs to avoid side effects
    monkeypatch.setattr(worker, "get_credentials", lambda *a, **k: object())
    monkeypatch.setattr(worker, "get_best_thumbnail", lambda *a, **k: None)
    monkeypatch.setattr(worker, "smart_upload_captions", lambda *a, **k: {})
    monkeypatch.setattr(worker, "upload_video", fake_upload)

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
    assert data.get("youtube_id") == "vid_enh_1"
    # Verify enhanced path was used
    assert captured.get("video_path", "").endswith(".enhanced.mp4")
