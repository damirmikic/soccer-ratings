from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from typing import Any

# In-memory only — fine for a single Render Starter instance. If this app
# ever runs with more than one worker/instance, job state needs to move to
# something shared (Redis, a DB table) since each process would otherwise
# see a different set of jobs.


class JobManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}

    def create(self, kind: str, label: str) -> str:
        job_id = uuid.uuid4().hex
        with self._lock:
            self._jobs[job_id] = {
                "id": job_id,
                "kind": kind,
                "label": label,
                "status": "running",
                "current": 0,
                "total": 0,
                "message": "Starting…",
                "result": None,
                "error": None,
            }
        return job_id

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job is not None else None

    def is_running(self, job_id: str) -> bool:
        job = self.get(job_id)
        return job is not None and job["status"] == "running"

    def _update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.update(fields)

    def run(self, job_id: str, fn: Callable[[Callable[[int, int, str], None]], dict]) -> None:
        """Run fn to completion, recording progress and outcome on the job.

        fn receives a progress callback of (current, total, message) and
        must return the job's result dict. Intended to be scheduled as a
        FastAPI BackgroundTask (which runs sync callables in a thread pool),
        so this method is itself synchronous and blocking.
        """

        def on_progress(current: int, total: int, message: str) -> None:
            self._update(job_id, current=current, total=total, message=message)

        try:
            result = fn(on_progress)
        except Exception as exc:
            self._update(job_id, status="error", error=str(exc), message=f"Failed: {exc}")
        else:
            self._update(job_id, status="done", result=result, message="Done")
