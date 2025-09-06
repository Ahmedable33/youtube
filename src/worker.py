from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Optional

from src.config_loader import load_config, ConfigError
from src.video_enhance import enhance_video, EnhanceError
from src.ai_generator import MetaRequest, generate_metadata
from src.auth import get_credentials, DEFAULT_CLIENT_SECRETS, DEFAULT_TOKEN_FILE
from src.uploader import upload_video


log = logging.getLogger("worker")

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
]


def _quality_defaults(name: Optional[str]) -> dict:
    if not name:
        return {}
    q = (name or "").lower()
    presets = {
        "low": {
            "scale": None,
            "crf": 23,
            "preset": "fast",
            "denoise": True,
            "sharpen": False,
            "color_fix": True,
        },
        "medium": {
            "scale": "1080p",
            "crf": 20,
            "preset": "medium",
            "denoise": True,
            "sharpen": True,
            "color_fix": True,
        },
        "high": {
            "scale": "1440p",
            "crf": 18,
            "preset": "slow",
            "denoise": True,
            "sharpen": True,
            "color_fix": True,
        },
        "youtube": {
            "scale": "1080p",
            "crf": 20,
            "preset": "slow",
            "denoise": True,
            "sharpen": True,
            "color_fix": True,
        },
        "max": {
            "scale": "2160p",
            "crf": 17,
            "preset": "slow",
            "denoise": True,
            "sharpen": True,
            "color_fix": True,
        },
    }
    return presets.get(q, {})


def _read_tasks(queue_dir: Path) -> list[Path]:
    return sorted(queue_dir.glob("task_*.json"))


