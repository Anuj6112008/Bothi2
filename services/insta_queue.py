"""
Instagram-check job queue – same role as check_queue but for IG lookups.

Why a queue: each IG check holds a proxy + paces against Instagram for up
to a minute (12+ exit attempts, 1.5s global interval). Spawning one thread
per user gave zero visibility and unbounded concurrency. This queue:

  * bounds concurrency (INSTA_QUEUE_WORKERS daemon workers)
  * bounds backlog (INSTA_QUEUE_MAX) -> user gets an instant "busy" reply
    instead of piling up threads
  * exposes stats() for the admin dashboard

Jobs run in worker threads; the result callback (user-facing edit +
billing) runs in the worker, exactly like the old per-check thread.
"""
import queue
import threading
import time

import config

_jobs: "queue.Queue" = queue.Queue(maxsize=max(1, config.INSTA_QUEUE_MAX))
_lock = threading.Lock()
_served = 0
_rejected = 0
_started = False
_start_lock = threading.Lock()


def _worker():
    global _served
    from services.insta_lookup import check_insta_email   # late import: no cycles
    while True:
        email, done = _jobs.get()
        try:
            result = check_insta_email(email)
        except Exception:
            result = {"email": email, "status": "ig_error", "via": "-"}
        try:
            done(result)
        except Exception:
            pass
        finally:
            with _lock:
                _served += 1
            _jobs.task_done()


def _ensure_started():
    global _started
    with _start_lock:
        if _started:
            return
        _started = True
        for i in range(max(1, config.INSTA_QUEUE_WORKERS)):
            threading.Thread(target=_worker, daemon=True,
                             name=f"ig-worker-{i}").start()


def submit(email, done):
    """
    Queue one IG check. done(result) runs in a worker thread when finished.
    Returns False when the backlog is full (caller must tell the user and
    must NOT bill anything).
    """
    global _rejected
    _ensure_started()
    try:
        _jobs.put_nowait((email, done))
        return True
    except queue.Full:
        with _lock:
            _rejected += 1
        return False


def stats():
    with _lock:
        return {
            "queue": _jobs.qsize(),
            "served": _served,
            "rejected": _rejected,
            "workers": max(1, config.INSTA_QUEUE_WORKERS),
        }
