"""
Système de planification d'uploads différés pour YouTube automation
Scheduler intelligent avec créneaux optimaux par jour de semaine
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytz

log = logging.getLogger(__name__)


class ScheduleStatus(Enum):
    SCHEDULED = "scheduled"
    READY = "ready"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TimeSlot:
    """Créneau horaire pour uploads"""

    start_hour: int
    start_minute: int
    end_hour: int
    end_minute: int
    priority: int = 1  # 1=haute, 2=moyenne, 3=basse

    def __post_init__(self):
        if not (0 <= self.start_hour <= 23) or not (0 <= self.end_hour <= 23):
            raise ValueError("Les heures doivent être entre 0 et 23")
        if not (0 <= self.start_minute <= 59) or not (0 <= self.end_minute <= 59):
            raise ValueError("Les minutes doivent être entre 0 et 59")

    @property
    def start_time(self) -> time:
        return time(self.start_hour, self.start_minute)

    @property
    def end_time(self) -> time:
        return time(self.end_hour, self.end_minute)

    def contains_time(self, check_time: time) -> bool:
        """Vérifie si une heure est dans ce créneau"""
        if self.start_time <= self.end_time:
            return self.start_time <= check_time <= self.end_time
        else:
            # Créneau qui traverse minuit
            return check_time >= self.start_time or check_time <= self.end_time

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start_hour": self.start_hour,
            "start_minute": self.start_minute,
            "end_hour": self.end_hour,
            "end_minute": self.end_minute,
            "priority": self.priority,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TimeSlot":
        return cls(**data)


@dataclass
class ScheduledTask:
    """Tâche planifiée"""

    task_id: str
    scheduled_time: datetime
    original_task_path: Path
    status: ScheduleStatus = ScheduleStatus.SCHEDULED
    created_at: Optional[datetime] = None
    attempts: int = 0
    max_attempts: int = 3

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "scheduled_time": self.scheduled_time.isoformat(),
            "original_task_path": str(self.original_task_path),
            "status": self.status.value,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScheduledTask":
        return cls(
            task_id=data["task_id"],
            scheduled_time=datetime.fromisoformat(data["scheduled_time"]),
            original_task_path=Path(data["original_task_path"]),
            status=ScheduleStatus(data["status"]),
            created_at=(
                datetime.fromisoformat(data["created_at"])
                if data.get("created_at")
                else None
            ),
            attempts=data.get("attempts", 0),
            max_attempts=data.get("max_attempts", 3),
        )


class UploadScheduler:
    """Gestionnaire de planification d'uploads"""

    def __init__(
        self, config_path: Path, schedule_dir: Path, timezone: str = "Europe/Paris"
    ):
        self.config_path = Path(config_path)
        self.schedule_dir = Path(schedule_dir)
        self.timezone = pytz.timezone(timezone)

        # Créer les répertoires
        self.schedule_dir.mkdir(parents=True, exist_ok=True)

        # Fichiers de données
        self.schedule_file = self.schedule_dir / "scheduled_tasks.json"
        self.slots_file = self.schedule_dir / "time_slots.json"

        # Charger la configuration
        self.load_config()
        self.load_scheduled_tasks()

    def load_config(self):
        """Charger la configuration des créneaux"""
        if self.slots_file.exists():
            try:
                with open(self.slots_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.time_slots = {}
                    for day, slots in data.items():
                        self.time_slots[day] = [
                            TimeSlot.from_dict(slot) for slot in slots
                        ]
            except Exception as e:
                log.error(f"Erreur chargement créneaux: {e}")
                self.time_slots = self._default_time_slots()
        else:
            self.time_slots = self._default_time_slots()
            self.save_time_slots()

    def _default_time_slots(self) -> Dict[str, List[TimeSlot]]:
        """Créneaux par défaut optimisés pour YouTube"""
        return {
            # Lundi - Vendredi: heures de pointe après le travail
            "monday": [
                TimeSlot(18, 0, 21, 0, priority=1),  # 18h-21h (optimal)
                TimeSlot(12, 0, 14, 0, priority=2),  # 12h-14h (pause déjeuner)
                TimeSlot(8, 0, 10, 0, priority=3),  # 8h-10h (matin)
            ],
            "tuesday": [
                TimeSlot(18, 0, 21, 0, priority=1),
                TimeSlot(12, 0, 14, 0, priority=2),
                TimeSlot(8, 0, 10, 0, priority=3),
            ],
            "wednesday": [
                TimeSlot(18, 0, 21, 0, priority=1),
                TimeSlot(12, 0, 14, 0, priority=2),
                TimeSlot(8, 0, 10, 0, priority=3),
            ],
            "thursday": [
                TimeSlot(18, 0, 21, 0, priority=1),
                TimeSlot(12, 0, 14, 0, priority=2),
                TimeSlot(8, 0, 10, 0, priority=3),
            ],
            "friday": [
                TimeSlot(18, 0, 21, 0, priority=1),
                TimeSlot(12, 0, 14, 0, priority=2),
                TimeSlot(15, 0, 17, 0, priority=2),  # Fin d'après-midi vendredi
            ],
            # Week-end: créneaux étendus
            "saturday": [
                TimeSlot(10, 0, 12, 0, priority=1),  # Matin week-end
                TimeSlot(14, 0, 18, 0, priority=1),  # Après-midi week-end
                TimeSlot(20, 0, 22, 0, priority=2),  # Soirée
            ],
            "sunday": [
                TimeSlot(10, 0, 12, 0, priority=1),
                TimeSlot(14, 0, 18, 0, priority=1),
                TimeSlot(20, 0, 22, 0, priority=2),
            ],
        }

    def save_time_slots(self):
        """Sauvegarder les créneaux"""
        try:
            data = {}
            for day, slots in self.time_slots.items():
                data[day] = [slot.to_dict() for slot in slots]

            with open(self.slots_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.error(f"Erreur sauvegarde créneaux: {e}")

    def load_scheduled_tasks(self):
        """Charger les tâches planifiées"""
        self.scheduled_tasks: List[ScheduledTask] = []

        if self.schedule_file.exists():
            try:
                with open(self.schedule_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    raw_tasks = [ScheduledTask.from_dict(task) for task in data]
                    # Normaliser les datetimes en timezone-aware
                    norm: List[ScheduledTask] = []
                    for t in raw_tasks:
                        if t.scheduled_time.tzinfo is None:
                            t.scheduled_time = self.timezone.localize(t.scheduled_time)
                        else:
                            t.scheduled_time = t.scheduled_time.astimezone(
                                self.timezone
                            )
                        if t.created_at is not None:
                            if t.created_at.tzinfo is None:
                                t.created_at = self.timezone.localize(t.created_at)
                            else:
                                t.created_at = t.created_at.astimezone(self.timezone)
                        norm.append(t)
                    self.scheduled_tasks = norm
            except Exception as e:
                log.error(f"Erreur chargement tâches planifiées: {e}")

    def save_scheduled_tasks(self):
        """Sauvegarder les tâches planifiées"""
        try:
            data = [task.to_dict() for task in self.scheduled_tasks]
            with open(self.schedule_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.error(f"Erreur sauvegarde tâches planifiées: {e}")

    def find_next_optimal_slot(
        self,
        from_time: Optional[datetime] = None,
        preferred_days: Optional[List[str]] = None,
        min_delay_hours: int = 1,
    ) -> datetime:
        """
        Trouve le prochain créneau optimal pour un upload

        Args:
            from_time: Heure de départ (maintenant par défaut)
            preferred_days: Jours préférés (tous par défaut)
            min_delay_hours: Délai minimum en heures

        Returns:
            Datetime du prochain créneau optimal
        """
        if from_time is None:
            from_time = datetime.now(self.timezone)

        # Ajouter le délai minimum
        search_start = from_time + timedelta(hours=min_delay_hours)

        # Chercher sur les 14 prochains jours
        for days_ahead in range(14):
            check_date = search_start.date() + timedelta(days=days_ahead)
            day_name = check_date.strftime("%A").lower()

            # Filtrer par jours préférés
            if preferred_days and day_name not in preferred_days:
                continue

            # Obtenir les créneaux du jour
            day_slots = self.time_slots.get(day_name, [])
            if not day_slots:
                continue

            # Trier par priorité (1 = meilleure)
            day_slots.sort(key=lambda s: s.priority)

            for slot in day_slots:
                # Calculer l'heure de début du créneau
                slot_start = datetime.combine(check_date, slot.start_time)
                slot_start = self.timezone.localize(slot_start)

                # Vérifier si c'est dans le futur
                if slot_start <= search_start:
                    continue

                # Vérifier la disponibilité (pas trop de tâches déjà planifiées)
                if self._is_slot_available(slot_start, slot):
                    return slot_start

        # Fallback: dans 24h si aucun créneau optimal trouvé
        return search_start + timedelta(hours=24)

    def _is_slot_available(
        self, slot_time: datetime, slot: TimeSlot, max_tasks_per_slot: int = 3
    ) -> bool:
        """Vérifie si un créneau a de la place"""
        slot_end = datetime.combine(slot_time.date(), slot.end_time)
        slot_end = self.timezone.localize(slot_end)

        # Compter les tâches déjà planifiées dans ce créneau
        tasks_in_slot = 0
        for task in self.scheduled_tasks:
            if (
                task.status in [ScheduleStatus.SCHEDULED, ScheduleStatus.READY]
                and slot_time <= task.scheduled_time <= slot_end
            ):
                tasks_in_slot += 1

        return tasks_in_slot < max_tasks_per_slot

    def schedule_task(
        self,
        task_path: Path,
        scheduled_time: Optional[datetime] = None,
        preferred_days: Optional[List[str]] = None,
    ) -> ScheduledTask:
        """
        Planifier une tâche

        Args:
            task_path: Chemin vers la tâche à planifier
            scheduled_time: Heure spécifique (auto si None)
            preferred_days: Jours préférés pour la planification auto

        Returns:
            Tâche planifiée créée
        """
        if scheduled_time is None:
            scheduled_time = self.find_next_optimal_slot(preferred_days=preferred_days)

        # Générer un ID unique
        task_id = f"sched_{int(scheduled_time.timestamp())}_{task_path.stem}"

        # Créer la tâche planifiée
        scheduled_task = ScheduledTask(
            task_id=task_id,
            scheduled_time=scheduled_time,
            original_task_path=task_path,
            created_at=datetime.now(self.timezone),
        )

        self.scheduled_tasks.append(scheduled_task)
        self.save_scheduled_tasks()

        log.info(f"Tâche planifiée: {task_id} pour {scheduled_time}")
        return scheduled_task

    def get_ready_tasks(
        self, current_time: Optional[datetime] = None
    ) -> List[ScheduledTask]:
        """Obtenir les tâches prêtes à être exécutées"""
        if current_time is None:
            current_time = datetime.now(self.timezone)

        ready_tasks = []
        for task in self.scheduled_tasks:
            if (
                task.status == ScheduleStatus.SCHEDULED
                and task.scheduled_time <= current_time
            ):
                task.status = ScheduleStatus.READY
                ready_tasks.append(task)

        if ready_tasks:
            self.save_scheduled_tasks()

        return ready_tasks

    def mark_task_processing(self, task_id: str) -> bool:
        """Marquer une tâche comme en cours de traitement"""
        for task in self.scheduled_tasks:
            if task.task_id == task_id:
                task.status = ScheduleStatus.PROCESSING
                self.save_scheduled_tasks()
                return True
        return False

    def mark_task_completed(self, task_id: str) -> bool:
        """Marquer une tâche comme terminée"""
        for task in self.scheduled_tasks:
            if task.task_id == task_id:
                task.status = ScheduleStatus.COMPLETED
                self.save_scheduled_tasks()
                return True
        return False

    def mark_task_failed(self, task_id: str, retry: bool = True) -> bool:
        """Marquer une tâche comme échouée et optionnellement la reprogrammer"""
        for task in self.scheduled_tasks:
            if task.task_id == task_id:
                task.attempts += 1

                if retry and task.attempts < task.max_attempts:
                    # Reprogrammer dans 1 heure
                    task.scheduled_time = datetime.now(self.timezone) + timedelta(
                        hours=1
                    )
                    task.status = ScheduleStatus.SCHEDULED
                    log.info(
                        f"Tâche reprogrammée: {task_id} (tentative {task.attempts})"
                    )
                else:
                    task.status = ScheduleStatus.FAILED
                    log.error(f"Tâche définitivement échouée: {task_id}")

                self.save_scheduled_tasks()
                return True
        return False

    def cancel_task(self, task_id: str) -> bool:
        """Annuler une tâche planifiée"""
        for i, task in enumerate(self.scheduled_tasks):
            if task.task_id == task_id and task.status in [
                ScheduleStatus.SCHEDULED,
                ScheduleStatus.READY,
            ]:
                del self.scheduled_tasks[i]
                self.save_scheduled_tasks()
                log.info(f"Tâche annulée: {task_id}")
                return True
        return False

    def reschedule_task(self, task_id: str, new_time: datetime) -> bool:
        """Reprogrammer une tâche"""
        for task in self.scheduled_tasks:
            if task.task_id == task_id and task.status in [
                ScheduleStatus.SCHEDULED,
                ScheduleStatus.READY,
            ]:
                # Normaliser new_time en timezone-aware locale
                if new_time.tzinfo is None:
                    task.scheduled_time = self.timezone.localize(new_time)
                else:
                    task.scheduled_time = new_time.astimezone(self.timezone)
                task.status = ScheduleStatus.SCHEDULED
                self.save_scheduled_tasks()
                log.info(f"Tâche reprogrammée: {task_id} pour {new_time}")
                return True
        return False

    def get_schedule_stats(self) -> Dict[str, Any]:
        """Obtenir les statistiques de planification"""
        now = datetime.now(self.timezone)

        stats = {
            "total_scheduled": len(self.scheduled_tasks),
            "by_status": {},
            "next_24h": 0,
            "next_week": 0,
            "overdue": 0,
        }

        # Compter par statut
        for task in self.scheduled_tasks:
            status = task.status.value
            stats["by_status"][status] = stats["by_status"].get(status, 0) + 1

            # Compter par période
            time_diff = task.scheduled_time - now
            if time_diff.total_seconds() < 0:
                stats["overdue"] += 1
            elif time_diff.total_seconds() < 86400:  # 24h
                stats["next_24h"] += 1
            elif time_diff.total_seconds() < 604800:  # 7 jours
                stats["next_week"] += 1

        return stats

    def cleanup_old_tasks(self, days_old: int = 30):
        """Nettoyer les anciennes tâches terminées"""
        cutoff_date = datetime.now(self.timezone) - timedelta(days=days_old)

        initial_count = len(self.scheduled_tasks)
        self.scheduled_tasks = [
            task
            for task in self.scheduled_tasks
            if not (
                task.status in [ScheduleStatus.COMPLETED, ScheduleStatus.FAILED]
                and task.created_at
                and task.created_at < cutoff_date
            )
        ]

        cleaned_count = initial_count - len(self.scheduled_tasks)
        if cleaned_count > 0:
            self.save_scheduled_tasks()
            log.info(f"Nettoyage: {cleaned_count} anciennes tâches supprimées")

        return cleaned_count
