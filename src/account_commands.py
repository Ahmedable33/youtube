"""
Commandes Telegram pour la gestion des comptes multiples
"""

import logging
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler

from .multi_account_manager import create_multi_account_manager, YouTubeAccount
from .config_loader import load_config

log = logging.getLogger(__name__)


async def cmd_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Afficher la liste des comptes disponibles"""
    msg = update.message
    if not msg:
        return

    try:
        config = load_config("config/video.yaml")
        if not config.get("multi_accounts", {}).get("enabled", False):
            await msg.reply_text("❌ La gestion multi-comptes n'est pas activée")
            return

        manager = create_multi_account_manager()
        accounts_status = manager.get_all_accounts_status()

        if not accounts_status:
            await msg.reply_text("❌ Aucun compte configuré")
            return

        # Obtenir le compte actuel pour ce chat
        current_account = manager.get_chat_account(str(msg.chat_id))
        current_id = current_account.account_id if current_account else None

        lines = ["📺 **Comptes YouTube disponibles:**\n"]

        for status in accounts_status:
            account_id = status["account_id"]
            name = status["name"]
            enabled = status["enabled"]
            uploads_used = status["uploads_used"]
            uploads_limit = status["uploads_limit"]
            quota_percentage = status["quota_percentage"]
            can_upload = status["can_upload"]

            # Indicateurs
            current_indicator = "✅ " if account_id == current_id else "📺 "
            status_indicator = "🟢" if can_upload else "🔴"

            lines.append(
                f"{current_indicator}**{name}** {status_indicator}\n"
                f"   • Uploads: {uploads_used}/{uploads_limit}\n"
                f"   • Quota API: {quota_percentage:.1f}%\n"
                f"   • Statut: {'Disponible' if can_upload else 'Limite atteinte'}\n"
            )

        # Boutons d'action
        keyboard = [
            [InlineKeyboardButton("🔄 Rafraîchir", callback_data="accounts_refresh")],
            [InlineKeyboardButton("➕ Ajouter compte", callback_data="accounts_add")],
        ]

        await msg.reply_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    except Exception as e:
        log.error(f"Erreur commande /accounts: {e}")
        await msg.reply_text(f"❌ Erreur: {str(e)}")


async def cmd_account_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ajouter un nouveau compte YouTube"""
    msg = update.message
    if not msg or not msg.text:
        return

    parts = msg.text.split()
    if len(parts) < 4:
        await msg.reply_text(
            "Usage: /account_add <id> <nom> <credentials_path> [token_path]\n\n"
            "Exemple:\n"
            '`/account_add gaming "Chaîne Gaming" config/creds_gaming.json config/token_gaming.json`',
            parse_mode="Markdown",
        )
        return

    account_id = parts[1]
    name = parts[2].strip('"')
    credentials_path = parts[3]
    token_path = parts[4] if len(parts) > 4 else f"config/token_{account_id}.json"

    try:
        config = load_config("config/video.yaml")
        if not config.get("multi_accounts", {}).get("enabled", False):
            await msg.reply_text("❌ La gestion multi-comptes n'est pas activée")
            return

        # Vérifier que le fichier credentials existe
        if not Path(credentials_path).exists():
            await msg.reply_text(
                f"❌ Fichier credentials introuvable: {credentials_path}"
            )
            return

        # Créer le compte
        account = YouTubeAccount(
            account_id=account_id,
            name=name,
            channel_id="",  # Sera rempli automatiquement
            credentials_path=credentials_path,
            token_path=token_path,
            daily_quota_limit=config.get("multi_accounts", {})
            .get("default_limits", {})
            .get("daily_quota_limit", 10000),
            daily_upload_limit=config.get("multi_accounts", {})
            .get("default_limits", {})
            .get("daily_upload_limit", 6),
            enabled=True,
        )

        manager = create_multi_account_manager()

        if manager.add_account(account):
            await msg.reply_text(f"✅ Compte ajouté: {name} ({account_id})")
        else:
            await msg.reply_text("❌ Erreur lors de l'ajout du compte")

    except Exception as e:
        log.error(f"Erreur ajout compte: {e}")
        await msg.reply_text(f"❌ Erreur: {str(e)}")


