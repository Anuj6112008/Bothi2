"""
proxiech.py - standalone free-proxy hunter for Temp Mail Checker Pro.

Run it yourself from this folder:

    py proxiech.py                    full run (all 28 sources, tens of
                                      thousands of candidates, 1-2 hours)
    py proxiech.py --workers 120      try more parallel probes
    py proxiech.py --limit 500        quick test (first 500 candidates)
    py proxiech.py --deadline 1800    stop after 30 min and save what we have

While it runs you get a live stats line:

    [00:03:12] probed 12340/59012 | alive 412 (3.3%) | throttle 88 | dead 11840 | 61.2/s | ETA 12 min

Outputs (written into this folder, also on Ctrl+C):

    alive_proxies.txt   verified-working exits for hi2.in -> load into bot
    dead_proxies.txt    everything that failed (kept for reference)

The probe is EXACTLY what the production bot uses ("golden probe"):
a tokenless POST to hi2.in/api/custom through the candidate must come
back as the normal 400 "reCaptcha error" answer. Anything else (dead,
timeout, Cloudflare page, "Too many requests") = not usable.
"""
import argparse
import os
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# ----------------------------------------------------------------- console
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ------------------------------------------------------------- dependencies
def _ensure_deps():
    try:
        import requests          # noqa: F401
        import socks             # noqa: F401  (PySocks: socks4/socks5 support)
    except ImportError:
        print("[setup] installing requests + pysocks ...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet", "requests", "pysocks"]
        )
        import requests          # noqa: F401
        import socks             # noqa: F401
    return __import__("requests")


requests = _ensure_deps()

API = "https://hi2.in/api/custom"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
}
TCP_TIMEOUT = 3.0       # port reachability pre-filter
HTTP_TIMEOUT = (4, 5)   # (connect to proxy, wait for hi2.in answer)

ALIVE_FILE = "alive_proxies.txt"
DEAD_FILE = "dead_proxies.txt"

# Same 28 sources the bot's auto-refresher uses (config.PROXY_SOURCES).
SOURCES = (
    ("http",   "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/http/data.txt"),
    ("http",   "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/https/data.txt"),
    ("socks4", "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/socks4/data.txt"),
    ("socks5", "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/socks5/data.txt"),
    ("http",   "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt"),
    ("socks4", "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks4.txt"),
    ("socks5", "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt"),
    ("http",   "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt"),
    ("socks4", "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks4.txt"),
    ("socks5", "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt"),
    ("http",   "https://raw.githubusercontent.com/roosterkid/openproxylist/main/HTTPS.txt"),
    ("socks4", "https://raw.githubusercontent.com/roosterkid/openproxylist/main/SOCKS4.txt"),
    ("socks5", "https://raw.githubusercontent.com/roosterkid/openproxylist/main/SOCKS5.txt"),
    ("http",   "https://raw.githubusercontent.com/zloi-user/hideip.me/main/http.txt"),
    ("http",   "https://raw.githubusercontent.com/zloi-user/hideip.me/main/https.txt"),
    ("socks4", "https://raw.githubusercontent.com/zloi-user/hideip.me/main/socks4.txt"),
    ("socks5", "https://raw.githubusercontent.com/zloi-user/hideip.me/main/socks5.txt"),
    ("http",   "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000&country=all"),
    ("socks4", "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks4&timeout=5000&country=all"),
    ("socks5", "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks5&timeout=5000&country=all"),
    ("http",   "https://raw.githubusercontent.com/mmpx12/proxy-list/master/http.txt"),
    ("http",   "https://raw.githubusercontent.com/mmpx12/proxy-list/master/https.txt"),
    ("socks4", "https://raw.githubusercontent.com/mmpx12/proxy-list/master/socks4.txt"),
    ("socks5", "https://raw.githubusercontent.com/mmpx12/proxy-list/master/socks5.txt"),
    ("http",   "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt"),
    ("http",   "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-http.txt"),
    ("socks4", "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-socks4.txt"),
    ("socks5", "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-socks5.txt"),
)


