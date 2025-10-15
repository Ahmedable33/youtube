# 🔧 Comment corriger les checks PR échoués

## Problèmes actuels détectés

### ❌ CI / tests - Failing

**Cause probable** : Erreurs de linting (lignes trop longues E501)

#### Solution rapide

```bash
# Corriger automatiquement les lignes trop longues avec black
black src/ tests/

# Vérifier
flake8 src/ tests/ --max-line-length=88 --extend-ignore=E203,W503

# Ou ignorer E501 temporairement (pas recommandé long terme)
flake8 src/ tests/ --extend-ignore=E203,W503,E501
```

### ❌ PR Quality / checks - Failing

**Causes possibles** :

1. Description PR trop courte (< 20 caractères)
2. Pas de reviewer/assignee
3. PR trop volumineuse (> 60 fichiers ou > 3000 changements)

#### Solutions

**1. Description PR trop courte**

- Éditez la PR sur GitHub
- Ajoutez une description détaillée (minimum 20 caractères)

**2. Pas de reviewer**

- Assignez-vous comme "Assignee" ou demandez un review

**3. PR trop volumineuse**

- Ajouter le label `skip-pr-size-check` sur GitHub si justifié

## 🚀 Workflow de correction complet

### 1. Corriger en local

```bash
# Se positionner sur la branche
cd /home/hamux/Projets/youtube
git checkout feat/public-privacy-vision-category-infallible-thumbnail

# Formater le code
black src/ tests/

# Vérifier les tests
pytest -q

# Commit les corrections
git add -A
git commit -m "fix: format code with black to pass CI linting"
git push
```

### 2. Corriger la PR sur GitHub

1. **Éditer la description** : Minimum 20 caractères
2. **Assigner un reviewer** : Section "Reviewers" à droite
3. **Ajouter label si nécessaire** : `skip-pr-size-check`

## 📋 Checklist de vérification

- [ ] `black src/ tests/` exécuté
- [ ] `pytest -q` passe (57/57 tests)
- [ ] Description PR >= 20 caractères
- [ ] Reviewer ou assignee défini

## 🎯 Script de vérification automatique

```bash
./scripts/pre-push-checks.sh
```
