"""The claugram daemon: runs the Telegram poller plus a job worker thread.

`claugram bot`, `claugram controller` and `claugram hub` all start this. The
poller is the single Telegram reader; the worker drains controller_jobs and
runs Claude in the target project.

One bot process = one Telegram token + whitelist (taken from the *primary*
project). It can, however, drive many registered repos: each chat picks an
active project with /use, and jobs are routed to that project's config/session.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Optional

from ..runtime import Runtime, setup_logging
from ..telegram import BotPoller, BotContext
from ..config import load_config
from . import runner, registry

log = logging.getLogger("claugram.daemon")


class JobWorker(threading.Thread):
    """Drains queued jobs, building/reusing a Runtime per target project."""

    def __init__(self, db_path, poll_interval: float = 2.0):
        super().__init__(daemon=True, name="claugram-jobworker")
        self.db_path = db_path
        self.poll_interval = poll_interval
        self._running = True
        self._runtimes: dict[str, Runtime] = {}

    def stop(self) -> None:
        self._running = False

    def _runtime_for(self, store, project_id: str) -> Optional[Runtime]:
        if project_id in self._runtimes:
            return self._runtimes[project_id]
        row = store.get_project(project_id)
        if not row:
            return None
        rt = Runtime(Path(row["root_path"]))
        self._runtimes[project_id] = rt
        return rt

    def run(self) -> None:
        from ..storage import Store
        store = Store(self.db_path)  # own connection for this thread
        while self._running:
            job = store.claim_next_job()
            if not job:
                time.sleep(self.poll_interval)
                continue
            log.info("running job %s (%s) project=%s",
                     job["id"], job["command"], job["project_id"])
            try:
                rt = self._runtime_for(store, job["project_id"])
                if rt is None:
                    store.finish_job(job["id"], "failed", "unknown project")
                    continue
                result = runner.run_job(rt, job)
                store.finish_job(job["id"], "done", result or "")
            except Exception as exc:  # pragma: no cover - defensive
                log.exception("job %s failed", job["id"])
                store.finish_job(job["id"], "failed", str(exc))
        for rt in self._runtimes.values():
            rt.close()
        store.close()


def _status_text(rt: Runtime) -> str:
    from ..cli_helpers import status_lines
    return "\n".join(status_lines(rt))


def _pick_primary(store) -> Optional[str]:
    """Newest registered project root, used for telegram creds + default."""
    projects = store.list_projects()
    if not projects:
        return None
    return projects[-1]["root_path"]


def run_daemon(project_root: Optional[Path] = None,
               enable_controller: bool = True) -> None:
    setup_logging("daemon")

    if project_root is None:
        from ..storage import Store
        boot = Store()
        primary = _pick_primary(boot)
        boot.close()
        if not primary:
            raise RuntimeError(
                "No registered projects. Run `claugram init` in a repo first, "
                "or start with `claugram bot --project <path>`.")
        project_root = Path(primary)

    primary_rt = Runtime(project_root)
    store = primary_rt.store
    default_ref = registry.by_id(store, primary_rt.project_id)

    # cache of per-project Runtimes used by the (single-threaded) poller for
    # status/session listing
    poller_runtimes: dict[str, Runtime] = {primary_rt.project_id: primary_rt}

    def rt_for(ref) -> Runtime:
        if ref.project_id not in poller_runtimes:
            poller_runtimes[ref.project_id] = Runtime(ref.root)
        return poller_runtimes[ref.project_id]

    def resolve_project(chat_id: int):
        return registry.active_ref(store, chat_id, default_ref)

    def select_project(chat_id: int, arg: str):
        ref = registry.find(store, arg)
        if ref:
            store.set_active_project(chat_id, ref.project_id)
        return ref

    def enqueue(command: str, prompt: str, chat_id: int) -> Optional[str]:
        ref = resolve_project(chat_id)
        if ref is None:
            return None
        return store.enqueue_job(ref.project_id, chat_id, command, prompt)

    def status_provider(chat_id: int) -> str:
        ref = resolve_project(chat_id)
        if ref is None:
            return "No project selected. Use /projects then /use <name>."
        return _status_text(rt_for(ref))

    worker = None
    if enable_controller and primary_rt.config.controller.enabled:
        worker = JobWorker(store.db_path)
        worker.start()

    ctx = BotContext(
        store=store,
        client=primary_rt.client,
        allowed_chat_ids=primary_rt.allowed_chat_ids,
        resolve_project=resolve_project,
        select_project=select_project,
        list_projects=lambda: registry.list_registered(store),
        enqueue=enqueue,
        status_provider=status_provider,
    )
    poller = BotPoller(ctx, poll_timeout=primary_rt.config.telegram.polling_timeout_sec)
    log.info("daemon started (primary=%s, %d project(s))",
             default_ref.name if default_ref else "?", len(store.list_projects()))
    try:
        poller.run()
    except KeyboardInterrupt:
        log.info("shutting down")
    finally:
        if worker:
            worker.stop()
        for rt in poller_runtimes.values():
            rt.close()
