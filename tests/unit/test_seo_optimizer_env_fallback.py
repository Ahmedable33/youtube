from src.seo_optimizer import create_seo_optimizer


def test_create_seo_optimizer_uses_env_when_config_key_null(monkeypatch):
    # Ensure clean env first
    monkeypatch.delenv("SEO_YOUTUBE_API_KEY", raising=False)
    monkeypatch.delenv("YOUTUBE_DATA_API_KEY", raising=False)

    # Set fallback env var
    monkeypatch.setenv("SEO_YOUTUBE_API_KEY", "env-key-123")

    cfg = {
        "enabled": True,
        "youtube_api_key": None,  # explicitly null in config
    }

    opt = create_seo_optimizer(cfg)
    assert opt is not None
    # Internal API key should be from env
    assert getattr(opt.youtube_api, "api_key", None) == "env-key-123"


def test_create_seo_optimizer_none_without_any_key(monkeypatch):
    # Remove env vars
    monkeypatch.delenv("SEO_YOUTUBE_API_KEY", raising=False)
    monkeypatch.delenv("YOUTUBE_DATA_API_KEY", raising=False)

    cfg = {
        "enabled": True,
        "youtube_api_key": None,
    }

    opt = create_seo_optimizer(cfg)
    assert opt is None
