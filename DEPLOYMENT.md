# Guide de Déploiement

Ce document explique comment configurer et exécuter le déploiement de l'application YouTube Automation.

## Prérequis

1. Un compte Google Cloud Platform avec les API YouTube activées
2. Un bucket S3 AWS pour le stockage (optionnel)
3. Un serveur ou un service d'hébergement

## Configuration des Secrets

### 1. Configuration des Secrets GitHub

#### Secrets Requis

| Nom du secret | Description | Où le trouver |
|--------------|-------------|----------------|
| `GOOGLE_CREDENTIALS` | Fichier JSON des credentials Google Cloud | Google Cloud Console > IAM > Comptes de service > Clés
| `YOUTUBE_CREDENTIALS` | Fichier JSON OAuth 2.0 pour l'API YouTube | Google API Console > Identifiants
| `AWS_ACCESS_KEY_ID` | Clé d'accès AWS | AWS IAM Console > Utilisateurs > Sécurité
| `AWS_SECRET_ACCESS_KEY` | Clé secrète AWS | Même endroit que la clé d'accès
| `CODECOV_TOKEN` | Token pour les rapports de couverture | Codecov.io > Settings
| `SLACK_WEBHOOK_URL` | (Optionnel) URL du webhook Slack | Slack > Administration > Gérer les applications > Incoming Webhooks

#### Comment ajouter un secret :
1. Allez dans les paramètres de votre dépôt GitHub
2. Cliquez sur "Secrets and variables" > "Actions"
3. Cliquez sur "New repository secret"
4. Entrez le nom du secret et sa valeur
5. Cliquez sur "Add secret"

#### Variables d'environnement recommandées

| Variable | Valeur par défaut | Description |
|----------|-------------------|-------------|
| `AWS_DEFAULT_REGION` | `us-east-1` | Région AWS par défaut |
| `ENVIRONMENT` | `development` | Environnement d'exécution |
| `LOG_LEVEL` | `INFO` | Niveau de journalisation |

### 2. Variables d'environnement

Créez un fichier `.env` à la racine du projet avec les variables suivantes :

```env
# Configuration Google Cloud
GOOGLE_APPLICATION_CREDENTIALS=config/google_credentials.json
YOUTUBE_CREDENTIALS=config/youtube_credentials.json

# Configuration AWS (optionnel)
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_DEFAULT_REGION=us-east-1

# Configuration de l'application
ENVIRONMENT=production
LOG_LEVEL=INFO
```

## Déploiement Automatique

Le déploiement est automatique lors d'un push sur la branche `main`. Le workflow effectue les étapes suivantes :

1. Exécution des tests
2. Vérification de la qualité du code
3. Configuration des credentials
4. Déploiement sur l'environnement de production
5. Vérification post-déploiement

## Déploiement Manuel

Pour déclencher un déploiement manuellement :

1. Allez dans l'onglet "Actions" de votre dépôt GitHub
2. Sélectionnez le workflow "CI/CD Pipeline"
3. Cliquez sur "Run workflow"
4. Sélectionnez la branche à déployer
5. Cliquez sur "Run workflow"

## Surveillance

Après le déploiement, surveillez :

1. Les logs d'application
2. Les métriques de performance
3. Les erreurs éventuelles
4. Les notifications Slack (si configurées)

## Rollback

En cas de problème, vous pouvez restaurer une version précédente :

1. Identifiez le commit stable précédent
2. Créez une branche de hotfix
3. Revenez à la version précédente
4. Poussez les modifications

## Sécurité

- Ne committez jamais de fichiers de configuration sensibles
- Utilisez des rôles IAM avec le principe du moindre privilège
- Mettez à jour régulièrement les dépendances
- Surveillez les journaux d'accès

## Dépannage

### Erreurs d'authentification
- Vérifiez que les credentials sont valides
- Vérifiez les permissions du compte de service
- Vérifiez que les API nécessaires sont activées

### Échec du déploiement
- Consultez les logs du workflow GitHub Actions
- Vérifiez les journaux du serveur
- Vérifiez l'espace disque et les permissions

Pour toute autre question, consultez la documentation ou créez une issue.
