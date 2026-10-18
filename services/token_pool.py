"""
Recaptcha token pool.

hi2.in accepts the same reCAPTCHA token for many requests (verified live:
one token served 11+ checks), so instead of solving reCAPTCHA for EVERY
check (2 Google requests each!), a background thread keeps a small pool
warm and checks pop tokens from it.
"""
import queue
import threading
import time

import config
from services.recaptcha import recaptcha

POOL_SIZE = max(1, config.TOKEN_POOL_SIZE)

_pool: "queue.Queue[str]" = queue.Queue(maxsize=POOL_SIZE)
_start_lock = threading.Lock()
_started = False
_stats = {"generated": 0, "used": 0, "gen_failed": 0}


def _filler_loop():
    """Keep the pool stocked in the background."""
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
    """Start the background filler (idempotent, called from main.py)."""
    global _started
    with _start_lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_filler_loop, daemon=True, name="token-pool").start()


def get_token(timeout=25):
    """
    Pop a warm token. Falls back to a live solve if the pool is empty.
    Returns token str or None.
    """
    if not _started:
        start()
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
