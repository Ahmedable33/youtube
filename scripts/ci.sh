#!/usr/bin/env bash
set -euo pipefail

MODE=${1:-all}

echo "[CI] Mode: ${MODE}"
echo "[CI] Python: $(python --version)"
echo "[CI] Pip: $(pip --version)"

run_lint() {
  if ! command -v pre-commit >/dev/null 2>&1; then
    echo "[CI] pre-commit not installed; skipping lint hooks"
    return 0
  fi
  # Ensure Git can operate on a bind-mounted repo (avoid 'dubious ownership')
  if [ -d .git ]; then
    git config --global --add safe.directory /app || true
    if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
      echo "[CI] Running pre-commit (skip pytest hook to avoid duplicate test runs)"
      if ! SKIP=pytest pre-commit run --all-files; then
        echo "[CI] pre-commit reported issues; re-running after auto-fixes"
        SKIP=pytest pre-commit run --all-files || (echo "[CI] pre-commit failed after retry" && exit 1)
      fi
    else
      echo "[CI] Not inside a Git work tree; skipping pre-commit"
    fi
  else
    echo "[CI] .git directory not found; skipping pre-commit"
  fi
}

run_unit() {
  if [ -d tests/unit ]; then
    echo "[CI] Running unit tests"
    pytest -q --maxfail=1 --disable-warnings tests/unit || (echo "[CI] unit tests failed" && exit 1)
  else
    echo "[CI] No tests/unit directory"
  fi
}

run_integration() {
  if [ -d tests/integration ]; then
    echo "[CI] Running integration tests"
    pytest -q --maxfail=1 --disable-warnings tests/integration || (echo "[CI] integration tests failed" && exit 1)
  else
    echo "[CI] No tests/integration directory"
  fi
}

case "$MODE" in
  lint)
    run_lint
    ;;
  unit)
    run_unit
    ;;
  integration)
    run_integration
    ;;
  all|*)
    run_lint
    run_unit
    run_integration
    ;;
esac

echo "[CI] Completed: ${MODE}"
