"""
Automatic proxy refresher – keeps the egress pool stocked with ZERO manual
work (the user has ~1200 users and must never touch this).

Loop (single daemon thread):
    every PROXY_SWEEP_EVERY seconds:
        if usable proxies < PROXY_REFILL_AT  OR  last sweep > PROXY_SWEEP_HOURS old:
            SWEEP:
              1. fetch fresh free lists from PROXY_SOURCES
                 (proxifly, TheSpeedX, monosans, roosterkid, zloi-user,
                  proxyscrape – http + socks4 + socks5)
              2. candidates = current file entries FIRST (still-alive
                 incumbents get re-validated) + fetched, deduped, shuffled
              3. probe each candidate tokenlessly THROUGH itself:
                 hi2.in answering {"error":"reCaptcha error"} = ALIVE
                 (exits early once PROXY_TARGET alive are found)
              4. atomic rewrite of PROXY_FILE + proxy_pool.load() –
                 hot reload, bot never restarts

Safety guards:
    * only one sweep at a time
    * never replaces a healthy list with < PROXY_REFILL_AT entries
      (source/network failure cannot shrink the pool)
    * a failed fetch still re-validates the existing file
"""
import os
import queue
import random
import socket
import threading
import time

import requests

import config
from services import proxy_pool

_API = "https://hi2.in/api/custom"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "authorization": "Basic bnVsbA==",
    "Origin": "https://hi2.in",
    "Referer": "https://hi2.in/",
    "X-Requested-With": "XMLHttpRequest",
}

STATE = {
    "sweeping": False,
    "last_sweep": 0.0,
    "sweeps": 0,
    "found": 0,
    "probed": 0,
    "sources_ok": 0,
    "last_dur": 0.0,
    "last_error": "",
    "wrote": False,
}
_lock = threading.Lock()
_start_lock = threading.Lock()
_started = False


# ------------------------------------------------------------------ sources
def _fetch_sources():
    """Download every source list. Returns ([(tag, raw_line), ...], ok_count)."""
    out = []
    ok = 0
    sess = requests.Session()
    sess.trust_env = False
    entries = list(config.PROXY_SOURCES) + [("http", u) for u in config.PROXY_SOURCES_EXTRA]
    for tag, url in entries:
        try:
            r = sess.get(url, timeout=25)
            if r.status_code != 200 or not r.text:
                continue
            ok += 1
            for line in r.text.splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    out.append((tag, line))
        except requests.RequestException:
            continue
    sess.close()
    return out, ok


def _normalize(tag, raw):
    """'ip:port' / 'scheme://ip:port' -> clean proxy URL (or None if junk)."""
    raw = raw.strip()
    if not raw:
        return None
    if "://" in raw:
        scheme, hostpart = raw.split("://", 1)
        scheme = scheme.lower()
    else:
        scheme, hostpart = tag, raw
    if scheme == "https":
        scheme = "http"      # 'https proxy' lists = CONNECT-capable http proxies
    if scheme not in ("http", "socks4", "socks5"):
        return None
    if " " in hostpart or "/" in hostpart or "?" in hostpart:
        return None          # not a bare host:port (html, urls, junk)
    host, _, port = hostpart.rpartition(":")
    if not host or not port.isdigit() or not (1 <= int(port) <= 65535):
        return None
    return f"{scheme}://{hostpart}"


# ------------------------------------------------------------------- probe
def _tcp_open(url, timeout=3.0):
    """Fast pre-check: is the proxy port even reachable? (~3s vs 4-5s
    full-probe timeout for the many blackholed entries in free lists).
    3.0s (not 1.5s): slow-RTT but LIVE exits (Asia/Latam, 2-3.5s connect)
    must survive – a tighter cutoff measurably shrank the sweep yield."""
    try:
        _, hostport = url.split("://", 1)
        host, _, port = hostport.rpartition(":")
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except Exception:
        return False


def _probe(url):
    """True if hi2.in answers normally THROUGH this proxy (golden signal)."""
    s = requests.Session()
    s.trust_env = False
    try:
        r = s.post(
            _API,
            data={"domain": "hi2.in", "prefix": "rf" + os.urandom(3).hex(),
                  "recaptcha": ""},
            headers=_HEADERS,
            proxies={"http": url, "https": url},
            timeout=(4, 5),
        )
        low = (r.text or "").lower()
        if "too many requests" in low or r.status_code == 429:
            return False
        if r.status_code == 400 and "recaptcha" in low:
            return True
        if "already taken" in low or '"expiry"' in low or '"hash"' in low:
            return True
        return False
    except Exception:
        return False
    finally:
        s.close()


