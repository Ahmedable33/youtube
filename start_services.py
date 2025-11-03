#!/usr/bin/env python3
"""
Lanceur unifié des services:
- Ollama (si provider SEO = ollama)
- Bot Telegram d'ingestion
- Scheduler de tâches planifiées
- Web Monitor (FastAPI)
- Watcher de la queue: lance automatiquement le worker quand une tâche est créée

Usage:
  python start_services.py \
    --sources config/sources.yaml \
    --config config/video.yaml \
    --queue-dir queue \
    --archive-dir queue_archive \
    --schedule-dir schedule \
    --monitor-host 127.0.0.1 \
    --monitor-port 8000 \
    --log-level INFO \
    --auto-restart (activé par défaut) ou --no-auto-restart pour désactiver

Arrêt: Ctrl+C (tous les sous-processus seront arrêtés proprement si possible)
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional, List

try:
    import yaml  # type: ignore
except Exception:
    yaml = None

PROJECT_ROOT = Path(__file__).parent.resolve()
PYTHON = sys.executable  # utilise l'interpréteur courant (venv recommandé)


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    if yaml is None:
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _is_ollama_up(host: str) -> bool:
    # Vérifier via HTTP si Ollama répond (endpoint /api/tags)
    try:
        import http.client
        from urllib.parse import urlparse

        u = urlparse(host)
        netloc = u.netloc or u.path  # supporte host sans schéma
        scheme = u.scheme or "http"
        if ":" in netloc:
            hostname, port = netloc.split(":", 1)
            port = int(port)
        else:
            hostname, port = netloc, 80 if scheme == "http" else 443
        conn = http.client.HTTPConnection(hostname, port, timeout=1.5)
        conn.request("GET", "/api/tags")
        resp = conn.getresponse()
        return resp.status < 500
    except Exception:
        return False


def _which(cmd: str) -> Optional[str]:
    from shutil import which

    return which(cmd)


def _write_file_from_env(json_var: str, b64_var: str, dest: Path) -> None:
    data_b64 = os.environ.get(b64_var)
    content = None
    if data_b64:
        try:
            import base64

            content = base64.b64decode(data_b64).decode("utf-8")
        except Exception:
            content = None
    if content is None:
        content = os.environ.get(json_var)
    if content:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")


def _ensure_oauth_files_from_env() -> None:
    client_dest = PROJECT_ROOT / "config" / "client_secret.json"
    token_dest = PROJECT_ROOT / "config" / "token.json"
    _write_file_from_env("YT_CLIENT_SECRET_JSON", "YT_CLIENT_SECRET_B64", client_dest)
    _write_file_from_env("YT_TOKEN_JSON", "YT_TOKEN_B64", token_dest)


def start_ollama_if_needed(video_cfg: dict) -> Optional[subprocess.Popen]:
    seo = (video_cfg or {}).get("seo") or {}
    provider = str(seo.get("provider") or "").lower()
    if provider != "ollama":
        return None
    host = str(
        seo.get("host") or os.environ.get("OLLAMA_HOST") or "http://localhost:11434"
    )

    if _is_ollama_up(host):
        print(f"✅ Ollama déjà disponible sur {host}")
        return None

    if not _which("ollama"):
        print(
            "⚠️  'ollama' introuvable dans le PATH. Installez Ollama ou ajustez la config SEO."
        )
        return None

    print("🚀 Démarrage d'Ollama (ollama serve)…")
    # Lance ollama serve en arrière-plan
    try:
        proc = subprocess.Popen(["ollama", "serve"], cwd=str(PROJECT_ROOT))
        # Attendre un court instant et re-tester
        for _ in range(10):
            time.sleep(0.8)
            if _is_ollama_up(host):
                print(f"✅ Ollama prêt sur {host}")
                break
        return proc
    except Exception as e:
        print(f"❌ Impossible de démarrer Ollama: {e}")
        return None


def start_process(cmd: List[str], name: str) -> subprocess.Popen:
    print(f"▶️  Lancement {name}: {' '.join(cmd)}")
    return subprocess.Popen(cmd, cwd=str(PROJECT_ROOT))


def run_worker_once(
    queue_dir: str, archive_dir: str, config_path: Optional[str], log_level: str
) -> int:
    cmd = [
        PYTHON,
        "main.py",
        "worker",
        "--queue-dir",
        queue_dir,
        "--archive-dir",
        archive_dir,
        "--log-level",
        log_level,
    ]
    if config_path:
        cmd.extend(["--config", config_path])
    print("⚙️  Démarrage worker (one-shot)…")
    return subprocess.call(cmd, cwd=str(PROJECT_ROOT))


def queue_watcher(
    queue_dir: str,
    archive_dir: str,
    config_path: Optional[str],
    log_level: str,
    stop_event: threading.Event,
):
    """Surveille queue_dir et lance le worker dès qu'une tâche apparaît.
    Évite de lancer plusieurs workers en parallèle.
    """
    q = Path(queue_dir)
    q.mkdir(parents=True, exist_ok=True)
    worker_running = False

    while not stop_event.is_set():
        try:
            # Y a-t-il des tâches pending ? (normales ou issues du scheduler)
            has_task = any(q.glob("task_*.json")) or any(q.glob("scheduled_*.json"))
            if has_task and not worker_running:
                worker_running = True
                rc = run_worker_once(queue_dir, archive_dir, config_path, log_level)
                print(f"✅ Worker terminé (code {rc}).")
                worker_running = False
            time.sleep(2.0)
        except Exception as e:
            print(f"❗ Watcher erreur: {e}")
            time.sleep(3.0)


def main():
    ap = argparse.ArgumentParser(
        description="Lance tous les services et déclenche le worker à la création de tâche"
    )
    ap.add_argument(
        "--sources",
        default="config/sources.yaml",
        help="Chemin sources.yaml pour le bot Telegram",
    )
    ap.add_argument(
        "--config", default="config/video.yaml", help="Chemin video.yaml pour le worker"
    )
    ap.add_argument(
        "--queue-dir", default="queue", help="Répertoire des tâches en attente"
    )
    ap.add_argument(
        "--archive-dir", default="queue_archive", help="Répertoire d'archives"
    )
    ap.add_argument(
        "--schedule-dir", default="schedule", help="Répertoire des tâches planifiées"
    )
    ap.add_argument("--monitor-host", default="127.0.0.1", help="Host du monitor web")
    ap.add_argument(
        "--monitor-port", type=int, default=8000, help="Port du monitor web"
    )
    ap.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Niveau de logs du worker",
    )
    # Auto-restart activé par défaut; possibilité de désactiver via --no-auto-restart
    ap.add_argument(
        "--auto-restart",
        dest="auto_restart",
        action="store_true",
        default=True,
        help=(
            "Relancer automatiquement les services (monitor/scheduler/bot/ollama) "
            "s'ils s'arrêtent (activé par défaut)"
        ),
    )
    ap.add_argument(
        "--no-auto-restart",
        dest="auto_restart",
        action="store_false",
        help="Désactiver le redémarrage automatique des services",
    )
    ap.add_argument(
        "--restart-backoff",
        type=float,
        default=3.0,
        help="Délai minimal (s) entre deux relances d'un même service",
    )
    args = ap.parse_args()
    if os.environ.get("LOG_LEVEL"):
        raw = (os.environ.get("LOG_LEVEL") or "").strip()
        # Sanitize values like "INFO,WARNING" or "info" -> pick first valid, uppercased
        cleaned = raw.split(",")[0].strip().upper()
        if cleaned in {"DEBUG", "INFO", "WARNING", "ERROR"}:
            args.log_level = cleaned
    _ensure_oauth_files_from_env()

    video_cfg = _read_yaml(Path(args.config))
    # Charger la configuration des sources (pour savoir si le bot Telegram doit être lancé)
    sources_path = Path(args.sources)
    sources_cfg = _read_yaml(sources_path)
    tcfg = (sources_cfg or {}).get("telegram") or {}
    # Overrides via environment (useful for Railway)
    env_enabled = os.environ.get("TELEGRAM_ENABLED")
    env_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if env_enabled is not None:
        t_enabled = str(env_enabled).strip().lower() in ("1", "true", "yes", "on")
    else:
        t_enabled = bool(tcfg.get("enabled", False))
    token = str((env_token if env_token else tcfg.get("token")) or "").strip()
    # If token provided via env and sources file missing, create a minimal one
    if token and not sources_path.exists():
        try:
            if yaml is not None:
                tmp_cfg = {"telegram": {"enabled": t_enabled, "token": token}}
                sources_path.parent.mkdir(parents=True, exist_ok=True)
                sources_path.write_text(
                    yaml.safe_dump(tmp_cfg, allow_unicode=True, sort_keys=False),
                    encoding="utf-8",
                )
            else:
                sources_path.parent.mkdir(parents=True, exist_ok=True)
                content = f"telegram:\n  enabled: {'true' if t_enabled else 'false'}\n  token: '{token}'\n"
                sources_path.write_text(content, encoding="utf-8")
        except Exception:
            pass
    token_placeholder = (not token) or token in (
        "VOTRE_BOT_TOKEN_ICI",
        "YOUR_BOT_TOKEN_HERE",
    )

    # 1) Démarrer Ollama si nécessaire
    spawned_ollama = start_ollama_if_needed(video_cfg)

    # 2) Lancer Monitor, Scheduler, Bot (processus séparés)
    procs: list[tuple[str, subprocess.Popen]] = []
    try:
        # Web monitor
        # Déterminer host/port de manière robuste (Railway fournit PORT automatiquement)
        port_env = (os.environ.get("PORT") or "").strip()
        port_val = args.monitor_port
        host_val = args.monitor_host
        if port_env:
            try:
                p = int(port_env)
                if 0 < p < 65536:
                    port_val = p
                    if args.monitor_host in ("127.0.0.1", "localhost"):
                        host_val = "0.0.0.0"
            except Exception:
                # PORT invalide: on garde les valeurs par défaut
                pass
        mon_cmd = [
            PYTHON,
            "monitor.py",
            "--host",
            host_val,
            "--port",
            str(port_val),
            "--queue-dir",
            args.queue_dir,
            "--archive-dir",
            args.archive_dir,
        ]
        procs.append(("monitor", start_process(mon_cmd, "monitor")))

        # Scheduler daemon
        sch_cmd = [
            PYTHON,
            "scheduler_daemon.py",
            "--schedule-dir",
            args.schedule_dir,
            "--queue-dir",
            args.queue_dir,
            "--archive-dir",
            args.archive_dir,
            "--interval",
            "60",
        ]
        procs.append(("scheduler", start_process(sch_cmd, "scheduler")))

        # Telegram bot (optionnel)
        start_telegram = False
        if t_enabled and not token_placeholder:
            # Lancer uniquement si activé et token valide présent
            bot_cmd = [PYTHON, "main.py", "telegram-bot", "--sources", args.sources]
            procs.append(("telegram-bot", start_process(bot_cmd, "telegram-bot")))
            start_telegram = True
        else:
            # Informer et ignorer le lancement du bot pour éviter les boucles d'erreur
            reason = "désactivé" if not t_enabled else "token manquant/placeholder"
            print(
                f"⏭️  Telegram bot ignoré ({reason}). Modifiez {args.sources} pour l'activer."
            )

        # 3) Lancer un watcher qui déclenche le worker quand des tâches apparaissent
        stop_event = threading.Event()
        t = threading.Thread(
            target=queue_watcher,
            args=(
                args.queue_dir,
                args.archive_dir,
                args.config,
                args.log_level,
                stop_event,
            ),
            name="queue-watcher",
            daemon=True,
        )
        t.start()

        print("\n🎛️  Tous les services sont lancés. Ctrl+C pour arrêter.\n")

        # Boucle principale: attendre les sous-processus ou SIGINT
        last_restart: dict[str, float] = {}
        cmd_by_name = {
            "monitor": mon_cmd,
            "scheduler": sch_cmd,
        }
        # Ajouter la commande du bot uniquement si démarré
        if "start_telegram" in locals() and start_telegram:
            cmd_by_name["telegram-bot"] = bot_cmd
        provider = str(
            ((video_cfg or {}).get("seo") or {}).get("provider") or ""
        ).lower()
        while True:
            time.sleep(1.0)
            # Surveiller les sous-processus et relancer si demandé
            for i, (name, p) in enumerate(list(procs)):
                if p.poll() is not None:
                    print(f"⚠️  Processus {name} terminé avec code {p.returncode}")
                    if args.auto_restart and name in cmd_by_name:
                        now = time.time()
                        if now - last_restart.get(name, 0.0) >= float(
                            args.restart_backoff
                        ):
                            try:
                                print(f"🔁 Relance {name}…")
                                new_p = start_process(cmd_by_name[name], name)
                                procs[i] = (name, new_p)
                                last_restart[name] = now
                            except Exception as e:
                                print(f"❌ Échec relance {name}: {e}")
                    else:
                        # Ne pas reloger en boucle les processus terminés: on les retire de la liste
                        try:
                            procs.pop(i)
                        except Exception:
                            pass

            # Surveiller Ollama si nous l'avons lancé et provider=ollama
            if (
                provider == "ollama"
                and spawned_ollama is not None
                and spawned_ollama.poll() is not None
            ):
                print("⚠️  Ollama s'est arrêté.")
                if args.auto_restart:
                    now = time.time()
                    if now - last_restart.get("ollama", 0.0) >= float(
                        args.restart_backoff
                    ):
                        print("🔁 Relance Ollama…")
                        spawned_ollama = start_ollama_if_needed(video_cfg)
                        last_restart["ollama"] = now

    except KeyboardInterrupt:
        print("\n👋 Arrêt demandé, fermeture des services…")
    finally:
        # Arrêt watcher
        try:
            stop_event.set()  # type: ignore[name-defined]
        except Exception:
            pass
        # Tuer sous-processus
        for name, p in procs:
            try:
                if p.poll() is None:
                    print(f"🛑 Arrêt {name}…")
                    if os.name == "posix":
                        p.send_signal(signal.SIGINT)
                        time.sleep(0.5)
                    p.terminate()
            except Exception:
                pass
        # Arrêter Ollama si nous l'avons lancé
        if spawned_ollama is not None:
            try:
                if spawned_ollama.poll() is None:
                    print("🛑 Arrêt Ollama…")
                    if os.name == "posix":
                        spawned_ollama.send_signal(signal.SIGINT)
                        time.sleep(0.5)
                    spawned_ollama.terminate()
            except Exception:
                pass


if __name__ == "__main__":
    main()
