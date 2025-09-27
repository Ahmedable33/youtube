from __future__ import annotations

import argparse
import sys
import logging
from pathlib import Path
from typing import List, Optional

from src.config_loader import load_config, ConfigError
from src.ai_generator import MetaRequest, generate_metadata, write_metadata_to_config


SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
]


# Test-friendly aliases (monkeypatch points) – resolved lazily if None
get_credentials = None  # type: ignore
upload_video = None  # type: ignore
download_source = None  # type: ignore
enhance_video = None  # type: ignore
run_bot_from_sources = None  # type: ignore
process_queue = None  # type: ignore


def _quality_defaults(name: Optional[str]) -> dict:
    """Retourne un dict d'options par défaut pour un préréglage de qualité.

    Champs possibles: scale, fps, denoise, sharpen, deinterlace, color_fix, crf, bitrate, preset,
    reencode_audio, audio_bitrate.
    """
    if not name:
        return {}
    q = (name or "").lower()
    presets = {
        # Rapide et léger
        "low": {
            "scale": None,
            "crf": 23,
            "preset": "fast",
            "denoise": True,
            "sharpen": False,
            "color_fix": True,
        },
        # Bon équilibre pour la plupart des contenus
        "medium": {
            "scale": "1080p",
            "crf": 20,
            "preset": "medium",
            "denoise": True,
            "sharpen": True,
            "color_fix": True,
        },
        # Plus qualitatif, plus lent
        "high": {
            "scale": "1440p",
            "crf": 18,
            "preset": "slow",
            "denoise": True,
            "sharpen": True,
            "color_fix": True,
        },
        # Optimisé pour YouTube 1080p
        "youtube": {
            "scale": "1080p",
            "crf": 18,
            "preset": "slow",
            "denoise": False,
            "sharpen": True,
            "color_fix": True,
        },
        # Max qualité (plus long et lourd)
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="CLI d'upload YouTube (resumable, planification, miniature)",
    )
    sub = p.add_subparsers(dest="command", required=True)

    up = sub.add_parser("upload", help="Uploader une vidéo")
    up.add_argument("--config", type=str, help="Fichier de configuration YAML/JSON")

    # Arguments explicites si pas de config
    up.add_argument("--video", type=str, help="Chemin de la vidéo")
    up.add_argument("--title", type=str, help="Titre de la vidéo")
    up.add_argument("--description", type=str, default="", help="Description")
    up.add_argument(
        "--tags",
        nargs="*",
        default=None,
        help="Tags (séparés par des espaces)",
    )
    up.add_argument(
        "--category-id", type=str, default="22", help="ID catégorie (par défaut 22)"
    )
    up.add_argument(
        "--privacy",
        type=str,
        default="private",
        choices=["private", "public", "unlisted"],
        help="Statut de confidentialité",
    )
    up.add_argument(
        "--publish-at",
        type=str,
        default=None,
        help="Date/heure de publication (RFC3339 UTC, ex: 2025-08-31T12:00:00Z)",
    )
    up.add_argument(
        "--thumbnail", type=str, default=None, help="Chemin de la miniature (optionnel)"
    )
    up.add_argument(
        "--made-for-kids",
        type=str,
        default=None,
        choices=["true", "false"],
        help="Contenu pour enfants",
    )

    # OAuth options
    # Ne pas importer src.auth ici: utiliser des valeurs par défaut littérales
    up.add_argument(
        "--client-secrets",
        type=str,
        default="config/client_secret.json",
        help="Chemin client_secret.json",
    )
    up.add_argument(
        "--token-file", type=str, default="config/token.json", help="Chemin token.json"
    )
    up.add_argument(
        "--headless",
        action="store_true",
        help="Flux OAuth en console (sans navigateur)",
    )

    # Logging
    up.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Niveau de logs",
    )

    # Pré-amélioration (ffmpeg) avant upload
    up.add_argument(
        "--pre-enhance",
        action="store_true",
        help="Améliorer la vidéo via ffmpeg avant l'upload (ou via config.enhance.enabled)",
    )
    up.add_argument(
        "--enhance-quality",
        type=str,
        default=None,
        choices=["low", "medium", "high", "youtube", "max"],
        help="Préréglage qualité pour l'étape d'amélioration",
    )
    up.add_argument(
        "--enhance-scale",
        type=str,
        default=None,
        help="Scale: 720p|1080p|1440p|2160p|WIDTHxHEIGHT|1.5x|2x",
    )
    up.add_argument(
        "--enhance-fps", type=float, default=None, help="Forcer la cadence (ex: 30)"
    )
    up.add_argument(
        "--enhance-denoise", action="store_true", help="Réduction de bruit (hqdn3d)"
    )
    up.add_argument(
        "--enhance-sharpen", action="store_true", help="Renforcer la netteté (unsharp)"
    )
    up.add_argument(
        "--enhance-deinterlace", action="store_true", help="Désentrelacer (yadif)"
    )
    up.add_argument(
        "--enhance-color-fix",
        action="store_true",
        help="Ajustement léger contraste/saturation",
    )
    up.add_argument(
        "--enhance-loudnorm",
        action="store_true",
        help="Normalisation loudness EBU R128",
    )
    up.add_argument(
        "--enhance-deband", action="store_true", help="Réduire le banding (deband)"
    )
    up.add_argument(
        "--enhance-deblock", action="store_true", help="Réduire les blocs (deblock)"
    )
    up.add_argument(
        "--enhance-sharpen-amount",
        type=float,
        default=None,
        help="Intensité de netteté (0.0-1.0)",
    )
    up.add_argument(
        "--enhance-contrast", type=float, default=None, help="Contraste (ex: 1.07)"
    )
    up.add_argument(
        "--enhance-saturation", type=float, default=None, help="Saturation (ex: 1.12)"
    )
    up.add_argument(
        "--enhance-hwaccel",
        type=str,
        default=None,
        choices=["none", "auto", "videotoolbox"],
        help="Accélération matérielle (macOS: videotoolbox)",
    )
    up.add_argument(
        "--enhance-crf",
        type=int,
        default=None,
        help="Qualité x264 (0-51, par défaut 18 si --bitrate non défini)",
    )
    up.add_argument(
        "--enhance-bitrate",
        type=str,
        default=None,
        help="Bitrate vidéo cible (ex: 6M). Si défini, ignore CRF",
    )
    up.add_argument(
        "--enhance-preset",
        type=str,
        default=None,
        choices=[
            "ultrafast",
            "superfast",
            "veryfast",
            "faster",
            "fast",
            "medium",
            "slow",
            "slower",
            "veryslow",
        ],
        help="Préréglage x264 (par défaut selon preset, sinon medium)",
    )
    up.add_argument(
        "--enhance-codec",
        type=str,
        default=None,
        choices=["h264", "hevc", "vp9", "av1"],
        help="Codec vidéo cible",
    )
    up.add_argument(
        "--enhance-reencode-audio", action="store_true", help="Réencoder l'audio en AAC"
    )
    up.add_argument(
        "--enhance-audio-bitrate",
        type=str,
        default=None,
        help="Bitrate audio si réencodage (par défaut 192k)",
    )
    up.add_argument(
        "--enhance-output",
        type=str,
        default=None,
        help="Fichier de sortie pour la vidéo améliorée (par défaut <video>.enhanced.mp4)",
    )

    # AI metadata generation
    ai = sub.add_parser(
        "ai-meta", help="Générer des métadonnées SEO (IA: Ollama/OpenAI)"
    )
    ai.add_argument("--topic", type=str, required=True, help="Sujet/Thème de la vidéo")
    ai.add_argument("--language", type=str, default="fr", help="Langue (fr/en/...)")
    ai.add_argument(
        "--tone",
        type=str,
        default="informatif",
        help="Ton éditorial (ex: informatif, divertissant)",
    )
    ai.add_argument(
        "--target-keywords", nargs="*", default=None, help="Mots-clés cibles"
    )
    ai.add_argument(
        "--channel-style", type=str, default=None, help="Style de la chaîne (optionnel)"
    )
    ai.add_argument(
        "--no-hashtags",
        dest="include_hashtags",
        action="store_false",
        help="Ne pas inclure de hashtags",
    )
    ai.set_defaults(include_hashtags=True)
    ai.add_argument("--max-tags", type=int, default=15, help="Nombre max de tags")
    ai.add_argument(
        "--max-title-chars", type=int, default=70, help="Longueur max du titre"
    )
    ai.add_argument(
        "--provider",
        type=str,
        choices=["ollama", "openai", "none"],
        default=None,
        help="Fournisseur IA (par défaut: valeur de config)",
    )
    ai.add_argument(
        "--model",
        type=str,
        default=None,
        help="Modèle IA (ex: gpt-4o-mini ou llama3.2:3b). Par défaut: valeur de config",
    )
    ai.add_argument(
        "--input-text",
        type=str,
        default=None,
        help="Contexte facultatif (script/transcript)",
    )
    ai.add_argument(
        "--out-config",
        type=str,
        default=None,
        help="Écrire les métadonnées dans ce YAML",
    )
    ai.add_argument(
        "--video-path",
        type=str,
        default=None,
        help="Définir aussi video_path dans le YAML",
    )
    ai.add_argument(
        "--print", action="store_true", help="Afficher les métadonnées générées"
    )
    ai.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Niveau de logs",
    )

    # yt-dlp ingestion
    ing = sub.add_parser("ingest", help="Télécharger une source vidéo (yt-dlp)")
    ing.add_argument("url", type=str, help="URL de la vidéo/source")
    ing.add_argument(
        "--output-dir", type=str, default="downloads", help="Dossier de sortie"
    )
    ing.add_argument(
        "--filename", type=str, default=None, help="Nom de fichier (sans extension)"
    )
    ing.add_argument(
        "--ext", type=str, default="mp4", help="Extension de sortie (mp4, mkv,...)"
    )
    ing.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Niveau de logs",
    )

    # video enhancement (ffmpeg)
    enh = sub.add_parser(
        "enhance", help="Améliorer la qualité (upscale, denoise, sharpen, etc.)"
    )
    enh.add_argument("--input", type=str, required=True, help="Fichier vidéo d'entrée")
    enh.add_argument(
        "--output",
        type=str,
        required=True,
        help="Fichier de sortie (ex: outputs/enhanced.mp4)",
    )
    enh.add_argument(
        "--quality",
        type=str,
        default=None,
        choices=["low", "medium", "high", "youtube", "max"],
        help="Préréglage global (valeurs par défaut surchargées par les autres options)",
    )
    enh.add_argument(
        "--scale",
        type=str,
        default=None,
        help="Cible d'upscale: 720p|1080p|1440p|2160p|WIDTHxHEIGHT|1.5x|2x",
    )
    enh.add_argument(
        "--fps", type=float, default=None, help="Forcer la cadence (ex: 30)"
    )
    enh.add_argument(
        "--denoise", action="store_true", help="Réduction de bruit (hqdn3d)"
    )
    enh.add_argument(
        "--sharpen", action="store_true", help="Renforcer la netteté (unsharp)"
    )
    enh.add_argument("--deinterlace", action="store_true", help="Désentrelacer (yadif)")
    enh.add_argument(
        "--color-fix", action="store_true", help="Léger ajustement contraste/saturation"
    )
    enh.add_argument(
        "--loudnorm", action="store_true", help="Normalisation loudness EBU R128"
    )
    enh.add_argument(
        "--deband", action="store_true", help="Réduire le banding (deband)"
    )
    enh.add_argument(
        "--deblock", action="store_true", help="Réduire les blocs (deblock)"
    )
    enh.add_argument(
        "--sharpen-amount",
        type=float,
        default=None,
        help="Intensité de netteté (0.0-1.0)",
    )
    enh.add_argument(
        "--contrast", type=float, default=None, help="Contraste (ex: 1.07)"
    )
    enh.add_argument(
        "--saturation", type=float, default=None, help="Saturation (ex: 1.12)"
    )
    enh.add_argument(
        "--hwaccel",
        type=str,
        default=None,
        choices=["none", "auto", "videotoolbox"],
        help="Accélération matérielle (macOS: videotoolbox)",
    )
    enh.add_argument(
        "--codec",
        type=str,
        default="h264",
        choices=["h264", "hevc", "vp9", "av1"],
        help="Codec vidéo (par défaut h264)",
    )
    enh.add_argument(
        "--crf",
        type=int,
        default=None,
        help="Qualité x264 (0-51, plus bas = meilleure qualité). Par défaut selon preset (18 si non précisé)",
    )
    enh.add_argument(
        "--bitrate",
        type=str,
        default=None,
        help="Bitrate vidéo cible (ex: 6M). Si défini, ignore CRF",
    )
    enh.add_argument(
        "--preset",
        type=str,
        default=None,
        choices=[
            "ultrafast",
            "superfast",
            "veryfast",
            "faster",
            "fast",
            "medium",
            "slow",
            "slower",
            "veryslow",
        ],
        help="Préréglage x264 (par défaut selon preset, sinon medium)",
    )
    enh.add_argument(
        "--reencode-audio", action="store_true", help="Réencoder l'audio en AAC"
    )
    enh.add_argument(
        "--audio-bitrate",
        type=str,
        default=None,
        help="Bitrate audio si réencodage (par défaut 192k)",
    )
    enh.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Niveau de logs",
    )

    # Telegram bot
    tgb = sub.add_parser(
        "telegram-bot", help="Lancer le bot Telegram pour ingérer des vidéos"
    )
    tgb.add_argument(
        "--sources",
        type=str,
        default="config/sources.yaml",
        help="Fichier de configuration des sources (YAML)",
    )
    tgb.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Niveau de logs",
    )

    # Worker (queue processor)
    wk = sub.add_parser(
        "worker", help="Traiter la file de tâches: enhance -> ai_meta -> upload"
    )
    wk.add_argument(
        "--queue-dir",
        type=str,
        default="queue",
        help="Dossier de la file (tâches JSON)",
    )
    wk.add_argument(
        "--archive-dir",
        type=str,
        default="queue_archive",
        help="Dossier d'archivage des tâches traitées",
    )
    wk.add_argument(
        "--config",
        type=str,
        default=None,
        help="Config vidéo (YAML) pour presets et métadonnées basiques",
    )
    wk.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Niveau de logs",
    )

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    if args.command == "upload":
        if args.config:
            try:
                cfg = load_config(args.config)
            except ConfigError as e:
                logging.error("%s", e)
                return 2
            video_path = cfg["video_path"]
            title = cfg["title"]
            description = cfg.get("description", "")
            tags = cfg.get("tags")
            category_id = cfg.get("category_id", 22)
            privacy_status = cfg.get("privacy_status", "private")
            publish_at = cfg.get("publish_at")
            thumbnail_path = cfg.get("thumbnail_path")
            made_for_kids = cfg.get("made_for_kids")
            enhance_cfg = cfg.get("enhance")
        else:
            if not args.video or not args.title:
                parser.error("--video et --title sont requis sans --config")
            video_path = args.video
            title = args.title
            description = args.description or ""
            tags = args.tags
            category_id = args.category_id
            privacy_status = args.privacy
            publish_at = args.publish_at
            thumbnail_path = args.thumbnail
            made_for_kids = (
                None if args.made_for_kids is None else (args.made_for_kids == "true")
            )
            enhance_cfg = None

        # Étape optionnelle d'amélioration avant upload
        pre_enhance = bool(args.pre_enhance)
        if not pre_enhance and enhance_cfg and isinstance(enhance_cfg, dict):
            pre_enhance = bool(enhance_cfg.get("enabled", False))

        if pre_enhance:
            # Fusion presets (quality) + config + CLI overrides
            def pick(cli_val, cfg_key, default=None):
                if cli_val is not None:
                    return cli_val
                if enhance_cfg and cfg_key in enhance_cfg:
                    return enhance_cfg.get(cfg_key)
                return default

            qname_cfg = (
                (enhance_cfg or {}).get("quality")
                if isinstance(enhance_cfg, dict)
                else None
            )
            qname = args.enhance_quality or qname_cfg
            base = _quality_defaults(qname)

            scale = pick(args.enhance_scale, "scale", base.get("scale"))
            fps = pick(args.enhance_fps, "fps", base.get("fps"))

            # Booleens: True si CLI, sinon valeur config si présente, sinon valeur du preset, sinon False
            def pbool(cli_flag: bool, key: str) -> bool:
                if cli_flag:
                    return True
                if enhance_cfg is not None and key in enhance_cfg:
                    return bool(enhance_cfg.get(key))
                return bool(base.get(key, False))

            denoise = pbool(bool(args.enhance_denoise), "denoise")
            sharpen = pbool(bool(args.enhance_sharpen), "sharpen")
            deinterlace = pbool(bool(args.enhance_deinterlace), "deinterlace")
            color_fix = pbool(bool(args.enhance_color_fix), "color_fix")
            loudnorm = pbool(bool(args.enhance_loudnorm), "loudnorm")
            deband = pbool(bool(args.enhance_deband), "deband")
            deblock = pbool(bool(args.enhance_deblock), "deblock")
            crf = pick(args.enhance_crf, "crf", base.get("crf"))
            bitrate = pick(args.enhance_bitrate, "bitrate", base.get("bitrate"))
            preset = pick(args.enhance_preset, "preset", base.get("preset", "medium"))
            hwaccel = pick(args.enhance_hwaccel, "hwaccel", base.get("hwaccel"))
            # Résolution de 'auto' -> videotoolbox sur macOS, sinon none
            if hwaccel == "auto":
                hwaccel = "videotoolbox" if sys.platform == "darwin" else "none"
            codec = pick(args.enhance_codec, "codec", base.get("codec", "h264"))
            reencode_audio = pbool(bool(args.enhance_reencode_audio), "reencode_audio")
            audio_bitrate = pick(
                args.enhance_audio_bitrate,
                "audio_bitrate",
                base.get("audio_bitrate", "192k"),
            )
            sharpen_amount = pick(
                args.enhance_sharpen_amount,
                "sharpen_amount",
                base.get("sharpen_amount"),
            )
            contrast = pick(args.enhance_contrast, "contrast", base.get("contrast"))
            saturation = pick(
                args.enhance_saturation, "saturation", base.get("saturation")
            )

            vd_path = Path(video_path)
            if args.enhance_output:
                out_path = Path(args.enhance_output)
            else:
                out_path = vd_path.with_name(vd_path.stem + ".enhanced.mp4")
            # Importer paresseusement pour éviter dépendances quand non utilisé
            # Permettre override par monkeypatch via alias global
            _enhance_video = globals().get("enhance_video")
            if not callable(_enhance_video):
                from src.video_enhance import enhance_video as _impl, EnhanceError

                _enhance_video = _impl
            else:
                # Define EnhanceError placeholder if tests patch only function
                class EnhanceError(Exception):
                    pass

            try:
                enhanced = _enhance_video(
                    input_path=vd_path,
                    output_path=out_path,
                    codec=codec,
                    hwaccel=hwaccel or "none",
                    scale=scale,
                    fps=fps,
                    denoise=denoise,
                    sharpen=sharpen,
                    deinterlace=deinterlace,
                    color_fix=color_fix,
                    loudnorm=loudnorm,
                    deband=deband,
                    deblock=deblock,
                    sharpen_amount=sharpen_amount,
                    contrast=contrast,
                    saturation=saturation,
                    crf=crf if crf is not None else 18,
                    bitrate=bitrate,
                    preset=preset,
                    reencode_audio=reencode_audio,
                    audio_bitrate=audio_bitrate,
                )
                video_path = str(enhanced)
                logging.info("Vidéo améliorée: %s", video_path)
            except EnhanceError as e:
                logging.error("Amélioration échouée: %s", e)
                return 2

        # Importer paresseusement auth/uploader pour éviter dépendances quand non utilisé
        _get_credentials = globals().get("get_credentials")
        if not callable(_get_credentials):
            from src.auth import get_credentials as _impl

            _get_credentials = _impl
        _upload_video = globals().get("upload_video")
        if not callable(_upload_video):
            from src.uploader import upload_video as _uimpl

            _upload_video = _uimpl

        creds = _get_credentials(
            SCOPES,
            client_secrets_path=args.client_secrets,
            token_path=args.token_file,
            headless=args.headless,
        )

        resp = _upload_video(
            creds,
            video_path=video_path,
            title=title,
            description=description,
            tags=tags,
            category_id=category_id,
            privacy_status=privacy_status,
            publish_at=publish_at,
            thumbnail_path=thumbnail_path,
            made_for_kids=made_for_kids,
        )
        vid = resp.get("id")
        print(f"Video ID: {vid}")
    elif args.command == "ai-meta":
        kw = args.target_keywords if args.target_keywords else None
        req = MetaRequest(
            topic=args.topic,
            language=args.language,
            tone=args.tone,
            target_keywords=kw,
            channel_style=args.channel_style,
            include_hashtags=args.include_hashtags,
            max_tags=args.max_tags,
            max_title_chars=args.max_title_chars,
            provider=args.provider,
            model=args.model,
            input_text=args.input_text,
        )
        # Utiliser le même fichier de config que --out-config si fourni, sinon défaut
        cfg_path = args.out_config if args.out_config else "config/video.yaml"
        data = generate_metadata(req, config_path=cfg_path, video_path=args.video_path)
        if args.print or not args.out_config:
            # Affiche un aperçu simple
            print("Title:\n" + data.get("title", ""))
            print("\nDescription:\n" + data.get("description", ""))
            print("\nTags:", ", ".join(data.get("tags", [])))
            if data.get("hashtags"):
                print("Hashtags:", " ".join(data.get("hashtags", [])))
        if args.out_config:
            write_metadata_to_config(
                args.out_config,
                video_path=args.video_path,
                title=data.get("title", ""),
                description=data.get("description", ""),
                tags=data.get("tags", []),
            )
            print(f"Métadonnées écrites dans {args.out_config}")
    elif args.command == "ingest":
        # Lazy import ingest (allow alias override)
        _download_source = globals().get("download_source")
        if not callable(_download_source):
            from src.ingest import download_source as _impl

            _download_source = _impl
        path = _download_source(
            args.url,
            output_dir=args.output_dir,
            filename=args.filename,
            prefer_ext=args.ext,
        )
        print(str(path))
    elif args.command == "enhance":
        # Lazy import enhance to avoid importing at module import time (allow alias override)
        _enhance_video2 = globals().get("enhance_video")
        if not callable(_enhance_video2):
            from src.video_enhance import enhance_video as _enh

            _enhance_video2 = _enh
        base = _quality_defaults(getattr(args, "quality", None))

        def pick2(cli_val, key, default=None):
            if cli_val is not None:
                return cli_val
            return base.get(key, default)

        # Merge presets with CLI
        scale = pick2(args.scale, "scale")
        fps = pick2(args.fps, "fps")
        denoise = args.denoise or bool(base.get("denoise", False))
        sharpen = args.sharpen or bool(base.get("sharpen", False))
        deinterlace = args.deinterlace or bool(base.get("deinterlace", False))
        color_fix = args.color_fix or bool(base.get("color_fix", False))
        loudnorm = args.loudnorm or bool(base.get("loudnorm", False))
        deband = args.deband or bool(base.get("deband", False))
        deblock = args.deblock or bool(base.get("deblock", False))
        crf = pick2(args.crf, "crf")
        bitrate = pick2(args.bitrate, "bitrate")
        preset = pick2(args.preset, "preset", "medium")
        hwaccel = pick2(args.hwaccel, "hwaccel")
        if hwaccel == "auto":
            hwaccel = "videotoolbox" if sys.platform == "darwin" else "none"
        codec = pick2(args.codec, "codec", "h264")
        reencode_audio = args.reencode_audio or bool(base.get("reencode_audio", False))
        audio_bitrate = pick2(args.audio_bitrate, "audio_bitrate", "192k")
        sharpen_amount = pick2(args.sharpen_amount, "sharpen_amount")
        contrast = pick2(args.contrast, "contrast")
        saturation = pick2(args.saturation, "saturation")

        out = _enhance_video2(
            input_path=args.input,
            output_path=args.output,
            codec=codec,
            hwaccel=hwaccel or "none",
            scale=scale,
            fps=fps,
            denoise=denoise,
            sharpen=sharpen,
            deinterlace=deinterlace,
            color_fix=color_fix,
            loudnorm=loudnorm,
            deband=deband,
            deblock=deblock,
            sharpen_amount=sharpen_amount,
            contrast=contrast,
            saturation=saturation,
            crf=crf if crf is not None else 18,
            bitrate=bitrate,
            preset=preset,
            reencode_audio=reencode_audio,
            audio_bitrate=audio_bitrate,
        )
        print(str(out))
    elif args.command == "telegram-bot":
        # Lazy import telegram bot (allow alias override)
        _run_bot = globals().get("run_bot_from_sources")
        if not callable(_run_bot):
            from src.ingest_telegram import run_bot_from_sources as _impl

            _run_bot = _impl
        logging.getLogger("httpx").setLevel(logging.WARNING)
        _run_bot(args.sources)
    elif args.command == "worker":
        # Lazy import worker (allow alias override)
        _process_queue = globals().get("process_queue")
        if not callable(_process_queue):
            from src.worker import process_queue as _impl

            _process_queue = _impl
        _process_queue(
            queue_dir=args.queue_dir,
            archive_dir=args.archive_dir,
            config_path=args.config,
            log_level=args.log_level,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
