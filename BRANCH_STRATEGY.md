# Stratégie de Branchement et Bonnes Pratiques

## 📋 Vue d'ensemble

Ce document décrit notre stratégie de branchement, nos processus de développement et nos standards de qualité de code.

## 🌿 Stratégie de Branchement (GitHub Flow)

Nous suivons une version adaptée de GitHub Flow pour un cycle de développement rapide et efficace :

1. **`main`** - Branche principale, toujours déployable

   - Protégée contre les pushes directs
   - Nécessite des pull requests (PR) avec approbation
   - Doit toujours être stable et prête pour la production

2. **Branches de fonctionnalité** `feature/*`

   - Préfixe : `feature/`
   - Exemple : `feature/add-login-form`
   - Créée à partir de `main`
   - Fusionnée via PR après revue

3. **Branches de correction** `fix/*`

   - Pour les corrections de bugs
   - Exemple : `fix/login-error-403`
   - Fusion rapide dans `main`

4. **Branches de hotfix** `hotfix/*`
   - Pour les corrections critiques en production
   - Créée à partir de `main`
   - Fusionnée dans `main` et `develop`

## 🚀 Processus de Développement

1. **Avant de commencer**

   ```bash
   git checkout main
   git pull origin main
   git checkout -b feature/ma-nouvelle-fonctionnalite
   ```

2. **Pendant le développement**

   - Faites des commits atomiques avec des messages clairs
   - Poussez régulièrement votre branche
   - Créez une PR tôt (draft si nécessaire)

3. **Création d'une Pull Request**

   - Assurez-vous que les tests passent
   - Mettez à jour la documentation si nécessaire
   - Assignez des relecteurs
   - Ajoutez des labels pertinents

4. **Revue de code**

   - Au moins une approbation requise
   - Tous les commentaires doivent être adressés
   - Les conflits doivent être résolus

5. **Après la fusion**
   - Supprimez la branche distante
   - Mettez à jour votre branche `main` locale

## ✅ Standards de Qualité

### Tests

- Toutes les nouvelles fonctionnalités doivent inclure des tests
- Couverture de code minimale : 80%
- Les tests doivent être rapides et indépendants

### Linting et Formatage

- Utilisation de `black` pour le formatage
- Vérification avec `flake8`
- Vérification des types avec `mypy`

### Messages de Commit

Format : `type(portée): description`

Exemples :

- `feat(auth): add login with Google`
- `fix(api): handle null values in response`
- `docs(readme): update installation instructions`
- `test(worker): add test for retry logic`

## 🔒 Branches Protégées

La branche `main` est protégée avec les règles suivantes :

- Nécessite une revue de code
- Nécessite que les vérifications CI passent
- Nécessite un historique linéaire
- Interdit les force pushes

## 🔄 Intégration Continue

Le workflow CI exécute :

- Tests unitaires et d'intégration
- Vérification du style de code
- Analyse statique du code
- Génération de rapports de couverture

## 🚨 Procédure de Hotfix

1. Créez une branche depuis `main` :
   ```bash
   git checkout -b hotfix/description-du-problema main
   ```
2. Appliquez les corrections nécessaires
3. Créez une PR vers `main`
4. Après approbation, fusionnez et créez un tag de version
5. Déployez la correction en production

## 📚 Ressources

- [GitHub Flow](https://guides.github.com/introduction/flow/)
- [Conventional Commits](https://www.conventionalcommits.org/)
- [Python Code Style](https://www.python.org/dev/peps/pep-0008/)
