#!/usr/bin/env python3
"""
Lanceur pour l'interface web de monitoring
Usage: python monitor.py [--host HOST] [--port PORT] [--queue-dir DIR] [--archive-dir DIR]
"""

import argparse
import sys
from pathlib import Path

# Ajouter le répertoire src au path pour les imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.web_monitor import run_server  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="YouTube Automation Web Monitor")
    parser.add_argument(
        "--host", default="127.0.0.1", help="Host à écouter (défaut: 127.0.0.1)"
    )
    parser.add_argument(
        "--port", type=int, default=8000, help="Port à écouter (défaut: 8000)"
    )
    parser.add_argument(
        "--queue-dir", default="./queue", help="Répertoire des tâches en attente"
    )
    parser.add_argument(
        "--archive-dir",
        default="./queue_archive",
        help="Répertoire des tâches archivées",
    )

    args = parser.parse_args()
    # Créer les répertoires s'ils n'existent pas
    Path(args.queue_dir).mkdir(exist_ok=True)
    Path(args.archive_dir).mkdir(exist_ok=True)
    print("🎯 YouTube Automation Monitor")
    print("=" * 40)
    print(f"Queue: {args.queue_dir}")
    print(f"Archive: {args.archive_dir}")
    print(f"URL: http://{args.host}:{args.port}")
    print("=" * 40)
    try:
        run_server(args.queue_dir, args.archive_dir, args.host, args.port)
    except KeyboardInterrupt:
        print("\n👋 Arrêt du serveur...")
    except Exception as e:
        print(f"❌ Erreur: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
