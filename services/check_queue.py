"""
Global check queue – THE core fix for the RETRY problem.

Earlier every Telegram message spawned its own thread straight at the
hi2.in API (bulk = 3 threads per user). With 1000+ users the API started
returning an HTML page "Too many requests. :(" and the checker reported
it as "RETRY" (observed: up to 61% of all checks failing).

Now ALL API attempts flow through ONE central pipeline:
  * limited worker threads (CHECK_WORKERS)
  * global spacing between requests + budget-aware pacing so the observed
    rolling limits (~500/2h, ~1000/24h successes per IP) are respected and
    capacity is spread across the whole day – no more 18h dead windows
  * exponential global cooldown when the API says "Too many requests"
    (5s -> 10s -> ... -> API_COOLDOWN_CAP) instead of hammering
  * fail-fast during long cooldowns: users get a polite "server busy"
    instantly instead of waiting, and pay 0 credits (refund path)
"""
import collections
import queue
import threading
import time
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FuturesTimeout

import config
from services import proxy_pool

WORKERS = max(1, config.CHECK_WORKERS)
MIN_INTERVAL = max(0.0, config.CHECK_MIN_INTERVAL)
MAX_QUEUE = max(10, config.CHECK_MAX_QUEUE)

_q: "queue.Queue" = queue.Queue()
_slot_lock = threading.Lock()
_start_lock = threading.Lock()
_next_slot = 0.0
_cooldown_until = 0.0
_throttle_streak = 0
_started = False
_served = 0
_success_ts = collections.deque()   # timestamps of counted (successful) responses


class QueueBusy(Exception):
    """Raised when the pipeline is full / in cooldown / wait too long."""


# ------------------------------------------------------------------ throttle
def report_throttled() -> float:
    """
    hi2.in answered 'Too many requests'. Pause the WHOLE pipeline with
    exponential cooldown (5s,10s,20s,30s,60s,...,API_COOLDOWN_CAP) instead
    of letting every user's check retry straight back into the wall.
    Returns the cooldown seconds applied.
    """
    global _throttle_streak, _cooldown_until
    with _slot_lock:
        _throttle_streak += 1
        delay = min(5 * (2 ** (_throttle_streak - 1)), config.API_COOLDOWN_CAP)
        _cooldown_until = max(_cooldown_until, time.monotonic() + delay)
        return delay


def report_ok():
    """
    Successful (counted) API response -> reset throttle state, remember the
    timestamp for rolling budget accounting, and clear any cooldown.
    """
    global _throttle_streak, _cooldown_until
    with _slot_lock:
        _throttle_streak = 0
        _cooldown_until = 0.0
        now = time.time()
        _success_ts.append(now)
        _prune_locked(now)


def throttle_streak() -> int:
    with _slot_lock:
        return _throttle_streak


def _prune_locked(now: float):
    cutoff = now - 86400
    while _success_ts and _success_ts[0] < cutoff:
        _success_ts.popleft()


def _count_2h_locked(now: float) -> int:
    cutoff = now - 7200
    n = 0
    for ts in reversed(_success_ts):
        if ts < cutoff:
            break
        n += 1
    return n


def usage():
    """(successes in last 24h, successes in last 2h) – budget visibility."""
    with _slot_lock:
        now = time.time()
        _prune_locked(now)
        return len(_success_ts), _count_2h_locked(now)


def current_interval() -> float:
    """
    Budget-aware spacing: full speed while plenty of daily capacity,
    gentle slowdown near the soft limits, drip at the hard limit so the
    API never (or rarely) trips its rolling windows. Limits scale with the
    usable proxy pool (each exit IP is individually capped in proxy_pool).
    """
    if proxy_pool.usable_count() > 0:
        # Live exits available -> every request leaves from its own IP, each
        # individually budgeted in proxy_pool. The direct-IP rolling tiers
        # must NEVER stall the whole queue (observed live: 15s spacing ->
        # 321-deep backlog -> queued tokens expired -> 0 successes/2h).
        return MIN_INTERVAL
    scale = proxy_pool.pace_scale()
    with _slot_lock:
        now = time.time()
        _prune_locked(now)
        u24 = len(_success_ts)
        u2h = _count_2h_locked(now)
    interval = MIN_INTERVAL
    if u2h >= config.PACE_SOFT_2H * scale:
        interval = max(interval, config.PACE_2H_INTERVAL)
    if u24 >= config.PACE_SOFT_24H * scale:
        interval = max(interval, config.PACE_24H_INTERVAL)
    if u24 >= config.PACE_HARD_24H * scale:
        interval = max(interval, config.PACE_HARD_INTERVAL)
    return interval


