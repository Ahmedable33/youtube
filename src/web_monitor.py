"""
Interface web de monitoring pour YouTube automation
Dashboard temps réel avec FastAPI et WebSocket
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any
import shutil

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn

log = logging.getLogger(__name__)


class TaskMonitor:
    """Gestionnaire de monitoring des tâches"""

    def __init__(self, queue_dir: Path, archive_dir: Path):
        self.queue_dir = Path(queue_dir)
        self.archive_dir = Path(archive_dir)
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        """Ajouter une nouvelle connexion WebSocket"""
        await websocket.accept()
        self.active_connections.append(websocket)
        log.info(f"Nouvelle connexion WebSocket: {len(self.active_connections)} total")

    def disconnect(self, websocket: WebSocket):
        """Supprimer une connexion WebSocket"""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            log.info(f"Connexion fermée: {len(self.active_connections)} restantes")

    async def broadcast(self, message: Dict[str, Any]):
        """Diffuser un message à toutes les connexions actives"""
        if not self.active_connections:
            return

        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                log.warning(f"Erreur envoi WebSocket: {e}")
                disconnected.append(connection)

        # Nettoyer les connexions fermées
        for conn in disconnected:
            self.disconnect(conn)

    def get_pending_tasks(self) -> List[Dict[str, Any]]:
        """Récupérer toutes les tâches en attente"""
        tasks = []
        if not self.queue_dir.exists():
            return tasks

        for task_file in self.queue_dir.glob("task_*.json"):
            try:
                with open(task_file, "r", encoding="utf-8") as f:
                    task_data = json.load(f)
                    task_data["file_path"] = str(task_file)
                    task_data["file_name"] = task_file.name
                    tasks.append(task_data)
            except Exception as e:
                log.error(f"Erreur lecture tâche {task_file}: {e}")

        # Trier par timestamp (plus récent en premier)
        tasks.sort(key=lambda x: x.get("received_at", ""), reverse=True)
        return tasks

    def get_archived_tasks(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Récupérer les tâches archivées (historique)"""
        tasks = []
        if not self.archive_dir.exists():
            return tasks

        for task_file in self.archive_dir.glob("task_*.json"):
            try:
                with open(task_file, "r", encoding="utf-8") as f:
                    task_data = json.load(f)
                    task_data["file_path"] = str(task_file)
                    task_data["file_name"] = task_file.name
                    tasks.append(task_data)
            except Exception as e:
                log.error(f"Erreur lecture archive {task_file}: {e}")

        # Trier par timestamp et limiter
        tasks.sort(key=lambda x: x.get("received_at", ""), reverse=True)
        return tasks[:limit]

    def get_task_stats(self) -> Dict[str, Any]:
        """Calculer les statistiques des tâches"""
        pending_tasks = self.get_pending_tasks()
        archived_tasks = self.get_archived_tasks(
            100
        )  # Plus large échantillon pour stats

        # Compter par statut
        status_counts = {}
        for task in pending_tasks:
            status = task.get("status", "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1

        for task in archived_tasks:
            status = task.get("status", "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1

        # Statistiques temporelles (dernières 24h)
        now = datetime.now()
        recent_tasks = []
        for task in archived_tasks:
            try:
                received_at = datetime.fromisoformat(
                    task.get("received_at", "").replace("Z", "+00:00")
                )
                if (now - received_at).total_seconds() < 86400:  # 24h
                    recent_tasks.append(task)
            except Exception:
                pass

        return {
            "total_pending": len(pending_tasks),
            "total_archived": len(archived_tasks),
            "status_counts": status_counts,
            "recent_24h": len(recent_tasks),
            "success_rate": self._calculate_success_rate(archived_tasks),
        }

    def _calculate_success_rate(self, tasks: List[Dict]) -> float:
        """Calculer le taux de succès"""
        if not tasks:
            return 0.0

        success_count = sum(1 for task in tasks if task.get("status") == "done")
        return round((success_count / len(tasks)) * 100, 1)

    async def retry_task(self, task_file: str) -> bool:
        """Relancer une tâche"""
        try:
            # Chercher dans les archives
            archive_path = self.archive_dir / task_file
            if not archive_path.exists():
                return False

            # Charger la tâche
            with open(archive_path, "r", encoding="utf-8") as f:
                task_data = json.load(f)

            # Réinitialiser le statut
            task_data["status"] = "pending"
            task_data["retried_at"] = datetime.now().isoformat()
            if "error" in task_data:
                del task_data["error"]
            if "youtube_id" in task_data:
                del task_data["youtube_id"]

            # Créer nouvelle tâche dans la queue
            new_task_path = self.queue_dir / task_file
            with open(new_task_path, "w", encoding="utf-8") as f:
                json.dump(task_data, f, ensure_ascii=False, indent=2)

            log.info(f"Tâche relancée: {task_file}")

            # Notifier via WebSocket
            await self.broadcast(
                {
                    "type": "task_retried",
                    "task_file": task_file,
                    "timestamp": datetime.now().isoformat(),
                }
            )

            return True

        except Exception as e:
            log.error(f"Erreur retry tâche {task_file}: {e}")
            return False

    async def cancel_task(self, task_file: str) -> bool:
        """Annuler une tâche en attente"""
        try:
            task_path = self.queue_dir / task_file
            if not task_path.exists():
                return False

            # Charger et modifier la tâche
            with open(task_path, "r", encoding="utf-8") as f:
                task_data = json.load(f)

            task_data["status"] = "cancelled"
            task_data["cancelled_at"] = datetime.now().isoformat()

            # Sauvegarder et archiver
            with open(task_path, "w", encoding="utf-8") as f:
                json.dump(task_data, f, ensure_ascii=False, indent=2)

            archive_path = self.archive_dir / task_file
            shutil.move(str(task_path), str(archive_path))

            log.info(f"Tâche annulée: {task_file}")

            # Notifier via WebSocket
            await self.broadcast(
                {
                    "type": "task_cancelled",
                    "task_file": task_file,
                    "timestamp": datetime.now().isoformat(),
                }
            )

            return True

        except Exception as e:
            log.error(f"Erreur cancel tâche {task_file}: {e}")
            return False

    async def delete_task(self, task_file: str) -> bool:
        """Supprimer définitivement une tâche archivée"""
        try:
            archive_path = self.archive_dir / task_file
            if not archive_path.exists():
                return False

            archive_path.unlink()
            log.info(f"Tâche supprimée: {task_file}")

            # Notifier via WebSocket
            await self.broadcast(
                {
                    "type": "task_deleted",
                    "task_file": task_file,
                    "timestamp": datetime.now().isoformat(),
                }
            )

            return True

        except Exception as e:
            log.error(f"Erreur suppression tâche {task_file}: {e}")
            return False


def create_app(queue_dir: str, archive_dir: str) -> FastAPI:
    """Créer l'application FastAPI"""

    app = FastAPI(
        title="YouTube Automation Monitor",
        description="Dashboard de monitoring temps réel",
        version="1.0.0",
    )

    # Initialiser le monitor
    monitor = TaskMonitor(queue_dir, archive_dir)

    # Templates et fichiers statiques
    templates_dir = Path(__file__).parent.parent / "web" / "templates"
    static_dir = Path(__file__).parent.parent / "web" / "static"

    templates_dir.mkdir(parents=True, exist_ok=True)
    static_dir.mkdir(parents=True, exist_ok=True)

    templates = Jinja2Templates(directory=str(templates_dir))
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        """Page principale du dashboard"""
        return templates.TemplateResponse("dashboard.html", {"request": request})

    @app.get("/api/stats")
    async def get_stats():
        """API: Statistiques des tâches"""
        return monitor.get_task_stats()

    @app.get("/api/tasks/pending")
    async def get_pending_tasks():
        """API: Tâches en attente"""
        return monitor.get_pending_tasks()

    @app.get("/api/tasks/archived")
    async def get_archived_tasks(limit: int = 50):
        """API: Historique des tâches"""
        return monitor.get_archived_tasks(limit)

    @app.post("/api/tasks/{task_file}/retry")
    async def retry_task(task_file: str):
        """API: Relancer une tâche"""
        success = await monitor.retry_task(task_file)
        if success:
            return {"status": "success", "message": f"Tâche {task_file} relancée"}
        else:
            raise HTTPException(status_code=404, detail="Tâche introuvable")

    @app.post("/api/tasks/{task_file}/cancel")
    async def cancel_task(task_file: str):
        """API: Annuler une tâche"""
        success = await monitor.cancel_task(task_file)
        if success:
            return {"status": "success", "message": f"Tâche {task_file} annulée"}
        else:
            raise HTTPException(status_code=404, detail="Tâche introuvable")

    @app.delete("/api/tasks/{task_file}")
    async def delete_task(task_file: str):
        """API: Supprimer une tâche"""
        success = await monitor.delete_task(task_file)
        if success:
            return {"status": "success", "message": f"Tâche {task_file} supprimée"}
        else:
            raise HTTPException(status_code=404, detail="Tâche introuvable")

    @app.get("/meta.json")
    async def meta():
        return {
            "app": "YouTube Automation Monitor",
            "version": "1.0.0",
            "time": datetime.now().isoformat(),
            "stats": monitor.get_task_stats(),
        }

    @app.get("/favicon.ico")
    async def favicon():
        return Response(status_code=204)

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket pour mises à jour temps réel"""
        await monitor.connect(websocket)
        try:
            # Envoyer les données initiales
            await websocket.send_json(
                {
                    "type": "initial_data",
                    "stats": monitor.get_task_stats(),
                    "pending_tasks": monitor.get_pending_tasks(),
                    "timestamp": datetime.now().isoformat(),
                }
            )

            # Boucle de mise à jour périodique
            while True:
                await asyncio.sleep(5)  # Mise à jour toutes les 5 secondes
                await websocket.send_json(
                    {
                        "type": "update",
                        "stats": monitor.get_task_stats(),
                        "pending_tasks": monitor.get_pending_tasks(),
                        "timestamp": datetime.now().isoformat(),
                    }
                )

        except WebSocketDisconnect:
            monitor.disconnect(websocket)
        except Exception as e:
            log.error(f"Erreur WebSocket: {e}")
            monitor.disconnect(websocket)

    return app


def run_server(
    queue_dir: str, archive_dir: str, host: str = "127.0.0.1", port: int = 8000
):
    """Lancer le serveur web"""
    app = create_app(queue_dir, archive_dir)

    print("🚀 Démarrage du serveur de monitoring...")
    print(f"📊 Dashboard: http://{host}:{port}")
    print(f"📁 Queue: {queue_dir}")
    print(f"📁 Archive: {archive_dir}")

    uvicorn.run(app, host=host, port=port, log_level="info", access_log=True)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python web_monitor.py <queue_dir> <archive_dir> [host] [port]")
        sys.exit(1)

    queue_dir = sys.argv[1]
    archive_dir = sys.argv[2]
    host = sys.argv[3] if len(sys.argv) > 3 else "127.0.0.1"
    port = int(sys.argv[4]) if len(sys.argv) > 4 else 8000

    run_server(queue_dir, archive_dir, host, port)