# ------------------------------------------------------- list -> candidates
def normalize(raw, tag):
    """'ip:port' (tag = default scheme) or 'scheme://ip:port' -> clean URL."""
    raw = (raw or "").strip()
    if not raw or raw.startswith("#"):
        return None
    if "://" in raw:
        scheme, _, hostpart = raw.partition("://")
        scheme = scheme.lower()
    else:
        scheme, hostpart = tag, raw
    if scheme == "https":
        scheme = "http"      # https-lists mean CONNECT-capable http proxies
    if scheme not in ("http", "socks4", "socks5"):
        return None
    if " " in hostpart or "/" in hostpart or "?" in hostpart:
        return None          # html / urls / junk lines
    host, _, port = hostpart.rpartition(":")
    if not host or not port.isdigit() or not (1 <= int(port) <= 65535):
        return None
    return f"{scheme}://{hostpart}"


def fetch_sources():
    """Download every list (parallel). Returns (candidates, ok_count, failed_urls)."""
    results = []
    ok = [0]
    failed = []

    def one(tag_url):
        tag, url = tag_url
        try:
            r = requests.get(url, timeout=25)
            r.raise_for_status()
            ok[0] += 1
            return tag, r.text
        except Exception:
            failed.append(url)
            return tag, None

    print(f"[sources] fetching {len(SOURCES)} lists ...", flush=True)
    with ThreadPoolExecutor(max_workers=14) as ex:
        futs = [ex.submit(one, su) for su in SOURCES]
        for f in as_completed(futs):
            tag, text = f.result()
            if text:
                results.append((tag, text))

    seen, candidates = set(), []
    for tag, text in results:
        for line in text.splitlines():
            url = normalize(line, tag)
            if url and url not in seen:
                seen.add(url)
                candidates.append(url)
    print(f"[sources] ok={ok[0]}/{len(SOURCES)}  candidates={len(candidates)}",
          flush=True)
    return candidates, ok[0], failed


# ------------------------------------------------------------------- probe
def tcp_open(url, timeout=TCP_TIMEOUT):
    """Cheap pre-filter: is the port even reachable?"""
    try:
        _, hostport = url.split("://", 1)
        host, _, port = hostport.rpartition(":")
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except Exception:
        return False


def probe(url):
    """'alive' | 'throttle' | 'dead' - golden probe through the candidate."""
    s = requests.Session()
    s.trust_env = False
    try:
        r = s.post(
            API,
            data={"domain": "hi2.in", "prefix": "rf" + os.urandom(3).hex(),
                  "recaptcha": ""},
            headers=HEADERS,
            proxies={"http": url, "https": url},
            timeout=HTTP_TIMEOUT,
        )
        low = (r.text or "").lower()
        if "too many requests" in low or r.status_code == 429:
            return "throttle"
        if r.status_code == 400 and "recaptcha" in low:
            return "alive"
        if "already taken" in low or '"expiry"' in low or '"hash"' in low:
            return "alive"
        return "dead"
    except Exception:
        return "dead"
    finally:
        s.close()


def work(url):
    """TCP pre-filter + HTTP golden probe -> (url, verdict)."""
    if not tcp_open(url):
        return url, "dead"
    return url, probe(url)


# ------------------------------------------------------------ live display
def hhmmss(sec):
    sec = int(sec)
    return f"{sec // 3600:02d}:{(sec % 3600) // 60:02d}:{sec % 60:02d}"