# ------------------------------------------------------------------- sweep
def sweep():
    """One refill cycle. Returns True if the proxy file was rewritten."""
    with _lock:
        if STATE["sweeping"]:
            return False
        STATE["sweeping"] = True
    t0 = time.time()
    wrote = False
    alive = []
    probed = [0]
    try:
        fetched, ok = _fetch_sources()

        existing = []
        if os.path.exists(config.PROXY_FILE):
            with open(config.PROXY_FILE, encoding="utf-8", errors="ignore") as f:
                existing = [l.strip() for l in f if l.strip() and not l.startswith("#")]

        seen = set()
        candidates = []
        # incumbents first: proxies that worked recently get re-validated first
        for raw in existing:
            u = _normalize("http", raw)
            if u and u not in seen:
                seen.add(u)
                candidates.append(u)
        random.shuffle(fetched)
        # HTTP first (measured ~7% alive) then SOCKS (lower yield, slower
        # timeouts) – otherwise huge socks lists eat the whole probe budget.
        http_fetched = [x for x in fetched if x[0] == "http"]
        socks_fetched = [x for x in fetched if x[0] != "http"]
        random.shuffle(http_fetched)
        random.shuffle(socks_fetched)
        for tag, raw in http_fetched + socks_fetched:
            u = _normalize(tag, raw)
            if u and u not in seen:
                seen.add(u)
                candidates.append(u)

        # ---- probe with early exit at PROXY_TARGET ----
        work: "queue.Queue" = queue.Queue()
        for u in candidates:
            work.put(u)
        stop = threading.Event()
        out_lock = threading.Lock()
        deadline = t0 + config.PROXY_PROBE_DEADLINE

        def worker():
            while not stop.is_set() and time.time() < deadline:
                try:
                    u = work.get(timeout=0.3)
                except queue.Empty:
                    return
                if _tcp_open(u):
                    hit = _probe(u)
                else:
                    hit = False
                with out_lock:
                    probed[0] += 1
                    if hit:
                        alive.append(u)
                        if len(alive) >= config.PROXY_TARGET:
                            stop.set()

        n_workers = max(4, config.PROXY_PROBE_WORKERS)
        threads = [threading.Thread(target=worker, daemon=True, name=f"px-sweep-{i}")
                   for i in range(n_workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=config.PROXY_PROBE_DEADLINE + 30)

        n = len(alive)
        # ---- safety: never shrink a healthy pool to nothing ----
        if n >= config.PROXY_REFILL_AT or not os.path.exists(config.PROXY_FILE):
            path = config.PROXY_FILE
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                for u in alive:
                    f.write(u + "\n")
            os.replace(tmp, path)          # atomic: readers never see a half file
            proxy_pool.load()              # hot reload – no restart
            wrote = True
        with _lock:
            STATE["found"] = n
            STATE["probed"] = probed[0]
            STATE["sources_ok"] = ok
            STATE["last_error"] = ""
    except Exception as e:                 # noqa: BLE001 - never kill the loop
        with _lock:
            STATE["last_error"] = type(e).__name__
    finally:
        with _lock:
            STATE["sweeping"] = False
            STATE["last_sweep"] = time.time()
            STATE["sweeps"] += 1
            STATE["last_dur"] = round(time.time() - t0, 1)
            STATE["wrote"] = wrote
    return wrote


def maybe_refill():
    """Trigger rule: low pool OR stale sweep."""
    if STATE["sweeping"]:
        return False
    usable = proxy_pool.usable_count()
    age_ok = (time.time() - STATE["last_sweep"]) >= config.PROXY_SWEEP_HOURS * 3600
    if usable < config.PROXY_REFILL_AT or age_ok:
        return sweep()
    return False


# ------------------------------------------------------------------- loop
def _dump_stats():
    """Persist live counters to data/runtime_stats.json so admin tooling can
    read pool/queue usage any time WITHOUT touching the running process."""
    try:
        import json
        from services import check_queue, proxy_pool as _pp
        out = {
            "ts": time.time(),
            "iso": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            "pool": _pp.stats(),
            "queue": check_queue.stats(),
            "refresher": stats(),
        }
        path = os.path.join(os.path.dirname(config.PROXY_FILE) or ".", "runtime_stats.json")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1)
        os.replace(tmp, path)
    except Exception:                         # noqa: BLE001 - never kill the loop
        pass


def _loop():
    time.sleep(45)                          # let the bot finish booting first
    while True:
        _dump_stats()                       # snapshot even while a sweep runs
        try:
            maybe_refill()
        except Exception:
            pass
        _dump_stats()                       # refresh after (possible) sweep
        time.sleep(config.PROXY_SWEEP_EVERY)


def start():
    global _started
    with _start_lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_loop, daemon=True, name="proxy-refresher").start()


def stats():
    with _lock:
        d = dict(STATE)
    if d["last_sweep"]:
        d["age_h"] = round((time.time() - d["last_sweep"]) / 3600.0, 1)
    else:
        d["age_h"] = -1.0
    return d
