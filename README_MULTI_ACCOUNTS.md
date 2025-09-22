# 📺 Gestion Multi-Comptes YouTube

Ce système permet de gérer plusieurs chaînes YouTube avec load balancing automatique et gestion des quotas.

## 🚀 Activation

1. **Activer dans la configuration**

```yaml
# config/video.yaml
multi_accounts:
  enabled: true  # Activer la gestion multi-comptes
  config_path: "config/multi_accounts.json"
  
  load_balancing:
    strategy: "quota_based"  # quota_based, round_robin, least_used
    auto_switch: true
    fallback_enabled: true
  
  default_limits:
    daily_quota_limit: 10000
    daily_upload_limit: 6
    api_calls_per_upload: 1600
```

1. **Configurer les comptes**

```bash
# Copier le fichier exemple
cp config/multi_accounts.example.json config/multi_accounts.json

# Éditer avec vos comptes
nano config/multi_accounts.json
```

## 🔧 Configuration des Comptes

### Structure JSON

```json
{
  "accounts": [
    {
      "account_id": "main",
      "name": "Chaîne Principale",
      "channel_id": "",
      "credentials_path": "config/credentials_main.json",
      "token_path": "config/token_main.json",
      "daily_quota_limit": 10000,
      "daily_upload_limit": 6,
      "enabled": true
    }
  ],
  "chat_mappings": {
    "123456789": "main"
  }
}
```

### Fichiers de Credentials

Chaque compte nécessite ses propres fichiers :

- `credentials_main.json` : Secrets client OAuth2
- `token_main.json` : Token d'accès (généré automatiquement)

## 📱 Commandes Telegram

### Gestion des Comptes

- `/accounts` - Liste des comptes disponibles
- `/account_add <id> <nom> <credentials_path>` - Ajouter un compte
- `/account_remove <id>` - Supprimer un compte
- `/account_select <id>` - Sélectionner un compte pour ce chat
- `/account_status [id]` - Statut détaillé d'un compte

### Exemples

```bash
# Ajouter un compte gaming
/account_add gaming "Chaîne Gaming" config/creds_gaming.json

# Sélectionner le compte gaming pour ce chat
/account_select gaming

# Voir le statut du compte actuel
/account_status
```

## 🎯 Load Balancing

### Stratégies Disponibles

1. **quota_based** (recommandé)
   - Sélectionne le compte avec le moins d'utilisation
   - Prend en compte uploads et quotas API
   - Évite automatiquement les comptes saturés

2. **round_robin**
   - Rotation équitable entre tous les comptes
   - Simple mais ne considère pas l'utilisation

3. **least_used**
   - Compte avec le moins d'uploads récents
   - Bon pour équilibrer la charge

### Fonctionnement Automatique

- **Auto-Switch** : Bascule automatiquement si quota atteint
- **Fallback** : Utilise un compte de secours si nécessaire
- **Monitoring** : Suivi en temps réel des quotas et limites

## 📊 Gestion des Quotas

### Limites par Défaut

- **Quota API** : 10,000 unités/jour
- **Uploads** : 6 vidéos/jour
- **Coût par upload** : ~1,600 unités API

### Suivi Automatique

- Comptage des uploads par compte
- Monitoring de l'utilisation API
- Réinitialisation quotidienne automatique
- Alertes en cas de limite atteinte

## 🔄 Interface Telegram

### Bouton Account

Quand multi-comptes activé, un bouton "👤 Account" apparaît dans le menu principal :

- Affiche tous les comptes disponibles
- Indique le compte actuellement sélectionné (✅)
- Montre l'utilisation des quotas en temps réel
- Permet de changer de compte d'un clic

### Statut dans les Métadonnées

```text
- Compte: Chaîne Gaming (multi-comptes)
```

## 🛠️ Configuration Avancée

### Mapping Chat → Compte

```json
"chat_mappings": {
  "123456789": "main",      // Chat admin → compte principal
  "987654321": "gaming",    // Chat gaming → compte gaming
  "555666777": "tech"       // Chat tech → compte tech
}
```

### Limites Personnalisées

```json
{
  "account_id": "premium",
  "daily_quota_limit": 50000,  // Quota premium
  "daily_upload_limit": 20,    // Plus d'uploads
  "enabled": true
}
```

## 🚨 Gestion des Erreurs

### uploadLimitExceeded

- Détection automatique des limites YouTube
- Basculement vers un autre compte disponible
- Archivage des tâches bloquées
- Retry automatique le lendemain

### Quota API Épuisé

- Monitoring en temps réel
- Sélection automatique d'un autre compte
- Alertes dans les logs
- Statistiques détaillées

## 📈 Monitoring

### Logs Détaillés

```text
[INFO] Compte sélectionné pour upload: Chaîne Gaming (score: 0.85)
[INFO] Upload enregistré pour gaming: 3/6 uploads
[INFO] Quota enregistré pour le compte gaming
```

### Commandes de Debug

```bash
# Statut de tous les comptes
/accounts

# Statut détaillé d'un compte
/account_status gaming

# Forcer le nettoyage des quotas
# (automatique mais peut être utile pour debug)
```

## 🔐 Sécurité

### Isolation des Credentials

- Chaque compte a ses propres fichiers OAuth2
- Tokens stockés séparément
- Pas de partage de credentials entre comptes

### Permissions Minimales

- Seuls les scopes YouTube nécessaires
- Pas d'accès aux autres services Google
- Révocation facile par compte

## 🎯 Cas d'Usage

### Multi-Chaînes Thématiques

```json
{
  "gaming": "Contenu gaming",
  "tech": "Reviews tech", 
  "lifestyle": "Vlogs lifestyle"
}
```

### Load Balancing Quotas

```json
{
  "main_morning": "Uploads matinaux",
  "main_evening": "Uploads soirée",
  "backup": "Compte de secours"
}
```

### Séparation Géographique

```json
{
  "france": "Contenu français",
  "international": "Contenu anglais"
}
```

Le système multi-comptes offre une flexibilité maximale pour gérer plusieurs chaînes YouTube de manière automatisée et optimisée ! 🚀
