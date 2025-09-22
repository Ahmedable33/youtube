from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import yaml


class ConfigError(Exception):
    pass


def load_config(path: str | Path) -> Dict[str, Any]:
    """
    Charge une configuration YAML/JSON et normalise les clés attendues.

    Clés supportées (normalisées):
      - video_path (str)
      - thumbnail_path (str | None)
      - title (str)
      - description (str)
      - tags (list[str])
      - category_id (int | str)
      - privacy_status (str)
      - publish_at (str | None)  # RFC3339 UTC (ex: 2025-08-31T12:00:00Z)
      - made_for_kids (bool | None)
      - enhance (dict | None)  # paramètres d'amélioration qualité ffmpeg
    """
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"Fichier de configuration introuvable: {p}")

    raw: Dict[str, Any]
    if p.suffix.lower() in {".yaml", ".yml"}:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    elif p.suffix.lower() == ".json":
        raw = json.loads(p.read_text(encoding="utf-8"))
    else:
        raise ConfigError("Extension de configuration non supportée (utilisez .yaml/.yml ou .json)")

    # Alias possibles (français et API)
    def take(*keys, default=None):
        for k in keys:
            if k in raw and raw[k] is not None:
                return raw[k]
        return default

    cfg: Dict[str, Any] = {
        "video_path": take("video_path", "video", "path"),
        "thumbnail_path": take("thumbnail_path", "thumbnail"),
        "title": take("title", "titre"),
        "description": take("description", "desc"),
        "tags": take("tags", default=[]) or [],
        "category_id": take("category_id", "categoryId", default=22),
        "privacy_status": (take("privacy_status", "privacyStatus", default="private") or "private").lower(),
        "publish_at": take("publish_at", "publishAt"),
        "made_for_kids": take("made_for_kids", "madeForKids"),
    }

    if not cfg["video_path"]:
        raise ConfigError("'video_path' est requis (chemin vers le fichier vidéo)")
    if not cfg["title"]:
        raise ConfigError("'title' est requis")
    if cfg["tags"] and not isinstance(cfg["tags"], list):
        raise ConfigError("'tags' doit être une liste de chaînes")

    # Bloc optionnel 'enhance'
    enh_raw = raw.get("enhance")
    enhance_cfg = None
    if enh_raw is not None:
        if not isinstance(enh_raw, dict):
            raise ConfigError("'enhance' doit être un objet/dict")
        # Valider et copier uniquement les clés supportées
        supported = {
            "enabled",
            "quality",
            "codec",
            "hwaccel",
            "loudnorm",
            "deband",
            "deblock",
            "sharpen_amount",
            "contrast",
            "saturation",
            "scale",
            "fps",
            "denoise",
            "sharpen",
            "deinterlace",
            "color_fix",
            "crf",
            "bitrate",
            "preset",
            "reencode_audio",
            "audio_bitrate",
        }
        enhance_cfg = {}
        for k, v in enh_raw.items():
            if k not in supported:
                continue
            enhance_cfg[k] = v
        # Types de base
        if "enabled" in enhance_cfg and not isinstance(enhance_cfg["enabled"], bool):
            raise ConfigError("'enhance.enabled' doit être booléen")
        if "quality" in enhance_cfg:
            if not isinstance(enhance_cfg["quality"], str):
                raise ConfigError("'enhance.quality' doit être une chaîne")
            allowed = {"low", "medium", "high", "youtube", "max"}
            if enhance_cfg["quality"] not in allowed:
                raise ConfigError("'enhance.quality' doit être parmi: " + ", ".join(sorted(allowed)))
        if "codec" in enhance_cfg:
            if not isinstance(enhance_cfg["codec"], str):
                raise ConfigError("'enhance.codec' doit être une chaîne")
            allowedc = {"h264", "hevc", "vp9", "av1"}
            if enhance_cfg["codec"].lower() not in allowedc:
                raise ConfigError("'enhance.codec' doit être parmi: " + ", ".join(sorted(allowedc)))
        if "hwaccel" in enhance_cfg:
            if not isinstance(enhance_cfg["hwaccel"], str):
                raise ConfigError("'enhance.hwaccel' doit être une chaîne")
            allowedh = {"none", "auto", "videotoolbox"}
            if enhance_cfg["hwaccel"].lower() not in allowedh:
                raise ConfigError("'enhance.hwaccel' doit être parmi: " + ", ".join(sorted(allowedh)))
        if "fps" in enhance_cfg and not (isinstance(enhance_cfg["fps"], (int, float)) or enhance_cfg["fps"] is None):
            raise ConfigError("'enhance.fps' doit être un nombre")
        if "crf" in enhance_cfg and not isinstance(enhance_cfg["crf"], int):
            raise ConfigError("'enhance.crf' doit être un entier")
        if "loudnorm" in enhance_cfg and not isinstance(enhance_cfg["loudnorm"], bool):
            raise ConfigError("'enhance.loudnorm' doit être booléen")
        if "deband" in enhance_cfg and not isinstance(enhance_cfg["deband"], bool):
            raise ConfigError("'enhance.deband' doit être booléen")
        if "deblock" in enhance_cfg and not isinstance(enhance_cfg["deblock"], bool):
            raise ConfigError("'enhance.deblock' doit être booléen")
        if "sharpen_amount" in enhance_cfg and not isinstance(enhance_cfg["sharpen_amount"], (int, float)):
            raise ConfigError("'enhance.sharpen_amount' doit être un nombre (0.0-1.0)")
        if "contrast" in enhance_cfg and not isinstance(enhance_cfg["contrast"], (int, float)):
            raise ConfigError("'enhance.contrast' doit être un nombre (ex: 1.07)")
        if "saturation" in enhance_cfg and not isinstance(enhance_cfg["saturation"], (int, float)):
            raise ConfigError("'enhance.saturation' doit être un nombre (ex: 1.12)")
        # Pas d'autre validation stricte ici pour rester flexible

    cfg["enhance"] = enhance_cfg

    return cfg
