import json
from pathlib import Path
import respx
import httpx

from src.ai_generator import MetaRequest, generate_metadata, _safe_json_loads


def test_heuristic_generate_simple():
    req = MetaRequest(topic="Demo Topic", provider="none", input_text="Un texte de test pour la description.")
    data = generate_metadata(req)
    assert isinstance(data, dict)
    assert data["title"]
    assert "description" in data
    assert isinstance(data.get("tags"), list)


@respx.mock
def test_ollama_fast_mode_ok(tmp_path: Path, monkeypatch):
    # Config SEO minimale (pas de video_path/title pour forcer fallback YAML brut)
    cfg = tmp_path / "video.yaml"
    cfg.write_text(
        """
seo:
  provider: ollama
  model: llama3.2:3b
  host: http://127.0.0.1:11434
  fast_mode: true
  num_predict: 60
  timeout_seconds: 30
        """,
        encoding="utf-8",
    )

    # Préparer réponses simulées pour /api/generate (3 appels)
    base_url = "http://127.0.0.1:11434/api/generate"

    def callback(request: httpx.Request):
        body = json.loads(request.content.decode())
        prompt = body.get("prompt", "")
        if "titre accrocheur" in prompt or "Donne UNIQUEMENT un titre" in prompt:
            return httpx.Response(200, json={"response": "Titre de test"})
        if "Ecris une description" in prompt:
            return httpx.Response(200, json={"response": "Paragraphe 1.\n\nParagraphe 2."})
        if "tableau JSON" in prompt:
            return httpx.Response(200, json={"response": json.dumps(["tag1", "tag2"])})
        return httpx.Response(400, json={"error": "unexpected prompt"})

    respx.post(base_url).mock(side_effect=callback)

    req = MetaRequest(topic="Recette de pâtes", language="fr")
    data = generate_metadata(req, config_path=str(cfg))

    assert data["title"].lower().startswith("titre")
    assert "description" in data and len(data["description"]) > 0
    assert data["tags"][:2] == ["tag1", "tag2"]


def test_safe_json_loads_variants():
    assert _safe_json_loads('{"a": 1}') == {"a": 1}
    assert _safe_json_loads("```json\n{\"a\":2}\n```") == {"a": 2}
    assert _safe_json_loads("xx{\"b\":3}yy") == {"b": 3}
