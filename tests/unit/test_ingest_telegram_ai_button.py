import json
from pathlib import Path

import pytest

from src import ingest_telegram as tg


def test_reply_keyboard_contains_ai_regen_button():
    kb = tg._reply_menu_keyboard()
    # ReplyKeyboardMarkup stores a list of rows of KeyboardButton objects
    found = False
    for row in kb.keyboard:
        for btn in row:
            label = getattr(btn, "text", btn)
            if label == "AI: Re-générer Titre/Tags":
                found = True
                break
        if found:
            break
    assert found


def _make_task(queue_dir: Path, chat_id: int, video_path: Path, meta: dict):
    queue_dir.mkdir(parents=True, exist_ok=True)
    # Create task file and last pointer
    task = {
        "source": "telegram",
        "chat_id": chat_id,
        "received_at": "2025-01-01T00:00:00Z",
        "video_path": str(video_path),
        "status": "pending",
        "steps": ["enhance", "ai_meta", "upload"],
        "prefs": {},
        "meta": meta,
    }
    task_path = queue_dir / f"task_test_{chat_id}.json"
    task_path.write_text(
        json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Write last pointer
    (queue_dir / f"last_task_{chat_id}.json").write_text(
        json.dumps({"task_path": str(task_path)}), encoding="utf-8"
    )

    return task_path


@pytest.mark.parametrize("has_desc", [False, True])
def test_ai_regenerate_title_tags_updates_meta(
    tmp_path: Path, monkeypatch, has_desc: bool
):
    # Prepare config file (minimal SEO Ollama)
    cfg_path = tmp_path / "video.yaml"
    cfg_path.write_text(
        """
seo:
  provider: ollama
  model: llama3.2:3b
  host: http://127.0.0.1:11434
  fast_mode: false
  num_predict: 120
        """.strip(),
        encoding="utf-8",
    )

    # Prepare fake video
    video = tmp_path / "vid.mp4"
    video.write_bytes(b"fake")

    chat_id = 999
    queue_dir = tmp_path / "queue"

    # Initial meta from user
    user_meta = {
        "language": "fr",
        "tone": "informatif",
        "title": "Mon titre utilisateur",
        "description": ("Ma description" if has_desc else None),
        "tags": ["old", "stuff"],
    }
    _make_task(queue_dir, chat_id, video, user_meta)

    # AI returns refined values
    ai_meta = {
        "title": "Titre IA percutant",
        "description": "Description IA enrichie",
        "tags": ["nouveau", "tags"],
    }

    # Monkeypatch AI generate_metadata
    monkeypatch.setattr(tg, "generate_metadata", lambda req, **kwargs: ai_meta)

    res = tg.ai_regenerate_title_tags(queue_dir, chat_id, config_path=str(cfg_path))
    meta = res["meta"]

    assert meta["title"] == "Titre IA percutant"
    # Tags normalized, order-insensitive
    assert set(meta["tags"]) == {"nouveau", "tags"}

    if has_desc:
        # Should preserve user's description
        assert meta["description"] == "Ma description"
    else:
        # Should fill from AI if missing
        assert meta["description"].startswith("Description IA")


def test_ai_regenerate_title_tags_errors_when_no_task(tmp_path: Path):
    with pytest.raises(RuntimeError):
        tg.ai_regenerate_title_tags(
            tmp_path / "queue", 42, config_path=str(tmp_path / "video.yaml")
        )
