"""
Recaptcha token pool.

hi2.in accepts the same reCAPTCHA token for many requests (verified live:
one token served 11+ checks), so instead of solving reCAPTCHA for EVERY
check (2 Google requests each!), background threads keep a warm pool and
checks pop tokens from it.

Speed notes (2026-10-22, "bot is slow" complaints):
  * pool was 4 with ONE serial filler -> any burst (or a bad-token nuke)
    starved all 4 checkers, each blocking up to 25s inside get_token while
    already holding a queue slot -> everything behind it stalled.
  * now: bigger default pool (12) + N parallel fillers -> refill rate ~= N
    solves in parallel, and get_token waits only briefly before falling
    back to an inline solve (bounded wait, never 25s).
"""
import queue
import threading
import time

import config
from services.recaptcha import recaptcha

POOL_SIZE = max(1, config.TOKEN_POOL_SIZE)
FILLERS = max(1, config.TOKEN_FILLERS)
# Wait for the background refill ONLY this long before solving inline.
GET_WAIT = max(1.0, config.TOKEN_GET_WAIT)

_pool: "queue.Queue[str]" = queue.Queue(maxsize=POOL_SIZE)
_start_lock = threading.Lock()
_started = False
_stats = {"generated": 0, "used": 0, "gen_failed": 0}


def _filler_loop():
    """Keep the pool stocked in the background (N of these run in parallel)."""
    while True:
        try:
            if _pool.qsize() < POOL_SIZE:
                token = recaptcha()
                if token:
                    try:
                        _pool.put_nowait(token)
                        _stats["generated"] += 1
                    except queue.Full:
                        pass
                    # try to fill the next slot immediately
                    continue
                _stats["gen_failed"] += 1
                time.sleep(3)   # Google failing -> back off
            else:
                time.sleep(0.5)  # pool full -> idle
        except Exception:
            time.sleep(3)


def start():
    """Start the background fillers (idempotent, called from main.py)."""
    global _started
    with _start_lock:
        if _started:
            return
        _started = True
        for i in range(FILLERS):
            threading.Thread(target=_filler_loop, daemon=True,
                             name=f"token-pool-{i}").start()


def get_token(timeout=None):
    """
    Pop a warm token. Waits briefly for the refill, then falls back to a
    live inline solve so a checker NEVER sits on an empty pool for long.
    Returns token str or None.
    """
    if not _started:
        start()
    if timeout is None:
        timeout = GET_WAIT
    try:
        token = _pool.get(timeout=timeout)
        _stats["used"] += 1
        return token
    except queue.Empty:
        pass
    # Pool empty (burst) -> generate inline as fallback
    token = recaptcha()
    if token:
        _stats["used"] += 1
    else:
        _stats["gen_failed"] += 1
    return token


def invalidate_all():
    """Drop every cached token (call when API says token is invalid/expired)."""
    while True:
        try:
            _pool.get_nowait()
        except queue.Empty:
            return


def stats():
    return dict(_stats, pool_size=_pool.qsize())
