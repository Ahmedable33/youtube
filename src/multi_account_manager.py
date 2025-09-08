"""
Gestionnaire multi-comptes YouTube
Permet de gérer plusieurs chaînes YouTube avec load balancing et quotas
"""

import logging
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Iterable
from dataclasses import dataclass, asdict
import hashlib

from .auth import get_credentials

log = logging.getLogger(__name__)

@dataclass
class YouTubeAccount:
    """Configuration d'un compte YouTube"""
    account_id: str
    name: str
    channel_id: str
    credentials_path: str
    token_path: str
    daily_quota_limit: int = 10000  # Quota API par jour
    daily_upload_limit: int = 6     # Uploads max par jour
    enabled: bool = True
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'YouTubeAccount':
        return cls(**data)

@dataclass
class QuotaUsage:
    """Utilisation des quotas d'un compte"""
    account_id: str
    date: str  # YYYY-MM-DD
    api_calls: int = 0
    uploads: int = 0
    last_upload: Optional[datetime] = None
    
    def to_dict(self) -> Dict:
        data = asdict(self)
        if self.last_upload:
            data['last_upload'] = self.last_upload.isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'QuotaUsage':
        if data.get('last_upload'):
            data['last_upload'] = datetime.fromisoformat(data['last_upload'])
        return cls(**data)

