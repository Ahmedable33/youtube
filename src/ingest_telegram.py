from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, CallbackQueryHandler, filters
from src.ai_generator import MetaRequest, generate_metadata


log = logging.getLogger("ingest_telegram")


@dataclass
class TelegramConfig:
    token: str
    allowed_chat_ids: list[int]
    download_dir: Path
    queue_dir: Path
    filename_pattern: str = "{unix}_{chat}_{orig}"

    @staticmethod
    def from_dict(d: dict) -> "TelegramConfig":
        token = d.get("token")
        if not token:
            raise ValueError("sources.telegram.token manquant dans le YAML")
        allowed = d.get("allowed_chat_ids") or []
        if not isinstance(allowed, list):
            raise ValueError("sources.telegram.allowed_chat_ids doit être une liste")
        dl = Path(d.get("download_dir") or "inputs/telegram").resolve()
        q = Path(d.get("queue_dir") or "queue").resolve()
        patt = d.get("filename_pattern") or "{unix}_{chat}_{orig}"
        return TelegramConfig(token=token, allowed_chat_ids=[int(x) for x in allowed], download_dir=dl, queue_dir=q, filename_pattern=patt)


def _safe_filename(name: str) -> str:
    # remplace les séparateurs et caractères spéciaux
    base = name.replace("/", "_").replace("\\", "_")
    base = "".join(c for c in base if 31 < ord(c) < 127)
    return base[:200] if len(base) > 200 else base


def _reply_menu_keyboard() -> ReplyKeyboardMarkup:
    # Clavier persistant (s'affiche en bas, ne dépend pas du message)
    rows = [
        ["Status", "Preview SEO", "Redo"],
        ["Quality: low", "Quality: medium", "Quality: high"],
        ["Quality: youtube", "Quality: max", "Chapters help"],
        ["Privacy: Private", "Privacy: Public", "Privacy: Unlisted"],
        ["Category: Gaming", "Category: Education", "Category: Entertainment"],
        ["Subtitles: ON", "Subtitles: OFF"],
        ["Schedule: Auto", "Schedule: Now", "Upload maintenant"],
        ["Cancel"],
    ]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=False)


async def _start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Bot actif. Envoyez une vidéo pour l'ingérer.",
        reply_markup=_reply_menu_keyboard(),
    )


async def _help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Commandes:\n"
        "/start - Démarrer\n"
        "/help - Aide\n"
        "/title <texte> - Définir le titre SEO pour la dernière tâche\n"
        "/desc <texte> - Définir la description pour la dernière tâche\n"
        "/tags <liste> - Définir les tags (séparés par virgule ou #hashtags) pour la dernière tâche\n"
        "Envoyez simplement une vidéo (avec une légende facultative): la vidéo sera traitée."
    )


def _last_task_pointer_path(queue_dir: Path, chat_id: int) -> Path:
    return queue_dir / f"last_task_{chat_id}.json"


def _set_last_task(queue_dir: Path, chat_id: int, task_path: Path) -> None:
    p = _last_task_pointer_path(queue_dir, chat_id)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"task_path": str(task_path)}, f)


def _get_last_task(queue_dir: Path, chat_id: int) -> Optional[Path]:
    p = _last_task_pointer_path(queue_dir, chat_id)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        t = Path(data.get("task_path", ""))
        return t if t.exists() else None
    except Exception:
        return None


def _extract_hashtags(text: str) -> list[str]:
    tags: list[str] = []
    word = ""
    i = 0
    while i < len(text):
        c = text[i]
        if c == "#":
            j = i + 1
            word = ""
            while j < len(text) and (text[j].isalnum() or text[j] in ("_", "-")):
                word += text[j]
                j += 1
            if word:
                tags.append(word.lower())
            i = j
        else:
            i += 1
    return tags


def _prefs_path(queue_dir: Path, chat_id: int) -> Path:
    return queue_dir / f"prefs_{chat_id}.json"


def _load_prefs(queue_dir: Path, chat_id: int) -> dict:
    p = _prefs_path(queue_dir, chat_id)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}
    return {}


def _save_prefs(queue_dir: Path, chat_id: int, prefs: dict) -> None:
    p = _prefs_path(queue_dir, chat_id)
    p.write_text(json.dumps(prefs or {}, ensure_ascii=False, indent=2), encoding="utf-8")


