from pathlib import Path
import importlib
import types
import sys


def test_quality_defaults_known_presets():
    # Stub googleapiclient to avoid hard dependency when importing worker
    ga = types.ModuleType("googleapiclient")
    ga_discovery = types.ModuleType("googleapiclient.discovery")
    ga_errors = types.ModuleType("googleapiclient.errors")
    ga_http = types.ModuleType("googleapiclient.http")
    sys.modules['googleapiclient'] = ga
    sys.modules['googleapiclient.discovery'] = ga_discovery
    sys.modules['googleapiclient.errors'] = ga_errors
    sys.modules['googleapiclient.http'] = ga_http

    worker = importlib.import_module('src.worker')

    for name in ["low", "medium", "high", "youtube", "max"]:
        cfg = worker._quality_defaults(name)
        assert isinstance(cfg, dict)
        # Check some expected keys exist across presets
        assert "crf" in cfg
        assert "preset" in cfg


def test_default_title_for_builds_from_filename(tmp_path: Path):
    # Stub googleapiclient to avoid hard dependency when importing worker
    ga = types.ModuleType("googleapiclient")
    ga_discovery = types.ModuleType("googleapiclient.discovery")
    ga_errors = types.ModuleType("googleapiclient.errors")
    ga_http = types.ModuleType("googleapiclient.http")
    sys.modules['googleapiclient'] = ga
    sys.modules['googleapiclient.discovery'] = ga_discovery
    sys.modules['googleapiclient.errors'] = ga_errors
    sys.modules['googleapiclient.http'] = ga_http

    worker = importlib.import_module('src.worker')

    p = tmp_path / "ma_super_video_demo_final.mp4"
    p.write_bytes(b"fake")
    title = worker._default_title_for(p)
    assert "ma super video demo final" in title
    assert len(title) <= 90