class MultiAccountManager:
    """Gestionnaire principal des comptes multiples"""
    
    def __init__(self, config_path: Path):
        self.config_path = Path(config_path)
        self.accounts: Dict[str, YouTubeAccount] = {}
        self.chat_mappings: Dict[str, str] = {}  # chat_id -> account_id
        self.quota_usage: Dict[str, QuotaUsage] = {}
        
        # Créer les répertoires nécessaires
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Charger la configuration
        self._load_config()
        self._load_quota_usage()
    
    def _load_config(self):
        """Charger la configuration des comptes"""
        if not self.config_path.exists():
            self._create_default_config()
            return
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # Charger les comptes
            for account_data in config.get("accounts", []):
                account = YouTubeAccount.from_dict(account_data)
                self.accounts[account.account_id] = account
            
            # Charger les mappings chat -> compte
            self.chat_mappings = config.get("chat_mappings", {})
            
            log.info(f"Configuration chargée: {len(self.accounts)} comptes, {len(self.chat_mappings)} mappings")
            
        except Exception as e:
            log.error(f"Erreur chargement config multi-comptes: {e}")
            self._create_default_config()
    
    def _create_default_config(self):
        """Créer une configuration par défaut"""
        default_config = {
            "accounts": [
                {
                    "account_id": "main",
                    "name": "Compte Principal",
                    "channel_id": "",
                    "credentials_path": "config/credentials_main.json",
                    "token_path": "config/token_main.json",
                    "daily_quota_limit": 10000,
                    "daily_upload_limit": 6,
                    "enabled": True
                }
            ],
            "chat_mappings": {},
            "load_balancing": {
                "strategy": "round_robin",  # round_robin, least_used, quota_based
                "auto_switch": True,
                "fallback_enabled": True
            }
        }
        
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, ensure_ascii=False, indent=2)
            
            # Charger la config par défaut
            self.accounts["main"] = YouTubeAccount.from_dict(default_config["accounts"][0])
            
        except Exception as e:
            log.error(f"Erreur création config par défaut: {e}")
    
    def _save_config(self):
        """Sauvegarder la configuration"""
        try:
            config = {
                "accounts": [account.to_dict() for account in self.accounts.values()],
                "chat_mappings": self.chat_mappings,
                "load_balancing": {
                    "strategy": "quota_based",
                    "auto_switch": True,
                    "fallback_enabled": True
                }
            }
            
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            log.error(f"Erreur sauvegarde config: {e}")
    
    def _load_quota_usage(self):
        """Charger l'utilisation des quotas"""
        quota_file = self.config_path.parent / "quota_usage.json"
        
        if not quota_file.exists():
            return
        
        try:
            with open(quota_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            today = datetime.now().strftime("%Y-%m-%d")
            
            for account_id, usage_data in data.items():
                if usage_data.get("date") == today:  # Seulement les données du jour
                    self.quota_usage[account_id] = QuotaUsage.from_dict(usage_data)
                    
        except Exception as e:
            log.error(f"Erreur chargement quotas: {e}")
    
    def _save_quota_usage(self):
        """Sauvegarder l'utilisation des quotas"""
        quota_file = self.config_path.parent / "quota_usage.json"
        
        try:
            data = {}
            for account_id, usage in self.quota_usage.items():
                data[account_id] = usage.to_dict()
            
            with open(quota_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            log.error(f"Erreur sauvegarde quotas: {e}")
    
    def add_account(self, account: YouTubeAccount) -> bool:
        """Ajouter un nouveau compte"""
        try:
            # Vérifier que les fichiers de credentials existent
            if not Path(account.credentials_path).exists():
                log.error(f"Fichier credentials introuvable: {account.credentials_path}")
                return False
            
            self.accounts[account.account_id] = account
            self._save_config()
            
            log.info(f"Compte ajouté: {account.name} ({account.account_id})")
            return True
            
        except Exception as e:
            log.error(f"Erreur ajout compte: {e}")
            return False
    
    def remove_account(self, account_id: str) -> bool:
        """Supprimer un compte"""
        if account_id not in self.accounts:
            return False
        
        # Supprimer les mappings associés
        self.chat_mappings = {k: v for k, v in self.chat_mappings.items() if v != account_id}
        
        # Supprimer le compte
        del self.accounts[account_id]
        
        # Supprimer les quotas
        if account_id in self.quota_usage:
            del self.quota_usage[account_id]
        
        self._save_config()
        self._save_quota_usage()
        
        log.info(f"Compte supprimé: {account_id}")
        return True
    
    def set_chat_account(self, chat_id: str, account_id: str) -> bool:
        """Associer un chat à un compte"""
        if account_id not in self.accounts:
            log.error(f"Compte inexistant: {account_id}")
            return False
        
        if not self.accounts[account_id].enabled:
            log.error(f"Compte désactivé: {account_id}")
            return False
        
        self.chat_mappings[str(chat_id)] = account_id
        self._save_config()
        
        log.info(f"Chat {chat_id} associé au compte {account_id}")
        return True
    
    def get_chat_account(self, chat_id: str) -> Optional[YouTubeAccount]:
        """Obtenir le compte associé à un chat"""
        account_id = self.chat_mappings.get(str(chat_id))
        
        if account_id and account_id in self.accounts:
            account = self.accounts[account_id]
            if account.enabled:
                return account
        
        # Fallback: utiliser le load balancing
        return self.get_best_account_for_upload()
    
    def get_best_account_for_upload(self) -> Optional[YouTubeAccount]:
        """Sélectionner le meilleur compte pour un upload (load balancing)"""
        available_accounts = [acc for acc in self.accounts.values() if acc.enabled]
        
        if not available_accounts:
            log.error("Aucun compte disponible pour upload")
            return None
        
        today = datetime.now().strftime("%Y-%m-%d")
        
        # Calculer les scores pour chaque compte
        account_scores = []
        
        for account in available_accounts:
            usage = self.quota_usage.get(account.account_id)
            
            if not usage or usage.date != today:
                # Pas d'utilisation aujourd'hui = score maximum
                score = 1.0
                uploads_used = 0
                api_calls_used = 0
            else:
                uploads_used = usage.uploads
                api_calls_used = usage.api_calls
                
                # Calculer le score basé sur l'utilisation
                upload_ratio = uploads_used / account.daily_upload_limit
                quota_ratio = api_calls_used / account.daily_quota_limit
                
                # Score inversé (moins d'utilisation = meilleur score)
                score = 1.0 - max(upload_ratio, quota_ratio)
            
            # Vérifier si le compte peut encore uploader
            if uploads_used >= account.daily_upload_limit:
                score = 0.0  # Compte saturé
            
            account_scores.append((account, score, uploads_used, api_calls_used))
        
        # Trier par score décroissant
        account_scores.sort(key=lambda x: x[1], reverse=True)
        
        best_account = account_scores[0][0]
        best_score = account_scores[0][1]
        
        if best_score <= 0:
            log.warning("Tous les comptes ont atteint leurs limites quotidiennes")
            return None
        
        log.info(f"Compte sélectionné pour upload: {best_account.name} (score: {best_score:.2f})")
        return best_account
    
    def record_upload(self, account_id: str, api_calls_used: int = 1600):
        """Enregistrer un upload et la consommation de quota"""
        today = datetime.now().strftime("%Y-%m-%d")
        
        if account_id not in self.quota_usage:
            self.quota_usage[account_id] = QuotaUsage(
                account_id=account_id,
                date=today
            )
        
        usage = self.quota_usage[account_id]
        
        # Réinitialiser si nouvelle journée
        if usage.date != today:
            usage.date = today
            usage.api_calls = 0
            usage.uploads = 0
        
        # Enregistrer l'upload
        usage.uploads += 1
        usage.api_calls += api_calls_used
        usage.last_upload = datetime.now()
        
        self._save_quota_usage()
        
        log.info(f"Upload enregistré pour {account_id}: {usage.uploads}/{self.accounts[account_id].daily_upload_limit} uploads")
    
    def get_account_status(self, account_id: str) -> Dict:
        """Obtenir le statut détaillé d'un compte"""
        if account_id not in self.accounts:
            return {}
        
        account = self.accounts[account_id]
        today = datetime.now().strftime("%Y-%m-%d")
        usage = self.quota_usage.get(account_id)
        
        if not usage or usage.date != today:
            uploads_used = 0
            api_calls_used = 0
            last_upload = None
        else:
            uploads_used = usage.uploads
            api_calls_used = usage.api_calls
            last_upload = usage.last_upload
        
        return {
            "account_id": account_id,
            "name": account.name,
            "enabled": account.enabled,
            "uploads_used": uploads_used,
            "uploads_limit": account.daily_upload_limit,
            "uploads_remaining": max(0, account.daily_upload_limit - uploads_used),
            "api_calls_used": api_calls_used,
            "api_calls_limit": account.daily_quota_limit,
            "quota_percentage": (api_calls_used / account.daily_quota_limit) * 100,
            "last_upload": last_upload.isoformat() if last_upload else None,
            "can_upload": uploads_used < account.daily_upload_limit and account.enabled
        }
    
    def get_all_accounts_status(self) -> List[Dict]:
        """Obtenir le statut de tous les comptes"""
        return [self.get_account_status(acc_id) for acc_id in self.accounts.keys()]
    
    def get_credentials_for_account(
        self,
        account_id: str,
        scopes: Optional[Iterable[str]] = None,
        headless: bool = False,
    ):
        """Obtenir les credentials pour un compte spécifique.
        Args:
            account_id: ID du compte configuré.
            scopes: Scopes OAuth requis. Défaut: scopes YouTube upload.
            headless: Flux OAuth en console.
        """
        if account_id not in self.accounts:
            raise ValueError(f"Compte inexistant: {account_id}")

        account = self.accounts[account_id]

        if scopes is None:
            scopes = [
                "https://www.googleapis.com/auth/youtube.upload",
                "https://www.googleapis.com/auth/youtube.force-ssl",
            ]

        try:
            return get_credentials(
                scopes,
                client_secrets_path=account.credentials_path,
                token_path=account.token_path,
                headless=headless,
            )
        except Exception as e:
            log.error(f"Erreur récupération credentials pour {account_id}: {e}")
            raise
    
    def cleanup_old_quota_data(self):
        """Nettoyer les anciennes données de quota"""
        today = datetime.now().strftime("%Y-%m-%d")
        
        # Supprimer les données qui ne sont pas d'aujourd'hui
        old_accounts = [
            acc_id for acc_id, usage in self.quota_usage.items()
            if usage.date != today
        ]
        
        for acc_id in old_accounts:
            del self.quota_usage[acc_id]
        
        if old_accounts:
            self._save_quota_usage()
            log.info(f"Nettoyage: {len(old_accounts)} anciennes données de quota supprimées")

def create_multi_account_manager(config_path: str = "config/multi_accounts.json") -> MultiAccountManager:
    """Créer un gestionnaire multi-comptes"""
    try:
        return MultiAccountManager(Path(config_path))
    except Exception as e:
        log.error(f"Erreur création gestionnaire multi-comptes: {e}")
        raise