async def _handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE, cfg: TelegramConfig) -> None:
    msg = update.message
    if not msg:
        return
    chat_id = msg.chat_id
    if cfg.allowed_chat_ids and chat_id not in cfg.allowed_chat_ids:
        log.warning("Chat %s non autorisé", chat_id)
        return

    vid = None
    orig_name = None
    if msg.video:
        vid = msg.video
        orig_name = getattr(vid, "file_name", None) or "video.mp4"
    elif msg.document and msg.document.mime_type and msg.document.mime_type.startswith("video/"):
        vid = msg.document
        orig_name = msg.document.file_name or "video.bin"
    else:
        return

    file = await context.bot.get_file(vid.file_id)

    ts = int(datetime.utcnow().timestamp())
    # Séparer nom et extension pour éviter les doublons .mp4.mp4
    if "." in orig_name:
        orig_stem, orig_ext = orig_name.rsplit(".", 1)
        ext = orig_ext
    else:
        orig_stem = orig_name
        ext = "mp4"

    base = cfg.filename_pattern.format(unix=ts, chat=chat_id, orig=_safe_filename(orig_stem))

    cfg.download_dir.mkdir(parents=True, exist_ok=True)
    cfg.queue_dir.mkdir(parents=True, exist_ok=True)

    out_path = cfg.download_dir / f"{base}.{ext}"
    await file.download_to_drive(str(out_path))
    log.info("Vidéo téléchargée: %s", out_path)

    # Créer tâche dans la queue
    caption = (msg.caption or "").strip()
    initial_tags = _extract_hashtags(caption) if caption else []
    # Préférences par chat (ex: quality)
    prefs = _load_prefs(cfg.queue_dir, chat_id)
    task = {
        "source": "telegram",
        "chat_id": chat_id,
        "received_at": datetime.utcnow().isoformat() + "Z",
        "video_path": str(out_path),
        "status": "pending",
        "steps": ["enhance", "ai_meta", "upload"],
        "prefs": prefs,
        # Champs optionnels SEO par défaut (peuvent être enrichis)
        "meta": {
            "language": "fr",
            "tone": "informatif",
            "title": None,
            "description": caption or None,
            "tags": initial_tags,
        },
    }
    task_path = cfg.queue_dir / f"task_{ts}_{chat_id}.json"
    with open(task_path, "w", encoding="utf-8") as f:
        json.dump(task, f, ensure_ascii=False, indent=2)
    _set_last_task(cfg.queue_dir, chat_id, task_path)
    await msg.reply_text(
        "✅ Reçu. Vidéo sauvegardée et tâche créée.",
        reply_markup=_reply_menu_keyboard(),
    )


async def _video_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, cfg: TelegramConfig) -> None:
    try:
        await _handle_video(update, context, cfg)
    except Exception as e:
        log.exception("Erreur lors du traitement de la vidéo: %s", e)
        if update.message:
            await update.message.reply_text("❌ Erreur lors du traitement de la vidéo (peut-être un timeout réseau). Réessayez ou envoyez un fichier plus petit.")


def load_sources_yaml(path: str | Path) -> dict:
    import yaml
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _main_menu_keyboard() -> InlineKeyboardMarkup:
    multi_accounts_enabled = False
    try:
        from .config_loader import load_config
        config = load_config("config/video.yaml")
        multi_accounts_enabled = config.get("multi_accounts", {}).get("enabled", False)
    except:
        pass

    # Boutons persistants
    keyboard = [
        [
            InlineKeyboardButton("📊 Status", callback_data="status"),
            InlineKeyboardButton("👁️ Preview SEO", callback_data="preview"),
            InlineKeyboardButton("🔄 Redo", callback_data="redo"),
        ],
        [
            InlineKeyboardButton("🎥 Quality: " + current_quality.title(), callback_data="quality"),
            InlineKeyboardButton("📝 Chapters help", callback_data="chapters_help"),
        ],
        [
            InlineKeyboardButton("🔒 Privacy: " + current_privacy.title(), callback_data="privacy"),
            InlineKeyboardButton("📂 Category: " + category_name, callback_data="category"),
        ],
        [
            InlineKeyboardButton("📺 Subtitles: " + ("ON" if subtitles_enabled else "OFF"), callback_data="subtitles"),
            InlineKeyboardButton("⏰ Schedule: " + schedule_mode.title(), callback_data="schedule"),
        ]
    ]
    
    # Ajouter le bouton compte si multi-comptes activé
    if multi_accounts_enabled:
        keyboard.append([
            InlineKeyboardButton("👤 Account", callback_data="account"),
        ])
    
    # Boutons d'action finaux
    keyboard.append([
        InlineKeyboardButton("🚀 Upload", callback_data="upload"),
        InlineKeyboardButton("❌ Cancel", callback_data="cancel"),
    ])
    return InlineKeyboardMarkup(keyboard)


def _account_menu_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    """Créer le menu de sélection de compte"""
    keyboard = []
    
    try:
        from .config_loader import load_config
        config = load_config("config/video.yaml")
        
        if not config.get("multi_accounts", {}).get("enabled", False):
            keyboard.append([InlineKeyboardButton("❌ Multi-comptes désactivé", callback_data="back_main")])
        else:
            from .multi_account_manager import create_multi_account_manager
            manager = create_multi_account_manager()
            
            # Obtenir le compte actuel
            current_account = manager.get_chat_account(str(chat_id))
            current_id = current_account.account_id if current_account else None
            
            # Ajouter les comptes disponibles
            for account in manager.accounts.values():
                if account.enabled:
                    status = manager.get_account_status(account.account_id)
                    
                    # Indicateur de sélection et statut
                    prefix = "✅ " if account.account_id == current_id else "📺 "
                    uploads_info = f"({status['uploads_used']}/{status['uploads_limit']})"
                    
                    button_text = f"{prefix}{account.name} {uploads_info}"
                    keyboard.append([InlineKeyboardButton(button_text, callback_data=f"account:{account.account_id}")])
            
            if not keyboard:
                keyboard.append([InlineKeyboardButton("❌ Aucun compte disponible", callback_data="back_main")])
    
    except Exception as e:
        keyboard.append([InlineKeyboardButton(f"❌ Erreur: {str(e)[:30]}...", callback_data="back_main")])
    
    # Bouton retour
    keyboard.append([InlineKeyboardButton("🔙 Retour", callback_data="back_main")])
    
    return InlineKeyboardMarkup(keyboard)


