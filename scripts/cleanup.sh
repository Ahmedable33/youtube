#!/usr/bin/env sh
set -eu

# Daily cleanup: delete files older than 15 days
# Targets:
# - queue_archive/ archived tasks JSON
# - inputs/telegram/ downloaded inputs

DAYS="15"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

log() { printf "%s %s\n" "[cleanup]" "$*"; }

log "start $(date -Is 2>/dev/null || date)"

# queue_archive
if [ -d "queue_archive" ]; then
  find queue_archive -type f -mtime +"$DAYS" -print -delete || true
fi

# inputs/telegram
if [ -d "inputs/telegram" ]; then
  find inputs/telegram -type f -mtime +"$DAYS" -print -delete || true
fi

log "done $(date -Is 2>/dev/null || date)"
