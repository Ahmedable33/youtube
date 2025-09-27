from pathlib import Path
import yaml
import pytest

from src.config_loader import load_config, ConfigError
from src.ai_generator import write_metadata_to_config


def test_load_config_basic_and_aliases(tmp_path: Path):
    cfg_path = tmp_path / "video.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "video": "test_video.mp4",
                "titre": "Mon titre",
                "desc": "Ma description",
                "tags": ["a", "b"],
                "categoryId": 24,
                "privacyStatus": "unlisted",
            }
        ),
        encoding="utf-8",
    )

    cfg = load_config(str(cfg_path))
    assert cfg["video_path"].endswith("test_video.mp4")
    assert cfg["title"] == "Mon titre"
    assert cfg["description"] == "Ma description"
    assert cfg["tags"] == ["a", "b"]
    assert str(cfg["category_id"]) == "24"
    assert cfg["privacy_status"] == "unlisted"


def test_load_config_errors(tmp_path: Path):
    # missing video_path
    cfg_path = tmp_path / "bad.yaml"
    cfg_path.write_text(yaml.safe_dump({"title": "t"}), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(str(cfg_path))

    # tags not a list
    cfg_path2 = tmp_path / "bad2.yaml"
    cfg_path2.write_text(
        yaml.safe_dump({"video_path": "a.mp4", "title": "t", "tags": "notalist"}),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_config(str(cfg_path2))


def test_write_metadata_to_config(tmp_path: Path):
    out_path = tmp_path / "out.yaml"
    write_metadata_to_config(
        str(out_path),
        video_path="file.mp4",
        title="Titre",
        description="Desc",
        tags=["x", "y"],
        category_id=22,
        privacy_status="private",
    )
    data = yaml.safe_load(out_path.read_text(encoding="utf-8"))
    assert data["video_path"] == "file.mp4"
    assert data["title"] == "Titre"
    assert data["description"] == "Desc"
    assert data["tags"] == ["x", "y"]
    assert data["category_id"] == 22
    assert data["privacy_status"] == "private"
