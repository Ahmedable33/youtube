import types

from src import uploader


def test_uploader_retries_on_5xx_then_succeeds(monkeypatch, tmp_path):
    # Create dummy file
    f = tmp_path / "v.mp4"
    f.write_bytes(b"\x00fake")

    # Fake credentials
    creds = object()

    class FakeHttpError(Exception):
        def __init__(self, status):
            self.resp = types.SimpleNamespace(status=status)

    # Fake request with 2 transient errors then success
    events = [500, 503, "ok"]

    class FakeRequest:
        def next_chunk(self):
            ev = events.pop(0)
            if ev == "ok":
                return None, {"id": "zid"}
            raise FakeHttpError(ev)

    # Monkeypatch exponential backoff to be deterministic and fast
    monkeypatch.setattr(uploader, "_exponential_backoff", lambda r: 0)

    # Build service returns an object with videos().insert(...)
    class FakeVideos:
        def insert(self, part, body, media_body):
            return FakeRequest()

    class FakeService:
        def videos(self):
            return FakeVideos()

    monkeypatch.setattr(uploader, "_build_service", lambda credentials: FakeService())

    # Run upload
    resp = uploader.upload_video(
        creds,
        video_path=str(f),
        title="X",
        description="",
        tags=[],
        privacy_status="private",
    )

    assert resp.get("id") == "zid"
