# Guide de Contribution

## 🔍 Vérifications pré-push en local

Pour éviter les échecs CI après avoir poussé, exécutez **toujours** les vérifications en local avant de pusher.

### 🚀 Méthode rapide (recommandée)

Le projet inclut un script et un git hook automatique :

```bash
# Exécution manuelle
./scripts/pre-push-checks.sh

# Ou laissez le git hook le faire automatiquement
git push  # Le hook s'exécute automatiquement
```

### 🛠️ Vérifications individuelles

#### 1. **Linting (flake8)**

```bash
flake8 src/ tests/ --max-line-length=88 --extend-ignore=E203,W503
```

#### 2. **Formatage (black)**

```bash
# Vérifier
black --check src/ tests/

# Corriger automatiquement
black src/ tests/
```

#### 3. **Tests complets**

```bash
# Tests avec couverture
pytest -v --cov=src --cov-report=term-missing

# Tests rapides (sans couverture)
pytest -q

# Tests d'un fichier spécifique
pytest tests/unit/test_worker_new_features.py -v
```

#### 4. **Type checking (optionnel)**

```bash
mypy src/ --ignore-missing-imports
```

### 📋 Checklist pré-PR

Avant de créer une Pull Request, vérifiez :

- [ ] **Description PR complète** (minimum 20 caractères)
- [ ] **Assigné un reviewer** ou vous-même comme assignee
- [ ] **Tests ajoutés** pour toute nouvelle fonctionnalité
- [ ] **Taille raisonnable** :
  - ≤ 60 fichiers modifiés
  - ≤ 3000 lignes changées (additions + deletions)
  - Sinon, ajoutez le label `skip-pr-size-check` si justifié
- [ ] **Pas de fichiers sensibles** (secrets, credentials, tokens)
- [ ] **Tous les tests passent** (`pytest -q`)
- [ ] **Linting propre** (`flake8 src/ tests/`)
- [ ] **Code formaté** (`black src/ tests/`)

### 🎯 Workflow CI/CD

#### CI Tests (`ci.yml`)

Vérifie automatiquement :

1. Installation des dépendances
2. Linting avec flake8
3. Tests avec pytest + couverture
4. Génération des artifacts (coverage.xml, test-results.xml)

#### PR Quality (`pr-quality.yml`)

Vérifie :

1. Description PR ≥ 20 caractères
2. Au moins un reviewer/assignee
3. Taille PR raisonnable (≤ 60 fichiers, ≤ 3000 changements)
4. Label `skip-pr-size-check` pour forcer si nécessaire

#### CodeQL

Analyse de sécurité automatique du code

### 🔧 Configuration locale

#### 1. Installer les dépendances CI

```bash
pip install -r requirements-ci.txt
```

#### 2. Activer le git hook automatique

Le hook `.git/hooks/pre-push` est déjà configuré. Il s'exécute automatiquement avant chaque `git push`.

Pour désactiver temporairement :

```bash
git push --no-verify  # Skip le hook
```

#### 3. Configurer pre-commit (optionnel, plus strict)

```bash
pip install pre-commit
pre-commit install
```

Créez `.pre-commit-config.yaml` :

```yaml
repos:
  - repo: https://github.com/psf/black
    rev: 24.1.0
    hooks:
      - id: black
        language_version: python3.11

  - repo: https://github.com/pycqa/flake8
    rev: 7.0.0
    hooks:
      - id: flake8
        args: [--max-line-length=88, --extend-ignore=E203, W503]

  - repo: local
    hooks:
      - id: pytest-check
        name: pytest-check
        entry: pytest
        language: system
        pass_filenames: false
        always_run: true
```

### 🐛 Déboguer les échecs CI

#### Échec "CI / tests"

```bash
# Reproduire localement
pytest -v --cov=src --cov-report=term-missing

# Voir les logs détaillés
pytest -vv --tb=long
```

#### Échec "PR Quality / checks"

Vérifiez :

1. **Description PR** : Ajoutez au moins 20 caractères dans la description
2. **Reviewer** : Assignez-vous ou demandez un review
3. **Taille** :
   - Si vraiment nécessaire, ajoutez le label `skip-pr-size-check`
   - Sinon, divisez la PR en plusieurs plus petites

#### Simuler GitHub Actions localement (avancé)

```bash
# Installer act (https://github.com/nektos/act)
curl https://raw.githubusercontent.com/nektos/act/master/install.sh | sudo bash

# Exécuter le workflow CI localement
act pull_request -j tests

# Exécuter tous les workflows
act pull_request
```

### 📊 Couverture de tests

Objectif : ≥ 80% de couverture

```bash
# Générer rapport HTML
pytest --cov=src --cov-report=html

# Ouvrir dans le navigateur
xdg-open htmlcov/index.html
```

### 🚨 Forcer un push (urgence uniquement)

Si vous devez absolument pusher malgré les checks :

```bash
# Skip le git hook local
git push --no-verify

# Ajoutez le label "skip-pr-size-check" dans la PR si nécessaire
```

**⚠️ Attention** : Les checks CI continueront de s'exécuter sur GitHub. Corrigez les erreurs dès que possible.

### 📝 Exemples de messages de commit

```bash
# Fonctionnalité
feat: add vision-based category detection with Ollama llava

# Correction
fix: handle missing thumbnail gracefully with 3-level fallback

# Tests
test: add comprehensive unit tests for audio language detection

# Documentation
docs: update CONTRIBUTING with pre-push verification guide

# Refactoring
refactor: extract thumbnail generation into dedicated function
```

### 🔗 Ressources

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [pytest Documentation](https://docs.pytest.org/)
- [flake8 Documentation](https://flake8.pycqa.org/)
- [black Documentation](https://black.readthedocs.io/)
