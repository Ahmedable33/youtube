from __future__ import annotations

import json
import logging
import shutil
import subprocess
from datetime import datetime
import re
from pathlib import Path
from typing import Optional
import smtplib
from email.message import EmailMessage
import os

from src.config_loader import load_config, ConfigError
from src.video_enhance import enhance_video, EnhanceError
from src.ai_generator import MetaRequest, generate_metadata
from src.scheduler import UploadScheduler
from src.subtitle_generator import (
    is_whisper_available,
    detect_language,
    generate_subtitles,
)
from .thumbnail_generator import get_best_thumbnail
from .multi_account_manager import create_multi_account_manager

log = logging.getLogger("worker")

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

# Test-friendly aliases and defaults (avoid import-time heavy deps)
upload_video = None  # type: ignore
get_credentials = None  # type: ignore
DEFAULT_CLIENT_SECRETS = "config/client_secret.json"
DEFAULT_TOKEN_FILE = "config/token.json"
smart_upload_captions = None  # type: ignore

# Alias modulaire patchable par les tests
smart_upload_captions = None  # type: ignore


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


def _clean_title(title: str) -> str:
    """Nettoie le titre: supprime les préfixes et guillemets superflus.
    - Retire les préfixes comme 'Titre utilisateur:' ou 'Title:' (case-insensitive)
    - Retire les guillemets et guillemets français entourant tout le titre
    """
    if not isinstance(title, str):
        return title
    s = title.strip()
    # Retirer préfixes
    s = re.sub(
        r"^(titre\s*utilisateur\s*:\s*|title\s*:\s*)", "", s, flags=re.IGNORECASE
    )
    s = s.strip()
    # Retirer guillemets paires
    pairs = [("«", "»"), ("“", "”"), ('"', '"'), ("'", "'")]
    for lq, rq in pairs:
        if s.startswith(lq) and s.endswith(rq) and len(s) >= 2:
            s = s[1:-1].strip()
            break
    return s


def _to_rfc3339_utc_from_dt(dt: datetime) -> str:
    """Convertit un datetime timezone-aware en RFC3339 UTC '...Z' sans microsecondes."""
    if dt.tzinfo is None:
        from datetime import timezone as _tz

        dt = dt.replace(tzinfo=_tz.utc)
    else:
        from datetime import timezone as _tz

        dt = dt.astimezone(_tz.utc)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _notify_email(email_cfg: dict, subject: str, body: str) -> None:
    try:
        if not isinstance(email_cfg, dict) or not email_cfg.get("enabled"):
            return
        to_field = email_cfg.get("to") or []
        if isinstance(to_field, str):
            recipients = [t.strip() for t in to_field.split(",") if t.strip()]
        else:
            recipients = [str(t).strip() for t in to_field if str(t).strip()]
        if not recipients:
            return
        host = str(email_cfg.get("host", "localhost"))
        port = int(email_cfg.get("port", 587))
        use_tls = bool(email_cfg.get("tls", True))
        username = email_cfg.get("username")
        # Prefer environment variable if specified
        password_env_key = email_cfg.get("password_env")
        password = None
        if password_env_key:
            password = os.getenv(str(password_env_key))
        if not password:
            password = email_cfg.get("password")
        sender = email_cfg.get("from") or username or "noreply@example.com"

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = ", ".join(recipients)
        msg.set_content(body)

        with smtplib.SMTP(host, port, timeout=15) as server:
            if use_tls:
                try:
                    server.starttls()
                except Exception:
                    pass
            if username:
                try:
                    server.login(str(username), str(password or ""))
                except Exception:
                    pass
            server.send_message(msg)

        log.info("Notification email envoyée à: %s", ",".join(recipients))
    except Exception as e:
        log.warning("Notification email échouée: %s", e)


def _add_video_to_playlist(
    credentials, video_id: str, playlist_id: str, position: Optional[int] = None
) -> None:
    """Ajoute la vidéo à une playlist YouTube si un playlist_id est fourni."""
    try:
        from googleapiclient.discovery import build  # type: ignore
    except Exception as e:
        log.warning("googleapiclient indisponible, ajout playlist ignoré: %s", e)
        return

    try:
        service = build("youtube", "v3", credentials=credentials)
        body = {
            "snippet": {
                "playlistId": str(playlist_id),
                "resourceId": {"kind": "youtube#video", "videoId": video_id},
            }
        }
        if position is not None:
            body["snippet"]["position"] = int(position)
        service.playlistItems().insert(part="snippet", body=body).execute()
        log.info("Vidéo %s ajoutée à la playlist %s", video_id, playlist_id)
    except Exception as e:
        log.error("Échec ajout vidéo %s à la playlist %s: %s", video_id, playlist_id, e)