def _quality_menu_keyboard() -> InlineKeyboardMarkup:
    row1 = [
        InlineKeyboardButton("low", callback_data="setq:low"),
        InlineKeyboardButton("medium", callback_data="setq:medium"),
        InlineKeyboardButton("high", callback_data="setq:high"),
    ]
    row2 = [
        InlineKeyboardButton("youtube", callback_data="setq:youtube"),
        InlineKeyboardButton("max", callback_data="setq:max"),
        InlineKeyboardButton("⬅️ Retour", callback_data="action:back_main"),
    ]
    return InlineKeyboardMarkup([row1, row2])


def build_application(cfg: TelegramConfig) -> Application:
    # Configurer des timeouts HTTPx plus généreux pour les téléchargements de fichiers
    try:
        from telegram.request import HTTPXRequest
        req = HTTPXRequest(
            connect_timeout=30.0,
            read_timeout=120.0,
            write_timeout=120.0,
            pool_timeout=30.0,
        )
        app = Application.builder().token(cfg.token).request(req).build()
    except Exception:
        app = Application.builder().token(cfg.token).build()
    app.add_handler(CommandHandler("start", _start))
    app.add_handler(CommandHandler("help", _help))
    # Video or document video
    app.add_handler(MessageHandler(filters.VIDEO | (filters.Document.VIDEO), lambda u, c: _video_handler(u, c, cfg)))
    # ReplyKeyboard text actions
    async def _on_text_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.message
        if not msg or not msg.text:
            return
        txt = msg.text.strip()
        if txt == "Status":
            await _cmd_status(update, context)
            return
        if txt == "Preview SEO":
            await _cmd_preview(update, context)
            return
        if txt == "Redo":
            await _cmd_redo(update, context)
            return
        if txt == "Cancel":
            await _cmd_cancel(update, context)
            return
        if txt.lower().startswith("chapters help"):
            await msg.reply_text(
                "Envoyez /chapters suivi de vos lignes de chapitres, une par ligne, au format:\n"
                "00:00 Intro\n00:45 Sujet 1\n01:30 Sujet 2\n\nExemple:\n/chapters\n00:00 Introduction\n00:30 Démo\n02:10 Astuces"
            )
            return
        if txt.lower().startswith("quality:"):
            preset = txt.split(":", 1)[1].strip().lower()
            if preset in ("low", "medium", "high", "youtube", "max"):
                chat_id = msg.chat_id
                prefs = _load_prefs(cfg.queue_dir, chat_id)
                prefs["quality"] = preset
                _save_prefs(cfg.queue_dir, chat_id, prefs)
                taskp = _get_last_task(cfg.queue_dir, chat_id)
                if taskp:
                    try:
                        data = json.loads(taskp.read_text(encoding="utf-8"))
                        if data.get("status") == "pending":
                            data.setdefault("prefs", {})["quality"] = preset
                            taskp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                    except Exception:
                        pass
                await msg.reply_text(f"✅ Qualité définie sur '{preset}' pour ce chat.")
            else:
                await msg.reply_text("Qualité invalide. Utilisez: low, medium, high, youtube, max")
        if txt.lower().startswith("privacy:"):
            privacy = txt.split(":", 1)[1].strip().lower()
            if privacy in ("private", "public", "unlisted"):
                chat_id = msg.chat_id
                prefs = _load_prefs(cfg.queue_dir, chat_id)
                prefs["privacy_status"] = privacy
                _save_prefs(cfg.queue_dir, chat_id, prefs)
                taskp = _get_last_task(cfg.queue_dir, chat_id)
                if taskp:
                    try:
                        data = json.loads(taskp.read_text(encoding="utf-8"))
                        if data.get("status") == "pending":
                            data["privacy_status"] = privacy
                            taskp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                    except Exception:
                        pass
                await msg.reply_text(f"✅ Visibilité définie sur '{privacy}' pour ce chat.")
            else:
                await msg.reply_text("Visibilité invalide. Utilisez: private, public, unlisted")
        if txt.lower().startswith("category:"):
            category_name = txt.split(":", 1)[1].strip().lower()
            # Mapping des catégories YouTube courantes
            category_map = {
                "gaming": 20,
                "education": 27,
                "entertainment": 24,
                "music": 10,
                "tech": 28,
                "science": 28,
                "news": 25,
                "sports": 17,
                "comedy": 23,
                "howto": 26,
                "people": 22,
                "blogs": 22
            }
            if category_name in category_map:
                category_id = category_map[category_name]
                chat_id = msg.chat_id
                prefs = _load_prefs(cfg.queue_dir, chat_id)
                prefs["category_id"] = category_id
                _save_prefs(cfg.queue_dir, chat_id, prefs)
                taskp = _get_last_task(cfg.queue_dir, chat_id)
                if taskp:
                    try:
                        data = json.loads(taskp.read_text(encoding="utf-8"))
                        if data.get("status") == "pending":
                            data["category_id"] = category_id
                            taskp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                    except Exception:
                        pass
                await msg.reply_text(f"✅ Catégorie définie sur '{category_name}' (ID: {category_id}) pour ce chat.")
            else:
                await msg.reply_text("Catégorie invalide. Utilisez: gaming, education, entertainment, music, tech, news, sports, comedy, howto, people")
        if txt.lower().startswith("subtitles:"):
            setting = txt.split(":", 1)[1].strip().lower()
            if setting in ("on", "off"):
                enabled = setting == "on"
                chat_id = msg.chat_id
                prefs = _load_prefs(cfg.queue_dir, chat_id)
                prefs["subtitles_enabled"] = enabled
                _save_prefs(cfg.queue_dir, chat_id, prefs)
                taskp = _get_last_task(cfg.queue_dir, chat_id)
                if taskp:
                    try:
                        data = json.loads(taskp.read_text(encoding="utf-8"))
                        if data.get("status") == "pending":
                            data["subtitles_enabled"] = enabled
                            taskp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                    except Exception:
                        pass
                status = "activés" if enabled else "désactivés"
                await msg.reply_text(f"✅ Sous-titres automatiques {status} pour ce chat.")
            else:
                await msg.reply_text("Paramètre invalide. Utilisez: on, off")
        if txt.lower().startswith("schedule:"):
            mode = txt.split(":", 1)[1].strip().lower()
            if mode in ("auto", "now"):
                chat_id = msg.chat_id
                prefs = _load_prefs(cfg.queue_dir, chat_id)
                prefs["schedule_mode"] = mode
                _save_prefs(cfg.queue_dir, chat_id, prefs)
                taskp = _get_last_task(cfg.queue_dir, chat_id)
                if taskp:
                    try:
                        data = json.loads(taskp.read_text(encoding="utf-8"))
                        if data.get("status") == "pending":
                            data["schedule_mode"] = mode
                            taskp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                    except Exception:
                        pass
                mode_text = "automatique (heures optimales)" if mode == "auto" else "immédiat"
                await msg.reply_text(f"✅ Mode de planification: {mode_text}")
            else:
                await msg.reply_text("Mode invalide. Utilisez: auto, now")
        if txt.lower() == "upload maintenant":
            chat_id = msg.chat_id
            taskp = _get_last_task(cfg.queue_dir, chat_id)
            if not taskp:
                await msg.reply_text("Aucune tâche récente trouvée. Envoyez d'abord une vidéo.")
                return
            try:
                data = json.loads(taskp.read_text(encoding="utf-8"))
                if data.get("status") != "pending":
                    await msg.reply_text(f"Tâche non pending (status: {data.get('status')}). Utilisez 'Redo' pour recréer une tâche.")
                    return
                # Marquer pour skip enhancement
                data["skip_enhance"] = True
                taskp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                await msg.reply_text("✅ Upload direct programmé (sans amélioration). La vidéo sera uploadée telle quelle.")
            except Exception as e:
                await msg.reply_text(f"Erreur: {e}")
        if txt.lower() == "cancel":
            chat_id = msg.chat_id
            taskp = _get_last_task(cfg.queue_dir, chat_id)
            if not taskp:
                await msg.reply_text("Aucune tâche récente trouvée.")
                return
            try:
                data = json.loads(taskp.read_text(encoding="utf-8"))
                if data.get("status") != "pending":
                    await msg.reply_text(f"Tâche non pending (status: {data.get('status')}).")
                    return
                data["status"] = "cancelled"
                taskp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                await msg.reply_text("✅ Tâche annulée.")
            except Exception as e:
                await msg.reply_text(f"Erreur: {e}")

    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), _on_text_buttons))
    # Commands to enrich metadata
    async def _cmd_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.message
        if not msg or not msg.text:
            return
        chat_id = msg.chat_id
        taskp = _get_last_task(cfg.queue_dir, chat_id)
        if not taskp:
            await msg.reply_text("Aucune tâche récente trouvée. Envoyez d'abord une vidéo.")
            return
        title = msg.text.split(maxsplit=1)
        if len(title) < 2:
            await msg.reply_text("Usage: /title <texte>")
            return
        data = json.loads(taskp.read_text(encoding="utf-8"))
        data.setdefault("meta", {})["title"] = title[1].strip()
        taskp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        await msg.reply_text("✅ Titre mis à jour.")

    async def _cmd_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.message
        if not msg or not msg.text:
            return
        chat_id = msg.chat_id
        taskp = _get_last_task(cfg.queue_dir, chat_id)
        if not taskp:
            await msg.reply_text("Aucune tâche récente trouvée. Envoyez d'abord une vidéo.")
            return
        parts = msg.text.split(maxsplit=1)
        if len(parts) < 2:
            await msg.reply_text("Usage: /desc <texte>")
            return
        data = json.loads(taskp.read_text(encoding="utf-8"))
        data.setdefault("meta", {})["description"] = parts[1].strip()
        taskp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        await msg.reply_text("✅ Description mise à jour.")

    async def _cmd_tags(update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.message
        if not msg or not msg.text:
            return
        chat_id = msg.chat_id
        taskp = _get_last_task(cfg.queue_dir, chat_id)
        if not taskp:
            await msg.reply_text("Aucune tâche récente trouvée. Envoyez d'abord une vidéo.")
            return
        parts = msg.text.split(maxsplit=1)
        if len(parts) < 2:
            await msg.reply_text("Usage: /tags <tag1, tag2, #tag3>")
            return
        raw = parts[1]
        # collect hashtags and comma-separated
        tags = set(_extract_hashtags(raw))
        for piece in raw.replace("\n", ",").split(","):
            t = piece.strip().lstrip("#")
            if t:
                tags.add(t.lower())
        data = json.loads(taskp.read_text(encoding="utf-8"))
        data.setdefault("meta", {})["tags"] = sorted(tags)
        taskp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        await msg.reply_text("✅ Tags mis à jour.")

    app.add_handler(CommandHandler("title", _cmd_title))
    app.add_handler(CommandHandler("desc", _cmd_desc))
    app.add_handler(CommandHandler("tags", _cmd_tags))

    async def _cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.message
        if not msg:
            return
        chat_id = msg.chat_id
        taskp = _get_last_task(cfg.queue_dir, chat_id)
        if not taskp:
            await msg.reply_text("Aucune tâche récente trouvée. Envoyez d'abord une vidéo.")
            return
        try:
            data = json.loads(taskp.read_text(encoding="utf-8"))
        except Exception:
            await msg.reply_text("Impossible de lire la dernière tâche.")
            return
        meta = data.get("meta") or {}
        title = meta.get("title") or "(non défini)"
        description = meta.get("description") or "(non défini)"
        tags = meta.get("tags") or []
        youtube_id = data.get("youtube_id")
        status = data.get("status") or "pending"
        steps = ", ".join(data.get("steps") or [])
        video_path = data.get("video_path")
        enhanced_path = data.get("enhanced_path")

        preview_desc = (description[:220] + "…") if isinstance(description, str) and len(description) > 220 else description
        tag_str = ", ".join(tags) if isinstance(tags, list) else str(tags)

        lines = [
            f"Statut: {status}",
            f"Étapes: {steps}",
            f"Vidéo: {video_path}",
        ]
        if enhanced_path:
            lines.append(f"Enhancé: {enhanced_path}")
        if youtube_id:
            lines.append(f"YouTube ID: {youtube_id}")
        # Afficher privacy_status
        prefs = _load_prefs(cfg.queue_dir, chat_id)
        current_privacy = data.get("privacy_status") or prefs.get("privacy_status") or "private"
        
        # Afficher category_id
        current_category_id = data.get("category_id") or prefs.get("category_id") or 22
        category_names = {20: "Gaming", 27: "Education", 24: "Entertainment", 10: "Music", 28: "Tech", 25: "News", 17: "Sports", 23: "Comedy", 26: "Howto", 22: "People & Blogs"}
        category_name = category_names.get(current_category_id, f"ID {current_category_id}")
        
        # Afficher sous-titres
        subtitles_enabled = data.get("subtitles_enabled") or prefs.get("subtitles_enabled") or False
        subtitles_status = "activés" if subtitles_enabled else "désactivés"
        
        # Afficher planification
        schedule_mode = data.get("schedule_mode") or prefs.get("schedule_mode") or "now"
        if schedule_mode == "auto":
            schedule_text = "automatique (heures optimales)"
        elif schedule_mode == "custom":
            custom_time = data.get("custom_schedule_time") or prefs.get("custom_schedule_time")
            if custom_time:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(custom_time)
                    schedule_text = f"programmé pour {dt.strftime('%d/%m/%Y à %H:%M')}"
                except:
                    schedule_text = "programmé (heure invalide)"
            else:
                schedule_text = "programmé"
        else:
            schedule_text = "immédiat"
        
        # Afficher SEO avancé si activé
        seo_advanced_enabled = False
        multi_accounts_enabled = False
        current_account = "principal"
        try:
            from .config_loader import load_config
            config = load_config("config/video.yaml")
            seo_advanced_enabled = config.get("seo_advanced", {}).get("enabled", False)
            multi_accounts_enabled = config.get("multi_accounts", {}).get("enabled", False)
            
            # Obtenir le compte actuel pour ce chat
            if multi_accounts_enabled:
                from .multi_account_manager import create_multi_account_manager
                manager = create_multi_account_manager()
                account = manager.get_chat_account(str(chat_id))
                if account:
                    current_account = account.name
        except:
            pass
        
        seo_status = "activé (tendances + concurrence)" if seo_advanced_enabled else "standard"
        account_status = f"{current_account}" + (" (multi-comptes)" if multi_accounts_enabled else "")
        
        lines.extend([
            "\nMétadonnées:",
            f"- Titre: {title}",
            f"- Description: {preview_desc}",
            f"- Tags: {tag_str}",
            f"- Visibilité: {current_privacy}",
            f"- Catégorie: {category_name}",
            f"- Sous-titres: {subtitles_status}",
            f"- Planification: {schedule_text}",
            f"- SEO: {seo_status}",
            f"- Compte: {account_status}",
        ])
        
        # Afficher infos sous-titres si générés
        subtitles_info = data.get("subtitles")
        if subtitles_info:
            generated = subtitles_info.get("generated", [])
            uploaded = subtitles_info.get("uploaded", [])
            source_lang = subtitles_info.get("source_language")
            if generated:
                lines.append(f"- Sous-titres générés: {', '.join(generated)}")
            if uploaded:
                lines.append(f"- Sous-titres uploadés: {', '.join(uploaded)}")
            if source_lang:
                lines.append(f"- Langue détectée: {source_lang}")
        
        # Afficher si tâche bloquée
        if status == "blocked":
            error_msg = data.get("error_message", "Erreur inconnue")
            blocked_at = data.get("blocked_at", "")
            lines.append(f"\n⚠️ BLOQUÉ: {error_msg}")
            if blocked_at:
                lines.append(f"Bloqué le: {blocked_at[:19].replace('T', ' ')}")
        await msg.reply_text("\n".join(lines))

    app.add_handler(CommandHandler("status", _cmd_status))

    async def _cmd_preview(update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.message
        if not msg:
            return
        chat_id = msg.chat_id
        taskp = _get_last_task(cfg.queue_dir, chat_id)
        if not taskp:
            await msg.reply_text("Aucune tâche récente trouvée. Envoyez d'abord une vidéo.")
            return
        try:
            data = json.loads(taskp.read_text(encoding="utf-8"))
        except Exception:
            await msg.reply_text("Impossible de lire la dernière tâche.")
            return
        meta = data.get("meta") or {}
        title = meta.get("title")
        description = meta.get("description") or ""
        tags = list(meta.get("tags") or [])
        # Compléter au besoin via IA en utilisant la description comme input_text
        if not title or not tags:
            try:
                req = MetaRequest(
                    topic=(title or Path(data.get("video_path", "video.mp4")).stem),
                    language=meta.get("language") or "fr",
                    tone=meta.get("tone") or "informatif",
                    include_hashtags=True,
                    max_tags=15,
                    max_title_chars=70,
                    model="gpt-4o-mini",
                    input_text=description or None,
                )
                ai = generate_metadata(req)
                title = title or ai.get("title")
                if not description:
                    description = ai.get("description") or ""
                if not tags:
                    tags = ai.get("tags") or []
            except Exception as e:
                # Si OPENAI_API_KEY absent ou autre erreur, garder ce qu'on a
                pass
        # Normaliser tags
        if tags:
            tags = sorted({str(t).strip().lstrip('#').lower() for t in tags if str(t).strip()})
        preview_desc = (description[:600] + "…") if len(description) > 600 else description
        tag_str = ", ".join(tags)
        await msg.reply_text(
            "Aperçu SEO:\n\n"
            f"Titre:\n{title or '(vide)'}\n\n"
            f"Description (extrait):\n{preview_desc or '(vide)'}\n\n"
            f"Tags:\n{tag_str or '(aucun)'}"
        )

    app.add_handler(CommandHandler("preview", _cmd_preview))

    async def _cmd_chapters(update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.message
        if not msg:
            return
        chat_id = msg.chat_id
        taskp = _get_last_task(cfg.queue_dir, chat_id)
        if not taskp:
            await msg.reply_text("Aucune tâche récente trouvée.")
            return
        # Récupérer le texte après la commande
        raw = msg.text.split("\n", 1)
        chapters_text = raw[1].strip() if len(raw) > 1 else ""
        if not chapters_text:
            await msg.reply_text(
                "Veuillez fournir vos chapitres après la commande, ex:\n"
                "/chapters\n00:00 Intro\n00:45 Sujet 1\n01:30 Sujet 2"
            )
            return
        # Filtrer les lignes avec timestamp
        lines = []
        for line in chapters_text.splitlines():
            l = line.strip()
            if not l:
                continue
            # Valider un timestamp simple mm:ss ou hh:mm:ss au début de ligne
            import re
            if re.match(r"^(\d{1,2}:)?\d{1,2}:\d{2}\s+.+", l) or re.match(r"^\d{1,2}:\d{2}\s+.+", l):
                lines.append(l)
        if not lines:
            await msg.reply_text("Aucun chapitre valide détecté (format mm:ss Titre ou hh:mm:ss Titre).")
            return
        try:
            data = json.loads(taskp.read_text(encoding="utf-8"))
            meta = data.setdefault("meta", {})
            desc = (meta.get("description") or "").rstrip()
            block = "\n\nChapitres:\n" + "\n".join(lines)
            meta["description"] = (desc + block) if desc else ("Chapitres:\n" + "\n".join(lines))
            taskp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            await msg.reply_text("✅ Chapitres insérés dans la description de la dernière tâche.")
        except Exception:
            await msg.reply_text("Erreur lors de l'insertion des chapitres.")

    app.add_handler(CommandHandler("chapters", _cmd_chapters))

    async def _cmd_privacy(update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.message
        if not msg or not msg.text:
            return
        chat_id = msg.chat_id
        parts = msg.text.split()
        if len(parts) < 2:
            await msg.reply_text("Usage: /privacy <private|public|unlisted>")
            return
        privacy = parts[1].lower()
        if privacy not in ("private", "public", "unlisted"):
            await msg.reply_text("Visibilité invalide. Utilisez: private, public, unlisted")
            return
        
        prefs = _load_prefs(cfg.queue_dir, chat_id)
        prefs["privacy_status"] = privacy
        _save_prefs(cfg.queue_dir, chat_id, prefs)
        
        taskp = _get_last_task(cfg.queue_dir, chat_id)
        if taskp:
            try:
                data = json.loads(taskp.read_text(encoding="utf-8"))
                if data.get("status") == "pending":
                    data["privacy_status"] = privacy
                    taskp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass
        await msg.reply_text(f"✅ Visibilité définie sur '{privacy}' pour ce chat.")

    app.add_handler(CommandHandler("privacy", _cmd_privacy))

    async def _cmd_subtitles(update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.message
        if not msg or not msg.text:
            return
        chat_id = msg.chat_id
        parts = msg.text.split()
        if len(parts) < 2:
            await msg.reply_text("Usage: /subtitles <on|off>")
            return
        
        setting = parts[1].lower()
        if setting not in ["on", "off"]:
            await msg.reply_text("Usage: /subtitles <on|off>")
            return
        
        enabled = setting == "on"
        prefs = _load_prefs(cfg.queue_dir, chat_id)
        prefs["subtitles_enabled"] = enabled
        _save_prefs(cfg.queue_dir, chat_id, prefs)
        
        # Mettre à jour la dernière tâche en attente
        taskp = _get_last_task(cfg.queue_dir, chat_id)
        if taskp:
            try:
                data = json.loads(taskp.read_text(encoding="utf-8"))
                if data.get("status") == "pending":
                    data["subtitles_enabled"] = enabled
                    taskp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass
        
        status = "activés" if enabled else "désactivés"
        await msg.reply_text(f"✅ Sous-titres automatiques {status} pour ce chat.")

    app.add_handler(CommandHandler("subtitles", _cmd_subtitles))

    async def _cmd_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.message
        if not msg or not msg.text:
            return
        chat_id = msg.chat_id
        parts = msg.text.split()
        if len(parts) < 2:
            await msg.reply_text("Usage: /schedule <auto|now|YYYY-MM-DD HH:MM>")
            return
        
        schedule_arg = " ".join(parts[1:])
        
        if schedule_arg.lower() == "auto":
            # Mode automatique
            prefs = _load_prefs(cfg.queue_dir, chat_id)
            prefs["schedule_mode"] = "auto"
            _save_prefs(cfg.queue_dir, chat_id, prefs)
            await msg.reply_text("✅ Mode planification automatique activé (heures optimales)")
            
        elif schedule_arg.lower() == "now":
            # Mode immédiat
            prefs = _load_prefs(cfg.queue_dir, chat_id)
            prefs["schedule_mode"] = "now"
            _save_prefs(cfg.queue_dir, chat_id, prefs)
            await msg.reply_text("✅ Mode planification immédiate activé")
            
        else:
            # Heure spécifique
            try:
                from datetime import datetime
                scheduled_time = datetime.strptime(schedule_arg, "%Y-%m-%d %H:%M")
                
                # Vérifier que c'est dans le futur
                if scheduled_time <= datetime.now():
                    await msg.reply_text("❌ L'heure doit être dans le futur")
                    return
                
                # Sauvegarder l'heure spécifique
                prefs = _load_prefs(cfg.queue_dir, chat_id)
                prefs["schedule_mode"] = "custom"
                prefs["custom_schedule_time"] = scheduled_time.isoformat()
                _save_prefs(cfg.queue_dir, chat_id, prefs)
                
                # Mettre à jour la dernière tâche
                taskp = _get_last_task(cfg.queue_dir, chat_id)
                if taskp:
                    try:
                        data = json.loads(taskp.read_text(encoding="utf-8"))
                        if data.get("status") == "pending":
                            data["schedule_mode"] = "custom"
                            data["custom_schedule_time"] = scheduled_time.isoformat()
                            taskp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                    except Exception:
                        pass
                
                await msg.reply_text(f"✅ Upload planifié pour le {scheduled_time.strftime('%d/%m/%Y à %H:%M')}")
                
            except ValueError:
                await msg.reply_text("❌ Format invalide. Utilisez: YYYY-MM-DD HH:MM (ex: 2024-12-25 18:30)")

    app.add_handler(CommandHandler("schedule", _cmd_schedule))

    async def _cmd_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.message
        if not msg or not msg.text:
            return
        chat_id = msg.chat_id
        parts = msg.text.split()
        if len(parts) < 2:
            await msg.reply_text("Usage: /category <gaming|education|entertainment|music|tech|news|sports|comedy|howto|people>")
            return
        category_name = parts[1].lower()
        
        # Mapping des catégories YouTube courantes
        category_map = {
            "gaming": 20,
            "education": 27,
            "entertainment": 24,
            "music": 10,
            "tech": 28,
            "science": 28,
            "news": 25,
            "sports": 17,
            "comedy": 23,
            "howto": 26,
            "people": 22,
            "blogs": 22
        }
        
        if category_name not in category_map:
            await msg.reply_text("Catégorie invalide. Utilisez: gaming, education, entertainment, music, tech, news, sports, comedy, howto, people")
            return
        
        category_id = category_map[category_name]
        prefs = _load_prefs(cfg.queue_dir, chat_id)
        prefs["category_id"] = category_id
        _save_prefs(cfg.queue_dir, chat_id, prefs)
        
        taskp = _get_last_task(cfg.queue_dir, chat_id)
        if taskp:
            try:
                data = json.loads(taskp.read_text(encoding="utf-8"))
                if data.get("status") == "pending":
                    data["category_id"] = category_id
                    taskp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass
        await msg.reply_text(f"✅ Catégorie définie sur '{category_name}' (ID: {category_id}) pour ce chat.")

    app.add_handler(CommandHandler("category", _cmd_category))

    async def _cmd_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.message
        if not msg or not msg.text:
            return
        chat_id = msg.chat_id
        parts = msg.text.split()
        if len(parts) < 3 or parts[1].lower() != "quality":
            await msg.reply_text("Usage: /set quality <low|medium|high|youtube|max>")
            return
        preset = parts[2].lower()
        if preset not in ("low", "medium", "high", "youtube", "max"):
            await msg.reply_text("Preset invalide. Choisissez: low, medium, high, youtube, max")
            return
        prefs = _load_prefs(cfg.queue_dir, chat_id)
        prefs["quality"] = preset
        _save_prefs(cfg.queue_dir, chat_id, prefs)
        # Mettre aussi à jour la dernière tâche si encore pending
        taskp = _get_last_task(cfg.queue_dir, chat_id)
        if taskp:
            try:
                data = json.loads(taskp.read_text(encoding="utf-8"))
                if data.get("status") in (None, "pending"):
                    data.setdefault("prefs", {})["quality"] = preset
                    taskp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass
        await msg.reply_text(f"✅ Qualité préférée définie sur: {preset}")

    async def _cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.message
        if not msg:
            return
        chat_id = msg.chat_id
        taskp = _get_last_task(cfg.queue_dir, chat_id)
        if not taskp:
            await msg.reply_text("Aucune tâche récente trouvée.")
            return
        try:
            data = json.loads(taskp.read_text(encoding="utf-8"))
            if data.get("status") in (None, "pending"):
                data["status"] = "cancelled"
                taskp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                await msg.reply_text("✅ Tâche annulée.")
            else:
                await msg.reply_text("Impossible d'annuler: tâche déjà traitée.")
        except Exception:
            await msg.reply_text("Erreur: impossible d'annuler la tâche.")

    async def _cmd_redo(update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.message
        if not msg:
            return
        chat_id = msg.chat_id
        taskp = _get_last_task(cfg.queue_dir, chat_id)
        if not taskp:
            await msg.reply_text("Aucune tâche récente trouvée.")
            return
        try:
            data = json.loads(taskp.read_text(encoding="utf-8"))
            video_path = data.get("video_path")
            if not video_path or not Path(video_path).exists():
                await msg.reply_text("Impossible de recréer la tâche: vidéo introuvable.")
                return
            ts = int(datetime.utcnow().timestamp())
            new_task = {
                "source": "telegram",
                "chat_id": chat_id,
                "received_at": datetime.utcnow().isoformat() + "Z",
                "video_path": video_path,
                "status": "pending",
                "steps": ["enhance", "ai_meta", "upload"],
                "prefs": data.get("prefs") or _load_prefs(cfg.queue_dir, chat_id),
                "meta": data.get("meta") or {},
            }
            new_taskp = cfg.queue_dir / f"task_{ts}_{chat_id}.json"
            new_taskp.write_text(json.dumps(new_task, ensure_ascii=False, indent=2), encoding="utf-8")
            _set_last_task(cfg.queue_dir, chat_id, new_taskp)
            await msg.reply_text("✅ Nouvelle tâche recréée à partir de la dernière.")
        except Exception:
            await msg.reply_text("Erreur: impossible de recréer la tâche.")

    app.add_handler(CommandHandler("set", _cmd_set))
    app.add_handler(CommandHandler("cancel", _cmd_cancel))
    app.add_handler(CommandHandler("redo", _cmd_redo))
    
    # Enregistrer les commandes de gestion des comptes
    from .account_commands import register_account_commands
    register_account_commands(app)

    async def _on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query:
            return
        data = query.data or ""
        chat_id = query.message.chat_id if query.message else None
        await query.answer()
        # Menus
        if data == "action:quality_menu":
            await query.edit_message_reply_markup(reply_markup=_quality_menu_keyboard())
            return
        if data == "action:back_main":
            await query.edit_message_reply_markup(reply_markup=_main_menu_keyboard())
            return
        if data == "action:account_menu":
            await query.edit_message_reply_markup(reply_markup=_account_menu_keyboard(chat_id))
            return
        # Account selection
        if data.startswith("account:"):
            account_id = data.split(":", 1)[1]
            if chat_id is None:
                return
            
            # Vérifier si multi-comptes activé
            try:
                from .config_loader import load_config
                config = load_config("config/video.yaml")
                if not config.get("multi_accounts", {}).get("enabled", False):
                    await query.edit_message_text("❌ Multi-comptes désactivé", reply_markup=_main_menu_keyboard())
                    return
                
                from .multi_account_manager import create_multi_account_manager
                manager = create_multi_account_manager()
                
                if manager.set_chat_account(str(chat_id), account_id):
                    account = manager.accounts.get(account_id)
                    account_name = account.name if account else account_id
                    await query.edit_message_text(f"✅ Compte sélectionné: {account_name}", reply_markup=_main_menu_keyboard())
                else:
                    await query.edit_message_text("❌ Erreur lors de la sélection du compte", reply_markup=_main_menu_keyboard())
                    
            except Exception as e:
                await query.edit_message_text(f"❌ Erreur: {str(e)}", reply_markup=_main_menu_keyboard())
            return
        
        # Status / Redo / Cancel
        if data == "action:status":
            # Afficher status sous forme de nouveau message pour garder le menu
            fake_update = Update(
                update.update_id,
                message=query.message
            )
            await _cmd_status(fake_update, context)  # type: ignore[arg-type]
            return
        if data == "action:redo":
            msg = query.message
            if msg:
                # Reutiliser la logique de _cmd_redo
                await _cmd_redo(Update(update.update_id, message=msg), context)  # type: ignore[arg-type]
            return
        if data == "action:cancel":
            msg = query.message
            if msg:
                await _cmd_cancel(Update(update.update_id, message=msg), context)  # type: ignore[arg-type]
            return
        # Set quality
        if data.startswith("setq:"):
            preset = data.split(":", 1)[1]
            if preset not in ("low", "medium", "high", "youtube", "max"):
                await query.edit_message_text("Preset invalide.", reply_markup=_quality_menu_keyboard())
                return
            if chat_id is None:
                return
            prefs = _load_prefs(cfg.queue_dir, chat_id)
            prefs["quality"] = preset
            _save_prefs(cfg.queue_dir, chat_id, prefs)
            # Mettre à jour la dernière tâche si pending
            taskp = _get_last_task(cfg.queue_dir, chat_id)
            if taskp:
                try:
                    dataj = json.loads(taskp.read_text(encoding="utf-8"))
                    if dataj.get("status") in (None, "pending"):
                        dataj.setdefault("prefs", {})["quality"] = preset
                        taskp.write_text(json.dumps(dataj, ensure_ascii=False, indent=2), encoding="utf-8")
                except Exception:
                    pass
            await query.edit_message_text(f"✅ Qualité préférée: {preset}", reply_markup=_main_menu_keyboard())

    app.add_handler(CallbackQueryHandler(_on_callback))
    return app


def run_bot_from_sources(sources_path: str | Path) -> None:
    data = load_sources_yaml(sources_path)
    tg = data.get("telegram") or {}
    cfg = TelegramConfig.from_dict(tg)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    app = build_application(cfg)
    log.info("Démarrage du bot Telegram…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