def main():
    ap = argparse.ArgumentParser(description="free-proxy hunter (hi2.in golden probe)")
    ap.add_argument("--workers", type=int, default=70, help="parallel probes (default 70)")
    ap.add_argument("--limit", type=int, default=0, help="probe only first N candidates (test)")
    ap.add_argument("--deadline", type=int, default=3600, help="max run seconds (default 3600)")
    args = ap.parse_args()

    print("=" * 62, flush=True)
    print("  PROXIECH - free proxy hunter for hi2.in (golden probe)", flush=True)
    print("=" * 62, flush=True)

    candidates, _src_ok, _src_failed = fetch_sources()
    total = len(candidates)

    # re-runs also re-validate yesterday's finds first (they're usually best)
    if os.path.exists(ALIVE_FILE):
        try:
            with open(ALIVE_FILE, encoding="utf-8", errors="ignore") as f:
                old = [l.strip() for l in f if l.strip() and not l.startswith("#")]
            known = set(candidates)
            prepend = [u for u in old if u not in known]
            if prepend:
                candidates = prepend + candidates
                print(f"[seed] re-validating {len(prepend)} previous alive finds first",
                      flush=True)
        except Exception:
            pass

    if args.limit > 0:
        candidates = candidates[: args.limit]
        print(f"[test] --limit {args.limit} -> probing {len(candidates)} only", flush=True)
    total = len(candidates)

    t0 = time.time()
    alive, throttle, dead = [], [], []
    probed = [0]
    stop_at = t0 + args.deadline

    print(f"[probe] workers={args.workers}  deadline={args.deadline}s  "
          f"press Ctrl+C to stop early and SAVE results", flush=True)
    print("", flush=True)

    interrupted = False
    ex = ThreadPoolExecutor(max_workers=args.workers)
    try:
        futs = {ex.submit(work, u): u for u in candidates}
        last_print = 0.0
        for fut in as_completed(futs):
            url, verdict = fut.result()
            probed[0] += 1
            if verdict == "alive":
                alive.append(url)
            elif verdict == "throttle":
                throttle.append(url)
            else:
                dead.append(url)
            now = time.time()
            if now - last_print >= 0.4:
                last_print = now
                el = now - t0
                rate = probed[0] / el if el > 0 else 0
                left = (total - probed[0]) / rate if rate > 0 else 0
                pct = (100.0 * len(alive) / probed[0]) if probed[0] else 0.0
                line = (f"[{hhmmss(el)}] probed {probed[0]}/{total} | "
                        f"alive {len(alive)} ({pct:.1f}%) | throttle {len(throttle)} | "
                        f"dead {len(dead)} | {rate:.1f}/s | ETA {hhmmss(left)}")
                sys.stdout.write("\r" + line.ljust(110))
                sys.stdout.flush()
            if now >= stop_at:
                interrupted = True
                break
    except KeyboardInterrupt:
        interrupted = True
        print("\n[stop] Ctrl+C - saving what we have ...", flush=True)
    finally:
        ex.shutdown(wait=False, cancel_futures=True)

    el = time.time() - t0
    print("", flush=True)

    # ------------------------------------------------------------- save
    with open(ALIVE_FILE, "w", encoding="utf-8") as f:
        f.write("# alive_proxies.txt - verified by proxiech (golden probe) "
                f"{time.strftime('%Y-%m-%d %H:%M')}\n")
        for u in alive:
            f.write(u + "\n")
    with open(DEAD_FILE, "w", encoding="utf-8") as f:
        f.write("# dead/throttled proxies (not usable right now)\n")
        for u in throttle:
            f.write(u + "  # throttled\n")
        for u in dead:
            f.write(u + "\n")

    print("=" * 62, flush=True)
    print(f"  DONE in {hhmmss(el)}  "
          f"({'PARTIAL - deadline hit' if interrupted else 'complete'})", flush=True)
    print(f"  probed   : {probed[0]} / {total}", flush=True)
    print(f"  ALIVE    : {len(alive)}   -> {ALIVE_FILE}", flush=True)
    print(f"  throttle : {len(throttle)} (busy exits, skipped)", flush=True)
    print(f"  dead     : {len(dead)}   -> {DEAD_FILE}", flush=True)
    if alive:
        print("", flush=True)
        print("  Next step: tell bhai - 'ho gaya' - he will load", flush=True)
        print("  alive_proxies.txt into the bot pool (1000+ target).", flush=True)
    elif probed[0]:
        print("  No alive found - try more workers or run again later.",
              flush=True)
    print("=" * 62, flush=True)


if __name__ == "__main__":
    main()
