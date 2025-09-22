# v2025.09.22 — Stable integration suite (35 tests passing)

## Highlights

- Worker robustness improvements
  - Missing video file: task marked `error` and archived.
  - uploadLimitExceeded: first failing task marked `blocked` and archived; worker stops to avoid cascading failures; remaining tasks stay in queue.
  - Multi-accounts: if no account is available, task is marked `error` and archived (instead of returning early).

- CLI upload `--pre-enhance`
  - Merges quality presets and CLI overrides.
  - Uses the generated `.enhanced.mp4` path for upload.

- Scheduling
  - Custom mode:
    - Past date/time -> process immediately.
    - Future date/time -> scheduled with `UploadScheduler`, original task moved to archive.
  - Scheduled tasks call `mark_task_completed` after successful processing.

- Subtitles
  - When Whisper is unavailable: logs a warning, does not fail the task (status remains `done`).
  - `replace_existing` with partial upload failures: records per-language results; task remains `done`.

## Tests

- Total: 35 tests passed
- Integration tests expanded:
  - Subtitles partial failure recorded; task remains `done`.
  - Scheduler custom (past/future) + `mark_task_completed`.
  - Invalid config -> warn + continue (no hard failure).
  - Multi-accounts no account -> task archived as `error`.
  - CLI upload `--pre-enhance` end-to-end with ffmpeg mocks.
- Test suite reorganized:
  - Unit tests in `tests/unit/`
  - Integration tests in `tests/integration/`

## CI

- Added GitHub Actions workflow: `.github/workflows/ci.yml`
  - Python 3.11, pytest run.
  - Uses `requirements-ci.txt` to avoid heavyweight Whisper dependency.

## Dependencies

- Test dependencies pinned for compatibility:
  - `respx==0.20.*`
  - `httpx>=0.24.1,<0.25`

## Breaking changes

- None.

## Upgrade notes

- No migration steps required.
- If using multi-accounts, tasks will now be archived with `status=error` when no account is available.
