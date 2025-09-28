from pathlib import Path
import sys
import types

import yaml

# Stub external heavy modules before importing main CLI
ga = types.ModuleType("googleapiclient")
ga_discovery = types.ModuleType("googleapiclient.discovery")
ga_errors = types.ModuleType("googleapiclient.errors")
ga_http = types.ModuleType("googleapiclient.http")


def _stub_build(*args, **kwargs):
    class _Svc:
        pass

    return _Svc()


class _StubHttpError(Exception):
    pass


class _StubResumableUploadError(Exception):
    pass


class _StubMediaFileUpload:
    def __init__(self, *args, **kwargs):
        pass


ga_discovery.build = _stub_build
ga_errors.HttpError = _StubHttpError
ga_errors.ResumableUploadError = _StubResumableUploadError
ga_http.MediaFileUpload = _StubMediaFileUpload
sys.modules["googleapiclient"] = ga
sys.modules["googleapiclient.discovery"] = ga_discovery
sys.modules["googleapiclient.errors"] = ga_errors
sys.modules["googleapiclient.http"] = ga_http

# Stub telegram ingest to avoid dependency at import time
stub_ingest_tg = types.ModuleType("src.ingest_telegram")


def _stub_run_bot_from_sources(*args, **kwargs):
    return None


stub_ingest_tg.run_bot_from_sources = _stub_run_bot_from_sources
sys.modules["src.ingest_telegram"] = stub_ingest_tg

import main as cli  # noqa: E402


def test_ai_meta_prints(monkeypatch, capsys, tmp_path: Path):
    # Stub generate_metadata to avoid any network
    def fake_generate(req, config_path: str = "config/video.yaml", video_path=None):
        return {
            "title": "Titre Test",
            "description": "Desc Test",
            "tags": ["t1", "t2"],
            "hashtags": ["#x"],
        }

    monkeypatch.setattr(cli, "generate_metadata", fake_generate)

    rc = cli.main(
        [
            "ai-meta",
            "--topic",
            "Sujet",
            "--language",
            "fr",
            "--print",
            "--log-level",
            "INFO",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "Title:" in out and "Titre Test" in out
    assert "Tags:" in out and "t1" in out


def test_ai_meta_writes_out_config(monkeypatch, tmp_path: Path):
    def fake_generate(req, config_path: str = "config/video.yaml", video_path=None):
        return {
            "title": "Titre Out",
            "description": "Desc Out",
            "tags": ["a", "b"],
            "hashtags": [],
        }

    monkeypatch.setattr(cli, "generate_metadata", fake_generate)

    out_yaml = tmp_path / "out.yaml"
    rc = cli.main(
        [
            "ai-meta",
            "--topic",
            "Sujet",
            "--language",
            "fr",
            "--out-config",
            str(out_yaml),
            "--video-path",
            "video.mp4",
            "--log-level",
            "INFO",
        ]
    )
    assert rc == 0
    data = yaml.safe_load(out_yaml.read_text(encoding="utf-8"))
    assert data["title"] == "Titre Out"
    assert data["video_path"] == "video.mp4"
    assert data["tags"] == ["a", "b"]
