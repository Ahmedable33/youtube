#!/usr/bin/env python3
"""
Démon pour le scheduler de tâches planifiées
Usage: python scheduler_daemon.py [--schedule-dir DIR] [--queue-dir DIR] [--archive-dir DIR] [--interval SECONDS]
"""

import argparse
import sys
from pathlib import Path

# Ajouter le répertoire src au path pour les imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.scheduled_worker import run_scheduled_worker


def main():
    parser = argparse.ArgumentParser(description="YouTube Automation Scheduler Daemon")
    parser.add_argument(
        "--schedule-dir", default="./schedule", help="Répertoire des tâches planifiées"
    )
    parser.add_argument(
        "--queue-dir", default="./queue", help="Répertoire de la queue normale"
    )
    parser.add_argument(
        "--archive-dir", default="./queue_archive", help="Répertoire des archives"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Intervalle de vérification en secondes (défaut: 60)",
    )

    args = parser.parse_args()

    # Créer les répertoires s'ils n'existent pas
    Path(args.schedule_dir).mkdir(exist_ok=True)
    Path(args.queue_dir).mkdir(exist_ok=True)
    Path(args.archive_dir).mkdir(exist_ok=True)

    print("📅 YouTube Automation Scheduler")
    print("=" * 40)
    print(f"Schedule: {args.schedule_dir}")
    print(f"Queue: {args.queue_dir}")
    print(f"Archive: {args.archive_dir}")
    print(f"Intervalle: {args.interval}s")
    print("=" * 40)

    try:
        run_scheduled_worker(
            args.schedule_dir, args.queue_dir, args.archive_dir, args.interval
        )
    except KeyboardInterrupt:
        print("\n👋 Arrêt du scheduler...")
    except Exception as e:
        print(f"❌ Erreur: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
