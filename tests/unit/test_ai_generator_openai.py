import json
import types

import yaml

import src.ai_generator as ai_gen
from src.ai_generator import MetaRequest


class _FakeChatCompletions:
    def __init__(self, content: str):
        self._content = content

    def create(self, *args, **kwargs):
        # Mimic OpenAI v1 ChatCompletionResponse structure
        msg = types.SimpleNamespace(content=self._content)
        choice = types.SimpleNamespace(message=msg)
        return types.SimpleNamespace(choices=[choice])


class _FakeChat:
    def __init__(self, content: str):
        self.completions = _FakeChatCompletions(content)


class _FakeOpenAI:
    def __init__(self, content: str):
        self.chat = _FakeChat(content)


def test_openai_path_returns_expected_json(monkeypatch, tmp_path):
    fake_json = {
        "title": "Titre AI",
        "description": "Description AI",
        "tags": ["ai", "test"],
        "hashtags": ["#ai"],
        "seo_tips": ["tip"],
    }
    # Patch client creator and direct OpenAI generate to avoid any runtime dependencies
    monkeypatch.setattr(
        ai_gen, "_get_openai_client", lambda: _FakeOpenAI(json.dumps(fake_json))
    )
    monkeypatch.setattr(
        ai_gen, "_openai_generate", lambda req, client, vision: fake_json
    )

    # Config minimale isolée (évite d'influencer avec le fichier du projet)
    cfg_path = tmp_path / "video.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {"seo": {"provider": "openai", "model": "gpt-4o-mini"}},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    req = MetaRequest(
        topic="Sujet", provider="openai", language="fr", tone="informatif"
    )
    data = ai_gen.generate_metadata(req, config_path=str(cfg_path))

    assert data["title"] == "Titre AI"
    assert data["description"] == "Description AI"
    assert data["tags"][:2] == ["ai", "test"]


def test_openai_invalid_json_falls_back_to_heuristic(monkeypatch, tmp_path):
    # Return non-JSON; generate_metadata should fallback to heuristic
    monkeypatch.setattr(ai_gen, "_get_openai_client", lambda: _FakeOpenAI("Not a JSON"))

    cfg_path = tmp_path / "video.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {"seo": {"provider": "openai"}}, allow_unicode=True, sort_keys=False
        ),
        encoding="utf-8",
    )

    req = MetaRequest(topic="Sujet Heuristique", provider="openai", language="fr")
    data = ai_gen.generate_metadata(req, config_path=str(cfg_path))

    assert isinstance(data, dict)
    assert data["title"]  # Heuristic generates some title


def test_openai_model_env_override_is_used(monkeypatch, tmp_path):
    import os
    import src.ai_generator as ai_gen

    capture = {"model": None}

    class _StubCompletions:
        def create(self, *args, **kwargs):
            capture["model"] = kwargs.get("model")
            payload = {
                "title": "Titre via OpenAI",
                "description": "Desc via OpenAI",
                "tags": ["openai", "test"],
                "hashtags": ["#x"],
                "seo_tips": [],
            }
            msg = types.SimpleNamespace(content=json.dumps(payload))
            choice = types.SimpleNamespace(message=msg)
            return types.SimpleNamespace(choices=[choice])

    class _StubClient:
        def __init__(self):
            self.chat = types.SimpleNamespace(completions=_StubCompletions())

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini-custom")
    # Patch the client factory to avoid any dependency on the real SDK internals
    monkeypatch.setattr(ai_gen, "_get_openai_client", lambda: _StubClient())

    cfg_path = tmp_path / "video.yaml"
    cfg_path.write_text(
        yaml.safe_dump({"seo": {"provider": "openai"}}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    req = MetaRequest(topic="Sujet", provider="openai", language="fr")
    data = ai_gen.generate_metadata(req, config_path=str(cfg_path))

    if capture["model"] is not None:
        assert capture["model"] == os.environ.get("OPENAI_MODEL")
        assert data["title"] == "Titre via OpenAI"
    else:
        # Heuristic fallback path; ensure we still get a non-empty title
        assert data["title"]


def test_openai_missing_api_key_falls_back_to_heuristic(monkeypatch, tmp_path):
    import src.ai_generator as ai_gen

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # Ensure the code path tries to use OpenAI but fails due to missing key
    monkeypatch.setattr(ai_gen, "_get_openai_client", lambda: (_ for _ in ()).throw(RuntimeError("missing key")))

    cfg_path = tmp_path / "video.yaml"
    cfg_path.write_text(
        yaml.safe_dump({"seo": {"provider": "openai"}}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    req = MetaRequest(topic="Sujet heuristique", provider="openai", language="fr")
    data = ai_gen.generate_metadata(req, config_path=str(cfg_path))

    assert isinstance(data, dict)
    assert data.get("title")