async def cmd_account_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Supprimer un compte YouTube"""
    msg = update.message
    if not msg or not msg.text:
        return

    parts = msg.text.split()
    if len(parts) < 2:
        await msg.reply_text("Usage: /account_remove <account_id>")
        return

    account_id = parts[1]

    try:
        config = load_config("config/video.yaml")
        if not config.get("multi_accounts", {}).get("enabled", False):
            await msg.reply_text("❌ La gestion multi-comptes n'est pas activée")
            return

        manager = create_multi_account_manager()

        if manager.remove_account(account_id):
            await msg.reply_text(f"✅ Compte supprimé: {account_id}")
        else:
            await msg.reply_text(f"❌ Compte introuvable: {account_id}")

    except Exception as e:
        log.error(f"Erreur suppression compte: {e}")
        await msg.reply_text(f"❌ Erreur: {str(e)}")


async def cmd_account_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sélectionner un compte pour ce chat"""
    msg = update.message
    if not msg or not msg.text:
        return

    parts = msg.text.split()
    if len(parts) < 2:
        await msg.reply_text("Usage: /account_select <account_id>")
        return

    account_id = parts[1]

    try:
        config = load_config("config/video.yaml")
        if not config.get("multi_accounts", {}).get("enabled", False):
            await msg.reply_text("❌ La gestion multi-comptes n'est pas activée")
            return

        manager = create_multi_account_manager()

        if manager.set_chat_account(str(msg.chat_id), account_id):
            account = manager.accounts.get(account_id)
            account_name = account.name if account else account_id
            await msg.reply_text(f"✅ Compte sélectionné: {account_name}")
        else:
            await msg.reply_text(
                f"❌ Impossible de sélectionner le compte: {account_id}"
            )

    except Exception as e:
        log.error(f"Erreur sélection compte: {e}")
        await msg.reply_text(f"❌ Erreur: {str(e)}")


async def cmd_account_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Afficher le statut détaillé d'un compte"""
    msg = update.message
    if not msg or not msg.text:
        return

    parts = msg.text.split()
    account_id = parts[1] if len(parts) > 1 else None

    try:
        config = load_config("config/video.yaml")
        if not config.get("multi_accounts", {}).get("enabled", False):
            await msg.reply_text("❌ La gestion multi-comptes n'est pas activée")
            return

        manager = create_multi_account_manager()

        # Si pas d'ID spécifié, utiliser le compte actuel du chat
        if not account_id:
            current_account = manager.get_chat_account(str(msg.chat_id))
            if not current_account:
                await msg.reply_text("❌ Aucun compte sélectionné pour ce chat")
                return
            account_id = current_account.account_id

        status = manager.get_account_status(account_id)

        if not status:
            await msg.reply_text(f"❌ Compte introuvable: {account_id}")
            return

        lines = [
            f"📺 **Statut du compte: {status['name']}**\n",
            f"🆔 ID: `{status['account_id']}`",
            f"📊 Statut: {'🟢 Actif' if status['enabled'] else '🔴 Désactivé'}",
            f"📤 Uploads: {status['uploads_used']}/{status['uploads_limit']} ({status['uploads_remaining']} restants)",
            f"⚡ Quota API: {status['quota_percentage']:.1f}% ({status['api_calls_used']}/{status['api_calls_limit']})",
            f"🚀 Peut uploader: {'✅ Oui' if status['can_upload'] else '❌ Non'}",
        ]

        if status["last_upload"]:
            from datetime import datetime

            last_upload = datetime.fromisoformat(status["last_upload"])
            lines.append(
                f"🕒 Dernier upload: {last_upload.strftime('%d/%m/%Y à %H:%M')}"
            )

        await msg.reply_text("\n".join(lines), parse_mode="Markdown")

    except Exception as e:
        log.error(f"Erreur statut compte: {e}")
        await msg.reply_text(f"❌ Erreur: {str(e)}")


def register_account_commands(app):
    """Enregistrer les commandes de gestion des comptes"""
    app.add_handler(CommandHandler("accounts", cmd_accounts))
    app.add_handler(CommandHandler("account_add", cmd_account_add))
    app.add_handler(CommandHandler("account_remove", cmd_account_remove))
    app.add_handler(CommandHandler("account_select", cmd_account_select))
    app.add_handler(CommandHandler("account_status", cmd_account_status))
