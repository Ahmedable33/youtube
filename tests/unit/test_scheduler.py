from datetime import timedelta
from pathlib import Path

from src.scheduler import UploadScheduler, ScheduleStatus


def test_scheduler_defaults_and_optimal_slot(tmp_path: Path):
    sched_dir = tmp_path / "schedule"
    us = UploadScheduler(config_path=tmp_path / "video.yaml", schedule_dir=sched_dir)

    # time_slots should be created and saved
    assert us.slots_file.exists()
    assert isinstance(us.time_slots, dict)
    assert any(us.time_slots.values())

    # find next optimal slot returns a future datetime with tzinfo
    next_dt = us.find_next_optimal_slot()
    assert next_dt.tzinfo is not None


def test_schedule_and_ready_tasks(tmp_path: Path):
    sched_dir = tmp_path / "schedule"
    us = UploadScheduler(config_path=tmp_path / "video.yaml", schedule_dir=sched_dir)

    # create dummy task file path
    task_file = tmp_path / "task_001.json"
    task_file.write_text("{}", encoding="utf-8")

    st = us.schedule_task(task_file)
    assert st.task_id
    assert st.status == ScheduleStatus.SCHEDULED

    # move time forward to mark ready
    ready_list = us.get_ready_tasks(current_time=st.scheduled_time + timedelta(minutes=5))
    assert any(t.task_id == st.task_id for t in ready_list)
    # persist updated status
    assert us.schedule_file.exists()
