import os
from pathlib import Path
import yaml
from src.seo_optimizer import create_seo_optimizer

cfg_path = Path("config/video.yaml")
doc = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
seo_cfg = (doc or {}).get("seo_advanced", {}) or {}

yaml_enabled = bool(seo_cfg.get("enabled", False))
yaml_key = seo_cfg.get("youtube_api_key")

print("yaml_enabled:", yaml_enabled)
print("yaml_has_key:", bool(yaml_key))
print("env_SEO_YOUTUBE_API_KEY:", bool(os.getenv("SEO_YOUTUBE_API_KEY")))
print("env_YOUTUBE_DATA_API_KEY:", bool(os.getenv("YOUTUBE_DATA_API_KEY")))

# Optimizer using YAML values
opt_yaml = create_seo_optimizer(
    {
        "enabled": yaml_enabled,
        "youtube_api_key": yaml_key,
    }
)
print("optimizer_from_yaml_created:", bool(opt_yaml))
if opt_yaml:
    used = getattr(opt_yaml.youtube_api, "api_key", "") or ""
    print("optimizer_from_yaml_key_length:", len(used))
    print("optimizer_from_yaml_source:", "yaml" if yaml_key else "env")

# Optimizer using ENV (force config null)
opt_env = create_seo_optimizer(
    {
        "enabled": True,
        "youtube_api_key": None,
    }
)
print("optimizer_from_env_created:", bool(opt_env))
if opt_env:
    used_env = getattr(opt_env.youtube_api, "api_key", "") or ""
    print("optimizer_from_env_key_length:", len(used_env))
