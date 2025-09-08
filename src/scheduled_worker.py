"""
Worker pour traiter les tâches planifiées
Vérifie périodiquement les tâches prêtes et les déplace vers la queue normale
"""

import logging
import time
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from .scheduler import UploadScheduler, ScheduleStatus

log = logging.getLogger(__name__)

class ScheduledWorker:
    """Worker pour traiter les tâches planifiées"""
    
    def __init__(self, 
                 schedule_dir: Path,
                 queue_dir: Path,
                 archive_dir: Path,
                 check_interval: int = 60):
        self.scheduler = UploadScheduler(
            config_path=Path("config/video.yaml"),
            schedule_dir=schedule_dir
        )
        self.queue_dir = Path(queue_dir)
        self.archive_dir = Path(archive_dir)
        self.check_interval = check_interval
        self.running = False
        
        # Créer les répertoires
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
    
    def start(self):
        """Démarrer le worker en mode continu"""
        self.running = True
        log.info("Démarrage du scheduled worker")
        
        while self.running:
            try:
                self.process_ready_tasks()
                self.cleanup_old_tasks()
                time.sleep(self.check_interval)
            except KeyboardInterrupt:
                log.info("Arrêt demandé par l'utilisateur")
                break
            except Exception as e:
                log.error(f"Erreur dans le scheduled worker: {e}")
                time.sleep(self.check_interval)
        
        log.info("Scheduled worker arrêté")
    
    def stop(self):
        """Arrêter le worker"""
        self.running = False
    
    def process_ready_tasks(self):
        """Traiter les tâches prêtes à être exécutées"""
        ready_tasks = self.scheduler.get_ready_tasks()
        
        if not ready_tasks:
            return
        
        log.info(f"Traitement de {len(ready_tasks)} tâches prêtes")
        
        for task in ready_tasks:
            try:
                self.move_task_to_queue(task)
            except Exception as e:
                log.error(f"Erreur traitement tâche {task.task_id}: {e}")
                self.scheduler.mark_task_failed(task.task_id, retry=True)
    
    def move_task_to_queue(self, scheduled_task):
        """Déplacer une tâche planifiée vers la queue normale"""
        original_path = scheduled_task.original_task_path
        
        if not original_path.exists():
            log.error(f"Tâche originale introuvable: {original_path}")
            self.scheduler.mark_task_failed(scheduled_task.task_id, retry=False)
            return
        
        # Charger la tâche originale
        try:
            with open(original_path, 'r', encoding='utf-8') as f:
                task_data = json.load(f)
        except Exception as e:
            log.error(f"Impossible de lire la tâche {original_path}: {e}")
            self.scheduler.mark_task_failed(scheduled_task.task_id, retry=False)
            return
        
        # Mettre à jour les métadonnées de planification
        task_data["scheduled_task_id"] = scheduled_task.task_id
        task_data["scheduled_time"] = scheduled_task.scheduled_time.isoformat()
        task_data["moved_to_queue_at"] = datetime.now().isoformat()
        
        # Créer le nouveau fichier dans la queue
        new_task_path = self.queue_dir / f"scheduled_{scheduled_task.task_id}.json"
        
        try:
            with open(new_task_path, 'w', encoding='utf-8') as f:
                json.dump(task_data, f, ensure_ascii=False, indent=2)
            
            # Marquer comme en cours de traitement
            self.scheduler.mark_task_processing(scheduled_task.task_id)
            
            log.info(f"Tâche déplacée vers la queue: {scheduled_task.task_id}")
            
        except Exception as e:
            log.error(f"Erreur création tâche dans la queue: {e}")
            self.scheduler.mark_task_failed(scheduled_task.task_id, retry=True)
    
    def cleanup_old_tasks(self):
        """Nettoyer les anciennes tâches (appelé périodiquement)"""
        # Nettoyer toutes les heures seulement
        if datetime.now().minute == 0:
            cleaned = self.scheduler.cleanup_old_tasks(days_old=7)
            if cleaned > 0:
                log.info(f"Nettoyage: {cleaned} anciennes tâches supprimées")
    
    def get_stats(self):
        """Obtenir les statistiques du scheduler"""
        return self.scheduler.get_schedule_stats()

def run_scheduled_worker(schedule_dir: str, queue_dir: str, archive_dir: str, check_interval: int = 60):
    """Point d'entrée pour lancer le scheduled worker"""
    worker = ScheduledWorker(
        schedule_dir=Path(schedule_dir),
        queue_dir=Path(queue_dir),
        archive_dir=Path(archive_dir),
        check_interval=check_interval
    )
    
    try:
        worker.start()
    except KeyboardInterrupt:
        worker.stop()

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 4:
        print("Usage: python scheduled_worker.py <schedule_dir> <queue_dir> <archive_dir> [check_interval]")
        sys.exit(1)
    
    schedule_dir = sys.argv[1]
    queue_dir = sys.argv[2]
    archive_dir = sys.argv[3]
    check_interval = int(sys.argv[4]) if len(sys.argv) > 4 else 60
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )
    
    run_scheduled_worker(schedule_dir, queue_dir, archive_dir, check_interval)
