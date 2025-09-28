import yaml

import main as cli
from src import uploader


def test_cli_upload_integration(monkeypatch, tmp_path, capsys):
    # Create a tiny dummy video file
    vid = tmp_path / "video.mp4"
    vid.write_bytes(b"\x00\x00fakevideo")

    # Minimal config to avoid pre-enhance and optional features
    cfg = {
        "video_path": str(vid),
        "title": "Titre Intégration",
        "description": "Desc Integration",
        "tags": ["int", "test"],
        "category_id": 22,
        "privacy_status": "private",
        "enhance": {"enabled": False},
    }
    cfg_path = tmp_path / "video.yaml"
    cfg_path.write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    # Stub credentials and YouTube service
    monkeypatch.setattr(cli, "get_credentials", lambda *a, **k: object())

    class FakeRequest:
        def __init__(self):
            self._done = False

        def next_chunk(self):
            if not self._done:
                self._done = True
                return None, {"id": "abc123"}
            return None, {"id": "abc123"}

    class FakeVideos:
        def insert(self, part, body, media_body):
            # Validate body contains our values
            assert body["snippet"]["title"] == "Titre Intégration"
            return FakeRequest()

    class FakeThumbs:
        def set(self, videoId, media_body):
            class _E:
                def execute(self):
                    return {}

            return _E()

    class FakeService:
        def videos(self):
            return FakeVideos()

        def thumbnails(self):
            return FakeThumbs()

    monkeypatch.setattr(uploader, "_build_service", lambda credentials: FakeService())

    rc = cli.main(
        [
            "upload",
            "--config",
            str(cfg_path),
            "--log-level",
            "INFO",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "Video ID: abc123" in out
