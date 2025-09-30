#!/usr/bin/env bash
# Script de vérification pre-push pour simuler les checks CI en local
# Usage: ./scripts/pre-push-checks.sh

set -e

echo "🔍 Vérifications pre-push (simule CI/CD)..."
echo ""

# Couleurs pour output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

FAILED=0

# Fonction pour afficher résultat
check_result() {
    if [ $1 -eq 0 ]; then
        echo -e "${GREEN}✅ $2${NC}"
    else
        echo -e "${RED}❌ $2${NC}"
        FAILED=1
    fi
}

# 1. Vérifier que nous sommes dans un virtualenv
echo "📦 Vérification environnement virtuel..."
if [ -z "$VIRTUAL_ENV" ]; then
    echo -e "${YELLOW}⚠️  Virtualenv non activé. Activation de .venv...${NC}"
    if [ -f ".venv/bin/activate" ]; then
        source .venv/bin/activate
    else
        echo -e "${RED}❌ .venv introuvable. Créez-le avec: python -m venv .venv${NC}"
        exit 1
    fi
fi
check_result $? "Environnement virtuel"
echo ""

# 2. Installer les dépendances CI si nécessaires
echo "📥 Vérification des dépendances CI..."
pip list | grep -q pytest || {
    echo "Installation des dépendances de test..."
    pip install -r requirements-ci.txt -q
}
check_result $? "Dépendances CI"
echo ""

# 3. Linting avec flake8
echo "🔎 Linting avec flake8..."
flake8 src/ tests/ --max-line-length=88 --extend-ignore=E203,W503 2>&1
FLAKE8_EXIT=$?
check_result $FLAKE8_EXIT "Flake8 linting"
echo ""

# 4. Linting avec black (check only)
echo "🎨 Vérification formatage avec black..."
black --check src/ tests/ 2>&1 || {
    echo -e "${YELLOW}⚠️  Formatage incorrect. Exécutez: black src/ tests/${NC}"
}
BLACK_EXIT=$?
check_result $BLACK_EXIT "Black formatting"
echo ""

# 5. Tests avec pytest
echo "🧪 Exécution des tests..."
pytest -v --cov=src --cov-report=term-missing --cov-report=html 2>&1
PYTEST_EXIT=$?
check_result $PYTEST_EXIT "Tests pytest"
echo ""

# 6. Vérification taille PR (simulé)
echo "📏 Vérification taille des changements..."
CHANGED_FILES=$(git diff --cached --name-only | wc -l)
ADDITIONS=$(git diff --cached --numstat | awk '{sum+=$1} END {print sum}')
DELETIONS=$(git diff --cached --numstat | awk '{sum+=$2} END {print sum}')
TOTAL_CHANGES=$((ADDITIONS + DELETIONS))

echo "   Fichiers modifiés: $CHANGED_FILES"
echo "   Additions: $ADDITIONS"
echo "   Deletions: $DELETIONS"
echo "   Total changements: $TOTAL_CHANGES"

if [ $CHANGED_FILES -gt 60 ]; then
    echo -e "${YELLOW}⚠️  Plus de 60 fichiers modifiés. Considérez diviser la PR.${NC}"
fi

if [ $TOTAL_CHANGES -gt 3000 ]; then
    echo -e "${YELLOW}⚠️  Plus de 3000 changements. Considérez diviser la PR.${NC}"
fi
check_result 0 "Taille PR"
echo ""

# 7. Vérifier que les fichiers sensibles ne sont pas commités
echo "🔐 Vérification fichiers sensibles..."
SENSITIVE_FILES=$(git diff --cached --name-only | grep -E "(secret|credential|token|\.env$|api.*key)" || true)
if [ -n "$SENSITIVE_FILES" ]; then
    echo -e "${RED}❌ Fichiers sensibles détectés:${NC}"
    echo "$SENSITIVE_FILES"
    FAILED=1
else
    check_result 0 "Pas de fichiers sensibles"
fi
echo ""

# Résumé
echo "════════════════════════════════════════"
if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✅ Tous les checks ont réussi !${NC}"
    echo "Vous pouvez pusher en toute sécurité."
    exit 0
else
    echo -e "${RED}❌ Certains checks ont échoué.${NC}"
    echo "Corrigez les erreurs avant de pusher."
    exit 1
fi
