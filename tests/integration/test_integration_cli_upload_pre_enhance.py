from pathlib import Path
import main as cli
import src.video_enhance as ve


class _FakeProc:
    def __init__(self, *args, **kwargs):
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
    monkeypatch.setattr(ve.shutil, "which", lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None)
    monkeypatch.setattr(ve.subprocess, "Popen", _FakeProc)


def test_cli_upload_pre_enhance_uses_enhanced_path(monkeypatch, tmp_path, capsys):
    _install_ffmpeg_monkeypatch(monkeypatch)

    inp = tmp_path / "in.mp4"
    inp.write_bytes(b"\x00\x00fake")

    captured = {}
    def fake_upload(creds, video_path, **kwargs):
        captured["video_path"] = video_path
        return {"id": "vid_cli_pre_1"}

    monkeypatch.setattr(cli, "get_credentials", lambda *a, **k: object())
    monkeypatch.setattr(cli, "upload_video", fake_upload)

    rc = cli.main([
        "upload",
        "--video", str(inp),
        "--title", "Titre",
        "--pre-enhance",
        "--enhance-quality", "youtube",
        "--enhance-scale", "1080p",
        "--log-level", "INFO",
    ])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert out.endswith("vid_cli_pre_1"), out
    assert captured.get("video_path", "").endswith(".enhanced.mp4")
