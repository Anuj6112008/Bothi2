"""
Egress proxy pool – spread hi2.in checks over multiple client IPs.

Why: hi2.in rate-limits per client IP (observed: ~500 successes / 2h and
~1000 / 24h per IP; VPS IP is throttled most of the day -> users saw
"RETRY"). Free proxies (proxifly/free-proxy-list) let each check leave
from a different IP, so one exhausted IP no longer blocks everyone.

Every proxy gets the SAME polite treatment we give the direct IP:
  * per-proxy rolling success budget (soft/hard caps well under the
    observed limits, so we never push a single exit IP into throttle)
  * per-proxy exponential cooldown when it answers "Too many requests"
  * consecutive network failures -> temporary quarantine
Fallback is always DIRECT (the old path) when no proxy is usable.

Data file: data/proxies.txt (one "http://ip:port" per line, '#' = comment).
Config:   PROXY_ENABLED, PROXY_SOFT_2H, PROXY_HARD_24H, ...
"""
import collections
import os
import threading
import time

import config

_lock = threading.Lock()
_list = []            # list[_Proxy]
_map = {}             # url -> _Proxy
_rr = 0
_loaded = False


class _Proxy:
    __slots__ = ("url", "fails", "streak", "cooldown_until", "quarantine_until", "ok_ts")

    def __init__(self, url):
        self.url = url
        self.fails = 0
        self.streak = 0
        self.cooldown_until = 0.0
        self.quarantine_until = 0.0
        self.ok_ts = collections.deque()

    def budget_ok(self, now):
        # prune old successes (rolling windows)
        day = now - 86400.0
        while self.ok_ts and self.ok_ts[0] < day:
            self.ok_ts.popleft()
        if len(self.ok_ts) >= config.PROXY_HARD_24H:
            return False
        hour = now - 7200.0
        n = 0
        for ts in reversed(self.ok_ts):
            if ts < hour:
                break
            n += 1
        return n < config.PROXY_SOFT_2H


def load(path=None):
    """(Re)read the proxy list from disk."""
    global _loaded
    path = path or config.PROXY_FILE
    items = []
    if os.path.exists(path):
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "://" not in line:
                    line = "http://" + line
                items.append(line)
    with _lock:
        _list.clear()
        _map.clear()
        for url in items:
            p = _Proxy(url)
            _list.append(p)
            _map[url] = p
        _loaded = True
    return len(items)


def _ensure():
    if not _loaded:
        load()


def acquire():
    """Next usable proxy URL, or None -> caller falls back to direct."""
    if not config.PROXY_ENABLED:
        return None
    _ensure()
    global _rr
    with _lock:
        if not _list:
            return None
        now = time.time()
        n = len(_list)
        for _ in range(n):
            p = _list[_rr % n]
            _rr += 1
            if now < p.quarantine_until:
                continue
            if now < p.cooldown_until:
                continue
            if not p.budget_ok(now):
                continue
            if p.quarantine_until and p.quarantine_until <= now:
                p.fails = 0       # quarantine served -> give it a fresh chance
            return p.url
        return None


def report(url, outcome):
    """
    Tell the pool how a proxy behaved.
      "ok"       -> success: record timestamp (budget), reset throttle streak
      "throttle" -> hi2.in said "Too many requests" for THIS exit IP
                    -> returns per-proxy cooldown seconds (for backoff)
      "net"      -> connect/read failure -> failure count / quarantine
    """
    _ensure()
    with _lock:
        p = _map.get(url)
        if p is None:
            return 0.0
        now = time.time()
        if outcome == "ok":
            p.ok_ts.append(now)
            p.streak = 0
            p.cooldown_until = 0.0
            return 0.0
        if outcome == "throttle":
            p.streak += 1
            delay = min(5 * (2 ** (p.streak - 1)), config.API_COOLDOWN_CAP)
            p.cooldown_until = max(p.cooldown_until, now + delay)
            return delay
        # network failure
        p.fails += 1
        if p.fails >= config.PROXY_MAX_FAILS:
            p.quarantine_until = now + config.PROXY_QUARANTINE
            p.fails = 0
        return 0.0


def pace_scale():
    """
    Global pacing multiplier: more usable proxies -> the pipeline may keep
    more daily capacity (each exit IP still individually capped).
    """
    if not config.PROXY_ENABLED:
        return 1
    return max(1, min(usable_count() // 4 + 1, config.PROXY_SCALE_CAP))


def usable_count():
    _ensure()
    with _lock:
        now = time.time()
        return sum(
            1 for p in _list
            if now >= p.quarantine_until and now >= p.cooldown_until and p.budget_ok(now)
        )


def stats():
    _ensure()
    with _lock:
        now = time.time()
        total = len(_list)
        cooldown = sum(1 for p in _list if now < p.cooldown_until)
        quarantined = sum(1 for p in _list if now < p.quarantine_until)
        usable = sum(
            1 for p in _list
            if now >= p.quarantine_until and now >= p.cooldown_until and p.budget_ok(now)
        )
        sent_ok = sum(len(p.ok_ts) for p in _list)
    return {
        "enabled": config.PROXY_ENABLED,
        "total": total,
        "usable": usable,
        "cooldown": cooldown,
        "quarantined": quarantined,
        "sent_ok_24h": sent_ok,
        "scale": pace_scale(),
    }