def _read_tasks(queue_dir: Path) -> list[Path]:
    # Inclure les tâches normales et celles issues du scheduler
    tasks = list(queue_dir.glob("task_*.json"))
    tasks += list(queue_dir.glob("scheduled_*.json"))
    return sorted(tasks)


def _load_task(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_task(path: Path, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _process_subtitles(
    creds, video_id: str, video_path: Path, subtitles_cfg: dict, task: dict
):
    """
    Génère et upload les sous-titres pour une vidéo

    Args:
        creds: Credentials YouTube
        video_id: ID de la vidéo YouTube
        video_path: Chemin vers la vidéo
        subtitles_cfg: Configuration des sous-titres
        task: Données de la tâche
    """
    if not is_whisper_available():
        log.warning(
            "Whisper non disponible, sous-titres ignorés. Installez avec: pip install openai-whisper"
        )
        return

    model = subtitles_cfg.get("whisper_model", "base")
    languages = subtitles_cfg.get("languages", ["fr"])
    auto_detect = subtitles_cfg.get("auto_detect_language", True)
    translate_en = subtitles_cfg.get("translate_to_english", False)
    upload_youtube = subtitles_cfg.get("upload_to_youtube", True)
    draft_mode = subtitles_cfg.get("draft_mode", False)
    replace_existing = subtitles_cfg.get("replace_existing", False)

    # Dossier de sortie pour les sous-titres
    subtitles_dir = video_path.parent / "subtitles"
    subtitles_dir.mkdir(exist_ok=True)

    log.info("Génération sous-titres pour vidéo %s", video_id)

    try:
        # Détecter la langue source si demandé
        source_language = None
        if auto_detect:
            try:
                source_language = detect_language(video_path, model)
                log.info("Langue détectée: %s", source_language)
            except Exception as e:
                log.warning("Échec détection langue: %s", e)

        # Si pas de détection, utiliser la première langue de la liste
        if not source_language and languages:
            source_language = languages[0]

        subtitle_files = {}

        # Générer pour chaque langue demandée
        for lang in languages:
            try:
                srt_path = subtitles_dir / f"{video_path.stem}_{lang}.srt"

                if lang == source_language:
                    # Transcription dans la langue source
                    generate_subtitles(
                        video_path=video_path,
                        output_path=srt_path,
                        language=source_language,
                        model=model,
                    )
                elif lang == "en" and translate_en:
                    # Traduction vers l'anglais
                    generate_subtitles(
                        video_path=video_path,
                        output_path=srt_path,
                        language=source_language,
                        model=model,
                        translate_to_english=True,
                    )
                else:
                    # Génération directe dans la langue cible
                    generate_subtitles(
                        video_path=video_path,
                        output_path=srt_path,
                        language=lang,
                        model=model,
                    )

                if srt_path.exists():
                    subtitle_files[lang] = srt_path
                    log.info("Sous-titres générés: %s", srt_path)

            except Exception as e:
                log.error("Échec génération sous-titres %s: %s", lang, e)

        # Ajouter traduction anglaise si demandée et pas déjà présente
        if translate_en and "en" not in subtitle_files and source_language != "en":
            try:
                en_srt_path = subtitles_dir / f"{video_path.stem}_en.srt"
                generate_subtitles(
                    video_path=video_path,
                    output_path=en_srt_path,
                    language=source_language,
                    model=model,
                    translate_to_english=True,
                )
                if en_srt_path.exists():
                    subtitle_files["en"] = en_srt_path
                    log.info("Traduction anglaise générée: %s", en_srt_path)
            except Exception as e:
                log.error("Échec traduction anglaise: %s", e)

        # Upload vers YouTube si demandé
        if upload_youtube and subtitle_files:
            try:
                # Utiliser la fonction patchée si disponible, sinon importer paresseusement
                _fn = globals().get("smart_upload_captions")
                if not callable(_fn):
                    from src.youtube_captions import smart_upload_captions as _impl

                    _fn = _impl
                results = _fn(
                    credentials=creds,
                    video_id=video_id,
                    subtitle_files=subtitle_files,
                    replace_existing=replace_existing,
                    is_draft=draft_mode,
                )

                # Logger les résultats
                for lang, result in results.items():
                    if result.get("success"):
                        action = result.get("action", "unknown")
                        log.info(
                            "Sous-titres %s %s: %s",
                            lang,
                            action,
                            result.get("caption_id"),
                        )
                    else:
                        log.error(
                            "Échec upload sous-titres %s: %s", lang, result.get("error")
                        )

                # Sauvegarder les infos dans la tâche
                task["subtitles"] = {
                    "generated": list(subtitle_files.keys()),
                    "uploaded": [
                        lang
                        for lang, result in results.items()
                        if result.get("success")
                    ],
                    "source_language": source_language,
                }

            except Exception as e:
                log.error("Erreur upload sous-titres vers YouTube: %s", e)
        else:
            # Sauvegarder seulement les infos de génération
            task["subtitles"] = {
                "generated": list(subtitle_files.keys()),
                "uploaded": [],
                "source_language": source_language,
            }

    except Exception as e:
        log.error("Erreur génération sous-titres: %s", e)
        raise


def _default_title_for(video_path: Path) -> str:
    return video_path.stem.replace("_", " ")[:90]


def _probe_audio_language(video_path: Path) -> Optional[str]:
    """Détecte la langue audio via ffprobe (métadonnées stream).

    Returns:
        Code langue ISO (ex: 'fr', 'en') ou None
    """
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream_tags=language",
            "-of",
            "default=nk=1:nw=1",
            str(video_path),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if res.returncode == 0:
            lang = (res.stdout or "").strip().lower()
            if lang and lang != "und":
                return lang
    except Exception as e:
        log.debug("ffprobe audio language detection failed: %s", e)
    return None


def _generate_placeholder_thumbnail(
    output_path: Path, width: int = 1280, height: int = 720
) -> bool:
    """Génère un placeholder thumbnail (image noire + texte) si tout échoue.

    Returns:
        True si réussi, False si Pillow non disponible
    """
    try:
        from PIL import Image, ImageDraw, ImageFont

        img = Image.new("RGB", (width, height), color="black")
        draw = ImageDraw.Draw(img)

        try:
            # Essayer d'utiliser une fonte par défaut
            font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 48
            )
        except Exception:
            font = ImageFont.load_default()

        text = "Video Thumbnail"
        # Centrer le texte
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        position = ((width - text_width) // 2, (height - text_height) // 2)

        draw.text(position, text, fill="white", font=font)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(output_path), "JPEG", quality=85)
        log.info("Placeholder thumbnail générée: %s", output_path)
        return True
    except ImportError:
        log.warning("Pillow non disponible, impossible de créer placeholder thumbnail")
        return False
    except Exception as e:
        log.error("Erreur génération placeholder thumbnail: %s", e)
        return False


def _handle_scheduled_task(
    task: dict, task_path: Path, scheduler: UploadScheduler
) -> bool:
    """
    Gérer une tâche avec planification

    Returns:
        True si la tâche doit être traitée maintenant, False si elle doit être planifiée
    """
    schedule_mode = task.get("schedule_mode", "now")

    if schedule_mode == "now":
        return True

    elif schedule_mode == "auto":
        # Planifier automatiquement aux heures optimales
        try:
            scheduled_task = scheduler.schedule_task(task_path)
            log.info(
                f"Tâche planifiée automatiquement: {scheduled_task.task_id} pour {scheduled_task.scheduled_time}"
            )
            return False
        except Exception as e:
            log.error(f"Erreur planification automatique: {e}")
            return True  # Fallback: traiter immédiatement

    elif schedule_mode == "custom":
        # Planifier à une heure spécifique
        custom_time_str = task.get("custom_schedule_time")
        if custom_time_str:
            try:
                from datetime import datetime
                import pytz

                custom_time = datetime.fromisoformat(custom_time_str)
                # Ajouter timezone si manquant
                if custom_time.tzinfo is None:
                    tz = pytz.timezone("Europe/Paris")
                    custom_time = tz.localize(custom_time)

                # Vérifier si c'est dans le futur
                now = datetime.now(pytz.timezone("Europe/Paris"))
                if custom_time <= now:
                    log.warning(
                        f"Heure planifiée dans le passé, traitement immédiat: {custom_time}"
                    )
                    return True

                scheduled_task = scheduler.schedule_task(
                    task_path, scheduled_time=custom_time
                )
                log.info(
                    f"Tâche planifiée pour {custom_time}: {scheduled_task.task_id}"
                )
                return False

            except Exception as e:
                log.error(f"Erreur planification personnalisée: {e}")
                return True  # Fallback: traiter immédiatement
        else:
            log.warning("Mode custom sans heure spécifiée, traitement immédiat")
            return True

    return True  # Fallback par défaut


def process_queue(
    *,
    queue_dir: str | Path,
    archive_dir: str | Path,
    config_path: Optional[str | Path] = None,
    log_level: str = "INFO",
) -> None:
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    qdir = Path(queue_dir)
    adir = Path(archive_dir)
    qdir.mkdir(parents=True, exist_ok=True)
    adir.mkdir(parents=True, exist_ok=True)

    # Initialiser le scheduler pour la planification
    schedule_dir = qdir.parent / "schedule"
    scheduler = UploadScheduler(
        config_path=config_path or Path("config/video.yaml"), schedule_dir=schedule_dir
    )

    cfg = None
    if config_path:
        try:
            cfg = load_config(config_path)
        except ConfigError as e:
            log.warning(
                "Config non chargée (%s), on continue avec des valeurs par défaut.", e
            )
            cfg = None

    for task_path in _read_tasks(qdir):
        try:
            task = _load_task(task_path)
            if task.get("status") not in (None, "pending", "error"):
                continue

            # Vérifier si la tâche doit être planifiée
            if not _handle_scheduled_task(task, task_path, scheduler):
                # Tâche planifiée, la supprimer de la queue normale
                archive_path = adir / task_path.name
                shutil.move(str(task_path), str(archive_path))
                log.info(f"Tâche déplacée vers planification: {task_path.name}")
                continue
            video_path = Path(task["video_path"]).resolve()
            if not video_path.exists():
                log.error("Vidéo introuvable: %s", video_path)
                task["status"] = "error"
                task["error"] = f"Video not found: {video_path}"
                _save_task(task_path, task)
                # Archiver la tâche en erreur pour ne pas bloquer la file
                archive_path = adir / task_path.name
                shutil.move(str(task_path), str(archive_path))
                log.info(f"Tâche archivée (erreur fichier manquant): {archive_path}")
                continue

            # Enhance: fusion presets qualité depuis la tâche (prefs.quality) + config
            enhance_cfg = (cfg or {}).get("enhance") if isinstance(cfg, dict) else None
            task_prefs = (task.get("prefs") or {}) if isinstance(task, dict) else {}
            qname = (task_prefs or {}).get("quality")
            if qname:
                base = _quality_defaults(qname)
                # le preset fournit des valeurs par défaut; la config existante a priorité s'il y a conflit
                enhance_cfg = {**base, **(enhance_cfg or {})}

            # Amélioration vidéo (si activée et non skippée)
            enhanced = Path(video_path)
            skip_enhance = task.get("skip_enhance", False)

            if skip_enhance:
                log.info("Amélioration skippée (upload direct demandé)")
            elif enhance_cfg and enhance_cfg.get("enabled", True):
                try:
                    log.info("Amélioration vidéo en cours...")
                    out_path = video_path.with_name(video_path.stem + ".enhanced.mp4")
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
                        loudnorm=bool((enhance_cfg or {}).get("loudnorm", False)),
                        crf=(enhance_cfg or {}).get("crf"),
                        bitrate=(enhance_cfg or {}).get("bitrate"),
                        preset=(enhance_cfg or {}).get("preset", "medium"),
                        reencode_audio=bool(
                            (enhance_cfg or {}).get("reencode_audio", True)
                        ),
                        audio_bitrate=(enhance_cfg or {}).get("audio_bitrate", "192k"),
                    )
                    log.info("Amélioration terminée: %s", enhanced)
                except EnhanceError as e:
                    log.error("Erreur d'amélioration: %s", e)
                    # Continuer avec la vidéo originale
                    enhanced = Path(video_path)

            # Métadonnées SEO: privilégier celles fournies dans la tâche (via Telegram)
            user_meta = (task.get("meta") or {}) if isinstance(task, dict) else {}
            title = user_meta.get("title") if user_meta.get("title") else None
            description = (
                user_meta.get("description") if user_meta.get("description") else None
            )
            tags = list(user_meta.get("tags") or [])

            # Si des champs manquent ou si config impose le titre IA depuis la description
            try:
                seo_cfg = (cfg or {}).get("seo") if isinstance(cfg, dict) else None
                if not seo_cfg:
                    # Fallback: lire le YAML brut pour récupérer le bloc seo
                    try:
                        import yaml

                        cfg_path = (
                            Path(config_path)
                            if config_path
                            else Path("config/video.yaml")
                        )
                        if cfg_path.exists():
                            raw_doc = (
                                yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
                                or {}
                            )
                            seo_cfg = raw_doc.get("seo")
                    except Exception:
                        seo_cfg = None
                seo_provider = (
                    (seo_cfg or {}).get("provider")
                    if isinstance(seo_cfg, dict)
                    else None
                )
                seo_model = (
                    (seo_cfg or {}).get("model") if isinstance(seo_cfg, dict) else None
                )
                seo_host = (
                    (seo_cfg or {}).get("host") if isinstance(seo_cfg, dict) else None
                )
                force_ai_title = (
                    bool((seo_cfg or {}).get("force_title_from_description", False))
                    if isinstance(seo_cfg, dict)
                    else False
                )
                # Préférence par chat : surchage le YAML si présent
                try:
                    task_prefs = (
                        (task.get("prefs") or {}) if isinstance(task, dict) else {}
                    )
                    if "ai_title_force" in task_prefs:
                        force_ai_title = bool(task_prefs.get("ai_title_force"))
                except Exception:
                    pass

                # Règle spéciale Telegram: toujours affiner le titre et les tags à l'aide de l'IA,
                # même s'ils existent déjà, pour les rendre plus percutants.
                is_telegram = task.get("source") == "telegram"
                need_ai = (
                    is_telegram
                    or force_ai_title
                    or (not title or not description or not tags)
                )
                if need_ai:
                    req = MetaRequest(
                        # Si un titre existe, l'utiliser comme topic de base; sinon fallback sur le nom de fichier
                        topic=(title or _default_title_for(video_path)),
                        language=((cfg or {}).get("language") or "fr"),
                        tone=((cfg or {}).get("tone") or "informatif"),
                        target_keywords=None,
                        channel_style=None,
                        include_hashtags=True,
                        include_category=True,
                        max_tags=15,
                        max_title_chars=70,
                        provider=seo_provider,
                        # Ne définir model/host que pour Ollama. Pour OpenAI, laisser None pour que
                        # src.ai_generator choisisse OPENAI_MODEL ou sa valeur par défaut.
                        model=(
                            seo_model
                            if ((seo_provider or "").lower() == "ollama")
                            else None
                        ),
                        host=(
                            seo_host
                            if ((seo_provider or "").lower() == "ollama")
                            else None
                        ),
                        # Contexte: inclure titre + description s'ils existent pour guider la réécriture
                        input_text=(
                            (f"Titre utilisateur: {title}\n\n" if title else "")
                            + (description or "")
                        )
                        or None,
                    )
                    ai_meta = generate_metadata(
                        req,
                        config_path=(
                            str(config_path) if config_path else "config/video.yaml"
                        ),
                        video_path=str(video_path),
                    )

                    # Si la tâche vient de Telegram: toujours remplacer titre et tags avec la version IA
                    if is_telegram:
                        title = ai_meta.get("title") or (
                            title or _default_title_for(video_path)
                        )
                        title = _clean_title(title)
                        tags = ai_meta.get("tags") or []
                        # Ne pas écraser la description utilisateur si elle existe; compléter seulement si absente
                        if not description:
                            description = ai_meta.get("description") or ""
                    else:
                        # Cas standard: Titre: remplacer si force_ai_title, sinon seulement s'il manque
                        if force_ai_title or not title:
                            title = ai_meta.get("title") or _default_title_for(
                                video_path
                            )
                            title = _clean_title(title)
                        # Description/Tags: compléter seulement si manquants
                        if not description:
                            description = ai_meta.get("description") or ""
                        if not tags:
                            tags = ai_meta.get("tags") or []
                    # Stocker la catégorie générée automatiquement pour usage ultérieur
                    ai_generated_category = ai_meta.get("category_id")
                else:
                    ai_generated_category = None
            except Exception as e:
                log.warning(
                    "AI metadata non générées (%s), on complète avec des valeurs par défaut.",
                    e,
                )
                ai_generated_category = None
                if not title:
                    title = _default_title_for(video_path)
                if not description:
                    description = ""
                if not tags:
                    tags = []

            # Normaliser tags (unicité, minuscule) – pas de limitation stricte
            if tags:
                tags = sorted(
                    {str(t).strip().lstrip("#").lower() for t in tags if str(t).strip()}
                )

            # Titre/description: seulement un défaut si vide, pas de troncature
            if not title or not str(title).strip():
                title = _default_title_for(video_path)

            # Obtenir les credentials YouTube avec gestion multi-comptes
            try:
                # Charger la config brute pour lire multi_accounts (ne pas utiliser load_config qui normalise)
                import yaml

                raw_cfg_path = Path("config/video.yaml")
                multi_accounts_enabled = False
                if raw_cfg_path.exists():
                    try:
                        raw_cfg = (
                            yaml.safe_load(raw_cfg_path.read_text(encoding="utf-8"))
                            or {}
                        )
                        multi_accounts_enabled = bool(
                            (raw_cfg.get("multi_accounts") or {}).get("enabled", False)
                        )
                    except Exception:
                        multi_accounts_enabled = False

                if multi_accounts_enabled:
                    # Utiliser le gestionnaire multi-comptes
                    manager = create_multi_account_manager()

                    # Obtenir le compte pour ce chat ou le meilleur compte disponible
                    chat_id = task.get("chat_id")
                    if chat_id:
                        account = manager.get_chat_account(str(chat_id))
                    else:
                        account = manager.get_best_account_for_upload()

                    if not account:
                        log.error("Aucun compte YouTube disponible pour upload")
                        # Marquer la tâche en erreur et archiver
                        try:
                            task["status"] = "error"
                            task["error"] = "No YouTube account available"
                            _save_task(task_path, task)
                            archive_path = adir / task_path.name
                            shutil.move(str(task_path), str(archive_path))
                            log.info(
                                f"Tâche archivée (aucun compte disponible): {archive_path}"
                            )
                        except Exception as _e:
                            log.warning(
                                f"Impossible d'archiver la tâche sans compte: {_e}"
                            )
                        continue

                    log.info(
                        f"Utilisation du compte: {account.name} ({account.account_id})"
                    )
                    credentials = manager.get_credentials_for_account(
                        account.account_id
                    )

                    # Enregistrer l'utilisation du compte après upload réussi
                    upload_account_id = account.account_id
                else:
                    # Mode single compte classique
                    _get_credentials = globals().get("get_credentials")
                    if not callable(_get_credentials):
                        from src.auth import get_credentials as _impl

                        _get_credentials = _impl
                    credentials = _get_credentials(
                        SCOPES,
                        client_secrets_path=DEFAULT_CLIENT_SECRETS,
                        token_path=DEFAULT_TOKEN_FILE,
                    )
                    upload_account_id = None

            except Exception as e:
                log.error(f"Erreur credentials YouTube: {e}")
                return False

            # Champs additionnels YouTube
            cfg_lang = (cfg or {}).get("language") if isinstance(cfg, dict) else None
            cfg_priv = (
                (cfg or {}).get("privacy_status") if isinstance(cfg, dict) else None
            )
            cfg_license = (
                (cfg or {}).get("license") if isinstance(cfg, dict) else None
            )  # "youtube" | "creativeCommon"
            cfg_emb = (cfg or {}).get("embeddable") if isinstance(cfg, dict) else None
            cfg_public_stats = (
                (cfg or {}).get("public_stats_viewable")
                if isinstance(cfg, dict)
                else None
            )
            cfg_default_audio_lang = (
                (cfg or {}).get("default_audio_language")
                if isinstance(cfg, dict)
                else None
            )

            # Derivations à partir de la tâche
            task_meta = (task.get("meta") or {}) if isinstance(task, dict) else {}
            lang = task_meta.get("language") or cfg_lang or "fr"
            privacy_status = (
                task.get("privacy_status")
                or task_meta.get("privacy_status")
                or cfg_priv
                or "public"
            )

            # Brancher Vision (Ollama) pour catégorie si activée (toujours tenter si activé)
            vision_cat = None
            vision_cfg = (cfg or {}).get("vision") if isinstance(cfg, dict) else None
            if isinstance(vision_cfg, dict) and vision_cfg.get("enabled", False):
                try:
                    from src.vision_analyzer import VisionAnalyzer
                    from src.thumbnail_generator import extract_frames

                    analyzer = VisionAnalyzer(
                        host=(vision_cfg or {}).get("host"),
                        model=(vision_cfg or {}).get("model", "llava"),
                        timeout=int((vision_cfg or {}).get("timeout", 60)),
                    )
                    # Extraire quelques frames pour l'analyse
                    frames = extract_frames(Path(enhanced), num_frames=3)
                    if frames:
                        analysis = analyzer.analyze_video(Path(enhanced), num_frames=3)
                        vision_cat = analysis.get("category_id")
                        if vision_cat is not None:
                            log.info("Catégorie Vision détectée: %s", vision_cat)
                except Exception as ve:
                    log.warning("Échec analyse Vision pour catégorie: %s", ve)

            # Catégorie: uniquement IA/Vision, sinon 22 (ignorer catégorie utilisateur et config)
            category_id = vision_cat or ai_generated_category or 22
            # Validation categoryId
            valid_categories = {
                "1",
                "2",
                "10",
                "15",
                "17",
                "19",
                "20",
                "22",
                "23",
                "24",
                "25",
                "26",
                "27",
                "28",
            }
            try:
                if str(category_id) not in valid_categories:
                    log.warning("categoryId invalide %s, fallback 22", category_id)
                    category_id = 22
            except Exception:
                category_id = 22
            made_for_kids = (
                task.get("made_for_kids")
                or task_meta.get("made_for_kids")
                or (cfg or {}).get("made_for_kids")
            )
            # Forcer made_for_kids à False par défaut
            if made_for_kids is None:
                made_for_kids = False

            # Date d'enregistrement: utiliser received_at si présent
            recording_date = (
                task.get("received_at")
                if isinstance(task.get("received_at"), str)
                else None
            )

            # Génération automatique de thumbnail (INFAILLIBLE)
            thumbnail_path = None
            thumb_output = enhanced.parent / f"{enhanced.stem}_thumb.jpg"

            # Niveau 1: get_best_thumbnail (frame 30% ou 5s)
            try:
                generated_thumb = get_best_thumbnail(enhanced, thumb_output)
                if generated_thumb and generated_thumb.exists():
                    thumbnail_path = str(generated_thumb)
                    log.info("Thumbnail générée (best): %s", thumbnail_path)
            except Exception as e:
                log.warning("Échec get_best_thumbnail: %s", e)

            # Niveau 2: fallback ffmpeg frame simple (1s)
            if not thumbnail_path:
                try:
                    cmd = [
                        "ffmpeg",
                        "-y",
                        "-v",
                        "error",
                        "-ss",
                        "00:00:01",
                        "-i",
                        str(enhanced),
                        "-vframes",
                        "1",
                        "-q:v",
                        "2",
                        str(thumb_output),
                    ]
                    res = subprocess.run(
                        cmd, capture_output=True, text=True, timeout=30
                    )
                    if res.returncode == 0 and thumb_output.exists():
                        thumbnail_path = str(thumb_output)
                        log.info(
                            "Thumbnail générée (ffmpeg fallback): %s", thumbnail_path
                        )
                    else:
                        log.warning("Échec ffmpeg fallback: %s", res.stderr)
                except Exception as e:
                    log.warning("Erreur ffmpeg fallback: %s", e)

            # Niveau 3: placeholder (Pillow) - TOUJOURS réussit si Pillow disponible
            if not thumbnail_path:
                log.warning("Génération placeholder thumbnail (dernière tentative)...")
                if _generate_placeholder_thumbnail(thumb_output):
                    thumbnail_path = str(thumb_output)
                else:
                    log.error("IMPOSSIBLE de générer une miniature (même placeholder)")

            try:
                _upload_video = globals().get("upload_video")
                if not callable(_upload_video):
                    from src.uploader import upload_video as _impl

                    _upload_video = _impl
                # Déterminer publish_at final
                task_publish_at = (
                    task.get("publish_at")
                    or (
                        task_meta.get("publish_at")
                        if isinstance(task_meta, dict)
                        else None
                    )
                    or (
                        (cfg or {}).get("publish_at") if isinstance(cfg, dict) else None
                    )
                )
                publish_at_final = task_publish_at
                if (privacy_status or "").lower() == "private" and not publish_at_final:
                    try:
                        slot_dt = scheduler.find_next_optimal_slot()
                        publish_at_final = _to_rfc3339_utc_from_dt(slot_dt)
                        log.info("publishAt auto fixé: %s", publish_at_final)
                    except Exception as e:
                        log.warning("Auto planification publishAt échouée: %s", e)

                resp = _upload_video(
                    credentials,
                    video_path=str(enhanced),
                    title=title,
                    description=description,
                    tags=tags,
                    category_id=category_id,
                    privacy_status=privacy_status,
                    publish_at=publish_at_final,
                    thumbnail_path=thumbnail_path or (cfg or {}).get("thumbnail_path"),
                    made_for_kids=made_for_kids,
                    embeddable=cfg_emb if cfg_emb is not None else True,
                    license=cfg_license or "youtube",
                    public_stats_viewable=(
                        cfg_public_stats if cfg_public_stats is not None else True
                    ),
                    default_language=lang,
                    default_audio_language=(
                        cfg_default_audio_lang
                        or _probe_audio_language(enhanced)
                        or lang
                    ),
                    recording_date=recording_date,
                )
                vid = resp.get("id")
                log.info("Upload réussi: video id=%s", vid)
                try:
                    import yaml

                    cfg_path = (
                        Path(config_path) if config_path else Path("config/video.yaml")
                    )
                    raw_cfg = (
                        yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
                        if cfg_path.exists()
                        else {}
                    )
                    email_cfg = (
                        (raw_cfg.get("notifications") or {}).get("email")
                        if isinstance(raw_cfg, dict)
                        else None
                    )
                    if isinstance(email_cfg, dict):
                        video_url = f"https://youtu.be/{vid}" if vid else ""
                        subject = f"Publication YouTube: {title}"
                        body_lines = [
                            f"Titre: {title}",
                            f"ID: {vid}",
                            f"URL: {video_url}",
                            f"Visibilité: {privacy_status}",
                            f"publishAt: {publish_at_final or '(immédiat)'}",
                            f"Fichier: {enhanced}",
                        ]
                        if upload_account_id:
                            body_lines.append(f"Compte: {upload_account_id}")
                        _notify_email(email_cfg, subject, "\n".join(body_lines))
                except Exception as _e:
                    log.warning("Notification email ignorée: %s", _e)
                # Ajout éventuel à une playlist si demandée
                try:
                    playlist_id = (
                        task.get("playlist_id")
                        or task_meta.get("playlist_id")
                        or (
                            (cfg or {}).get("playlist_id")
                            if isinstance(cfg, dict)
                            else None
                        )
                    )
                    if playlist_id:
                        _add_video_to_playlist(credentials, vid, str(playlist_id))
                except Exception as e:
                    log.error("Erreur ajout à la playlist: %s", e)
            except Exception as e:
                # Gestion spécifique uploadLimitExceeded (sans dépendre du type exact)
                if "uploadLimitExceeded" in str(
                    e
                ) or "exceeded the number of videos" in str(e):
                    log.warning(f"Limite d'upload YouTube atteinte: {e}")

                    # Marquer la tâche comme bloquée
                    task["status"] = "blocked"
                    task["error"] = "uploadLimitExceeded"
                    task[
                        "error_message"
                    ] = "Limite quotidienne YouTube atteinte. Réessayez dans 24h."
                    task["blocked_at"] = datetime.now().isoformat()

                    # Sauvegarder la tâche bloquée
                    task_path.write_text(
                        json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8"
                    )

                    # Archiver la tâche bloquée
                    archive_path = adir / task_path.name
                    shutil.move(str(task_path), str(archive_path))

                    log.info(f"Tâche marquée comme bloquée et archivée: {archive_path}")

                    # Arrêter le traitement des autres tâches pour éviter les échecs en cascade
                    log.warning(
                        "Arrêt du worker pour éviter d'autres échecs uploadLimitExceeded"
                    )
                    return
                else:
                    # Autres erreurs d'upload
                    raise

            task["status"] = "done"
            task["youtube_id"] = vid
            _save_task(task_path, task)

            # Génération et upload de sous-titres (si activé)
            subtitles_cfg = (
                (cfg or {}).get("subtitles") if isinstance(cfg, dict) else None
            )
            task_subtitles_enabled = task.get("subtitles_enabled", False)
            config_subtitles_enabled = (
                subtitles_cfg.get("enabled", False) if subtitles_cfg else False
            )

            # Activer si demandé dans la tâche OU dans la config
            if task_subtitles_enabled or config_subtitles_enabled:
                try:
                    _process_subtitles(
                        credentials, vid, enhanced, subtitles_cfg or {}, task
                    )
                except Exception as e:
                    log.error("Erreur génération sous-titres pour %s: %s", vid, e)
                    # Ne pas faire échouer la tâche pour les sous-titres
                # Toujours persister les infos de sous-titres (générés/uploadés) si le task a été modifié
                try:
                    _save_task(task_path, task)
                except Exception as _e:
                    log.warning(
                        f"Impossible de sauvegarder les infos de sous-titres: {_e}"
                    )

            # Enregistrer l'utilisation du quota si multi-comptes
            if upload_account_id:
                try:
                    manager.record_upload(upload_account_id, api_calls_used=1600)
                    log.info(f"Quota enregistré pour le compte {upload_account_id}")
                except Exception as e:
                    log.error(f"Erreur enregistrement quota: {e}")

            # Marquer comme terminée si tâche planifiée
            if task.get("scheduled_task_id"):
                try:
                    scheduler.mark_task_completed(task["scheduled_task_id"])
                except Exception as e:
                    log.error("Erreur marquage tâche planifiée terminée: %s", e)

            # Archive
            dest = adir / task_path.name
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