# ------------------------------------------------------------------- limiter
def _acquire_slot():
    """Global rate limiter + cooldown: space out every hi2.in call."""
    global _next_slot
    scale = proxy_pool.pace_scale()
    with _slot_lock:
        now = time.monotonic()
        spacing = MIN_INTERVAL
        # Budget pacing only guards the DIRECT path (usable exits == 0):
        # proxy exits are individually capped in proxy_pool, so a proxy-fed
        # queue must keep full speed or backlog delays expire queued work.
        if proxy_pool.usable_count() == 0:
            wall = time.time()
            _prune_locked(wall)
            u24 = len(_success_ts)
            u2h = _count_2h_locked(wall)
            if u2h >= config.PACE_SOFT_2H * scale:
                spacing = max(spacing, config.PACE_2H_INTERVAL)
            if u24 >= config.PACE_SOFT_24H * scale:
                spacing = max(spacing, config.PACE_24H_INTERVAL)
            if u24 >= config.PACE_HARD_24H * scale:
                spacing = max(spacing, config.PACE_HARD_INTERVAL)
        start = max(now, _next_slot, _cooldown_until)
        _next_slot = start + spacing
    delay = start - time.monotonic()
    if delay > 0:
        time.sleep(delay)


def _cooldown_remaining() -> float:
    with _slot_lock:
        return max(0.0, _cooldown_until - time.monotonic())


def _worker():
    global _served
    while True:
        fn, fut = _q.get()
        try:
            if not fut.set_running_or_notify_cancel():
                continue          # caller cancelled while queued
            _acquire_slot()       # wait for rate slot / budget pacing / cooldown
            try:
                result = fn()
            except BaseException as e:      # noqa: BLE001 - forward to caller
                if not fut.cancelled():
                    try:
                        fut.set_exception(e)
                    except Exception:
                        pass
                continue
            if not fut.cancelled():
                try:
                    fut.set_result(result)
                except Exception:
                    pass
            _served += 1
        finally:
            _q.task_done()


def start():
    """Start worker threads (idempotent, called from main.py)."""
    global _started
    with _start_lock:
        if _started:
            return
        _started = True
    for i in range(WORKERS):
        threading.Thread(target=_worker, daemon=True, name=f"check-worker-{i}").start()


def position() -> int:
    """Jobs waiting in the pipeline (for 'queued #N' messages)."""
    return _q.qsize()


def run(fn, timeout=120):
    """
    Submit one rate-limited API attempt and wait for its result.
    Raises QueueBusy if the pipeline is full, the API is in a long
    cooldown (fail-fast -> polite 'busy', zero credits), or the wait
    timed out.
    """
    if not _started:
        start()
    # Fail-fast only when there is genuinely nowhere to send the request:
    # a long DIRECT cooldown with no usable proxy left. (If the pool has
    # live proxies, checks keep flowing through them.)
    if _cooldown_remaining() > config.API_FAIL_FAST_AFTER and proxy_pool.usable_count() == 0:
        raise QueueBusy("api in cooldown")
    if _q.qsize() >= MAX_QUEUE:
        raise QueueBusy(f"check queue full ({_q.qsize()})")
    fut: Future = Future()
    _q.put((fn, fut))
    try:
        return fut.result(timeout=timeout)
    except FuturesTimeout:
        # Waited too long without a result -> let caller report politely
        raise QueueBusy("timed out waiting in queue")


def stats():
    u24, u2h = usage()
    with _slot_lock:
        cd = max(0.0, _cooldown_until - time.monotonic())
        streak = _throttle_streak
    return {
        "queue": _q.qsize(),
        "workers": WORKERS,
        "served": _served,
        "cooldown": round(cd, 1),
        "throttle_streak": streak,
        "used_24h": u24,
        "used_2h": u2h,
        "interval": round(current_interval(), 2),
    }