def _load_task(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_task(path: Path, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _default_title_for(video_path: Path) -> str:
    return video_path.stem.replace("_", " ")[:90]


def process_queue(*, queue_dir: str | Path, archive_dir: str | Path, config_path: Optional[str | Path] = None, log_level: str = "INFO") -> None:
    logging.basicConfig(level=getattr(logging, log_level), format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    qdir = Path(queue_dir)
    adir = Path(archive_dir)
    qdir.mkdir(parents=True, exist_ok=True)
    adir.mkdir(parents=True, exist_ok=True)

    cfg = None
    if config_path:
        try:
            cfg = load_config(config_path)
        except ConfigError as e:
            log.warning("Config non chargée (%s), on continue avec des valeurs par défaut.", e)
            cfg = None

    for task_path in _read_tasks(qdir):
        try:
            task = _load_task(task_path)
            if task.get("status") not in (None, "pending", "error"):
                continue
            video_path = Path(task["video_path"]).resolve()
            if not video_path.exists():
                log.error("Vidéo introuvable: %s", video_path)
                task["status"] = "error"
                task["error"] = f"Video not found: {video_path}"
                _save_task(task_path, task)
                continue

            # Enhance: fusion presets qualité depuis la tâche (prefs.quality) + config
            enhance_cfg = (cfg or {}).get("enhance") if isinstance(cfg, dict) else None
            task_prefs = (task.get("prefs") or {}) if isinstance(task, dict) else {}
            qname = (task_prefs or {}).get("quality")
            if qname:
                base = _quality_defaults(qname)
                # le preset fournit des valeurs par défaut; la config existante a priorité s'il y a conflit
                enhance_cfg = {**base, **(enhance_cfg or {})}
            out_path = video_path.with_name(video_path.stem + ".enhanced.mp4")
            try:
                enhanced = enhance_video(
                    input_path=video_path,
                    output_path=out_path,
                    codec=(enhance_cfg or {}).get("codec", "h264"),
                    hwaccel=(enhance_cfg or {}).get("hwaccel", "none"),
                    scale=(enhance_cfg or {}).get("scale"),
                    fps=(enhance_cfg or {}).get("fps"),
                    denoise=bool((enhance_cfg or {}).get("denoise", False)),
                    sharpen=bool((enhance_cfg or {}).get("sharpen", False)),
                    deband=bool((enhance_cfg or {}).get("deband", False)),
                    deblock=bool((enhance_cfg or {}).get("deblock", False)),
                    sharpen_amount=(enhance_cfg or {}).get("sharpen_amount"),
                    contrast=(enhance_cfg or {}).get("contrast"),
                    saturation=(enhance_cfg or {}).get("saturation"),
                    deinterlace=bool((enhance_cfg or {}).get("deinterlace", False)),
                    color_fix=bool((enhance_cfg or {}).get("color_fix", False)),
                    crf=int((enhance_cfg or {}).get("crf", 18)),
                    bitrate=(enhance_cfg or {}).get("bitrate"),
                    preset=(enhance_cfg or {}).get("preset", "medium"),
                    reencode_audio=bool((enhance_cfg or {}).get("reencode_audio", False)),
                    loudnorm=bool((enhance_cfg or {}).get("loudnorm", False)),
                    audio_bitrate=(enhance_cfg or {}).get("audio_bitrate", "192k"),
                )
                task["enhanced_path"] = str(enhanced)
            except EnhanceError as e:
                log.error("Enhance échoué: %s", e)
                task["status"] = "error"
                task["error"] = f"enhance_failed: {e}"
                _save_task(task_path, task)
                # passer au suivant
                continue

            # Métadonnées SEO: privilégier celles fournies dans la tâche (via Telegram)
            user_meta = (task.get("meta") or {}) if isinstance(task, dict) else {}
            title = user_meta.get("title") if user_meta.get("title") else None
            description = user_meta.get("description") if user_meta.get("description") else None
            tags = list(user_meta.get("tags") or [])

            # Si des champs manquent, compléter via l'IA
            if not title or not description or not tags:
                try:
                    seo_cfg = (cfg or {}).get("seo") if isinstance(cfg, dict) else None
                    seo_provider = (seo_cfg or {}).get("provider") if isinstance(seo_cfg, dict) else None
                    seo_model = (seo_cfg or {}).get("model") if isinstance(seo_cfg, dict) else None
                    seo_host = (seo_cfg or {}).get("host") if isinstance(seo_cfg, dict) else None
                    req = MetaRequest(
                        topic=_default_title_for(video_path),
                        language=((cfg or {}).get("language") or "fr"),
                        tone=((cfg or {}).get("tone") or "informatif"),
                        target_keywords=None,
                        channel_style=None,
                        include_hashtags=True,
                        max_tags=15,
                        max_title_chars=70,
                        provider=seo_provider,
                        model=seo_model or "llama3.1:8b-instruct",
                        host=seo_host,
                        input_text=description if (description and not title) else None,
                    )
                    ai_meta = generate_metadata(req)
                    if not title:
                        title = ai_meta.get("title") or _default_title_for(video_path)
                    if not description:
                        description = ai_meta.get("description") or ""
                    if not tags:
                        tags = ai_meta.get("tags") or []
                except Exception as e:
                    log.warning("AI metadata non générées (%s), on complète avec des valeurs par défaut.", e)
                    if not title:
                        title = _default_title_for(video_path)
                    if not description:
                        description = ""
                    if not tags:
                        tags = []

            # Normaliser tags (unicité, minuscule)
            if tags:
                tags = sorted({str(t).strip().lstrip('#').lower() for t in tags if str(t).strip()})

            # Upload
            creds = get_credentials(SCOPES, client_secrets_path=DEFAULT_CLIENT_SECRETS, token_path=DEFAULT_TOKEN_FILE)
            # Champs additionnels YouTube
            cfg_lang = (cfg or {}).get("language") if isinstance(cfg, dict) else None
            cfg_priv = (cfg or {}).get("privacy_status") if isinstance(cfg, dict) else None
            cfg_cat = (cfg or {}).get("category_id") if isinstance(cfg, dict) else None
            cfg_license = (cfg or {}).get("license") if isinstance(cfg, dict) else None  # "youtube" | "creativeCommon"
            cfg_emb = (cfg or {}).get("embeddable") if isinstance(cfg, dict) else None
            cfg_public_stats = (cfg or {}).get("public_stats_viewable") if isinstance(cfg, dict) else None
            cfg_default_audio_lang = (cfg or {}).get("default_audio_language") if isinstance(cfg, dict) else None

            # Derivations à partir de la tâche
            task_meta = (task.get("meta") or {}) if isinstance(task, dict) else {}
            lang = task_meta.get("language") or cfg_lang or "fr"
            privacy_status = (task.get("privacy_status")
                              or task_meta.get("privacy_status")
                              or cfg_priv or "private")
            category_id = (task.get("category_id")
                           or task_meta.get("category_id")
                           or cfg_cat or 22)
            made_for_kids = (task.get("made_for_kids")
                             or task_meta.get("made_for_kids")
                             or (cfg or {}).get("made_for_kids"))

            # Date d'enregistrement: utiliser received_at si présent
            recording_date = (task.get("received_at") if isinstance(task.get("received_at"), str) else None)

            resp = upload_video(
                creds,
                video_path=str(enhanced),
                title=title,
                description=description,
                tags=tags,
                category_id=category_id,
                privacy_status=privacy_status,
                publish_at=(cfg or {}).get("publish_at"),
                thumbnail_path=(cfg or {}).get("thumbnail_path"),
                made_for_kids=made_for_kids,
                embeddable=cfg_emb if cfg_emb is not None else True,
                license=cfg_license or "youtube",
                public_stats_viewable=cfg_public_stats if cfg_public_stats is not None else True,
                default_language=lang,
                default_audio_language=cfg_default_audio_lang or lang,
                recording_date=recording_date,
            )
            vid = resp.get("id")
            log.info("Upload réussi: video id=%s", vid)
            task["status"] = "done"
            task["youtube_id"] = vid
            _save_task(task_path, task)

            # Archive
            dest = Path(archive_dir) / task_path.name
            shutil.move(str(task_path), str(dest))
        except Exception as e:
            log.exception("Erreur inattendue sur %s: %s", task_path, e)
            try:
                task = _load_task(task_path)
                task["status"] = "error"
                task["error"] = str(e)
                _save_task(task_path, task)
            except Exception:
                pass
