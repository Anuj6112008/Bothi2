"""
proxiech.py - standalone free-proxy hunter for Temp Mail Checker Pro (v2 UI).

Run it yourself from this folder:

    py proxiech.py                    full run (all 28 sources, ~87k candidates)
    py proxiech.py --workers 120      try more parallel probes
    py proxiech.py --limit 500        quick test (first 500 candidates)
    py proxiech.py --deadline 1800    stop after 30 min, save what we have

Flow:
    1. intro banner + list fetching (~1 min)
    2. screen clears, live dashboard starts (colored)
    3. Ctrl+C = early stop, results still saved

Outputs (this folder):
    alive_proxies.txt   verified-working exits for hi2.in -> load into bot
                        (previous finds are re-validated FIRST on re-runs)
    dead_proxies.txt    everything that failed (reference)

Probe = EXACTLY the production bot's "golden probe": a tokenless POST to
hi2.in/api/custom through the candidate must come back as the normal
400 "reCaptcha error". Anything else = not usable.
"""
import argparse
import os
import socket
import subprocess
import sys
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed

# ----------------------------------------------------------------- console
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

if os.name == "nt":
    os.system("")      # win10+: enable ANSI colors in cmd / PowerShell / WindowsTerminal

RST = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
MAGENTA = "\033[35m"


def g(t):
    return f"{GREEN}{t}{RST}"


def r(t):
    return f"{RED}{t}{RST}"


def y(t):
    return f"{YELLOW}{t}{RST}"


def c(t):
    return f"{CYAN}{t}{RST}"


def dim(t):
    return f"{DIM}{t}{RST}"


def bold(t):
    return f"{BOLD}{t}{RST}"


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


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
            resp = requests.get(url, timeout=25)
            resp.raise_for_status()
            ok[0] += 1
            return tag, resp.text
        except Exception:
            failed.append(url)
            return tag, None

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
        resp = s.post(
            API,
            data={"domain": "hi2.in", "prefix": "rf" + os.urandom(3).hex(),
                  "recaptcha": ""},
            headers=HEADERS,
            proxies={"http": url, "https": url},
            timeout=HTTP_TIMEOUT,
        )
        low = (resp.text or "").lower()
        if "too many requests" in low or resp.status_code == 429:
            return "throttle"
        if resp.status_code == 400 and "recaptcha" in low:
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


# -------------------------------------------------------------- UI helpers
def hhmmss(sec):
    sec = int(sec)
    return f"{sec // 3600:02d}:{(sec % 3600) // 60:02d}:{sec % 60:02d}"


def progress_bar(frac, width=24):
    frac = max(0.0, min(1.0, frac))
    filled = int(round(frac * width))
    return c("#" * filled) + dim("-" * (width - filled))


def banner(workers, deadline):
    print()
    print("  " + dim("=" * 60))
    print("   " + bold(c("P R O X I E C H")) + "   " + dim("free proxy hunter for hi2.in"))
    print("   " + dim("golden probe | same engine as the bot | laptop edition"))
    print("  " + dim("=" * 60))
    print(f"   sources : {bold(len(SOURCES))} lists")
    print(f"   power   : {bold(workers)} parallel probes, deadline {deadline // 60} min")
    print(f"   output  : {g('alive_proxies.txt')}  " + dim("-> load into bot"))
    print(f"             {r('dead_proxies.txt')}   " + dim("-> reference"))
    print("   " + dim("tip: Ctrl+C bhi results save kar deta hai"))
    print("  " + dim("-" * 60))
    print()


# ------------------------------------------------------------ live display
def print_dashboard(state):
    """Full live block; caller handles cursor-up redraw."""
    total = state["total"]
    probed = state["probed"]
    alive = state["alive"]
    thr = state["throttle"]
    dead = state["dead"]
    el = time.time() - state["t0"]
    rate = probed / el if el > 0 else 0
    left = (total - probed) / rate if rate > 0 else 0
    pct = (100.0 * probed / total) if total else 100.0
    apct = (100.0 * alive / probed) if probed else 0.0

    lines = []
    lines.append("  " + bold(c("PROXIECH LIVE"))
                 + dim("   |   golden probe -> hi2.in") + "        ")
    lines.append("  " + dim("-" * 58))
    lines.append(f"   probed   : {bold(probed)} / {total}  ({pct:.0f}%)  "
                 f"{progress_bar(pct / 100.0)}")
    lines.append(f"   {g('ALIVE')}    : {g(bold(alive))}  ({apct:.1f}% yield)")
    lines.append(f"   {y('throttle')} : {y(thr)}   " + dim("(busy exits, skipped)"))
    lines.append(f"   {r('dead')}     : {r(dead)}")
    lines.append(f"   speed    : {rate:.1f}/s    ETA {hhmmss(left)}    "
                 f"run {hhmmss(el)}")
    lines.append("  " + dim("-" * 58))
    lines.append("   " + bold("latest finds:"))
    if state["latest"]:
        for u in state["latest"]:
            lines.append("     " + g("+ ") + u)
    else:
        lines.append("     " + dim("(abhi tak koi naya alive nahi)"))
    return lines


class LiveView:
    """Redraws the dashboard in place using ANSI cursor-up."""

    def __init__(self):
        self._prev_lines = 0

    def update(self, state):
        lines = print_dashboard(state)
        out = "\033[%dA\033[J" % self._prev_lines if self._prev_lines else ""
        out += "\n".join(lines) + "\n"
        sys.stdout.write(out)
        sys.stdout.flush()
        self._prev_lines = len(lines)

    def clear(self):
        if self._prev_lines:
            sys.stdout.write("\033[%dA\033[J" % self._prev_lines)
            sys.stdout.flush()
            self._prev_lines = 0


# -------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="free-proxy hunter (hi2.in golden probe)")
    ap.add_argument("--workers", type=int, default=70, help="parallel probes (default 70)")
    ap.add_argument("--limit", type=int, default=0, help="probe only first N candidates (test)")
    ap.add_argument("--deadline", type=int, default=3600, help="max run seconds (default 3600)")
    args = ap.parse_args()

    banner(args.workers, args.deadline)

    # ---- [1/3] fetch lists
    print("   " + c("[1/3]") + f" fetching {len(SOURCES)} proxy lists ...", flush=True)
    candidates, src_ok, src_failed = fetch_sources()
    print("   " + c("[2/3]") + f" {bold(len(candidates))} unique candidates ready "
          f"({g(src_ok)} lists ok" + (f", {r(len(src_failed))} failed" if src_failed else "")
          + ")", flush=True)

    # re-runs also re-validate previous finds first (they're usually best)
    if os.path.exists(ALIVE_FILE):
        try:
            with open(ALIVE_FILE, encoding="utf-8", errors="ignore") as f:
                old = [l.strip() for l in f if l.strip() and not l.startswith("#")]
            known = set(candidates)
            prepend = [u for u in old if u not in known]
            if prepend:
                candidates = prepend + candidates
                print("   " + c("[seed]") + f" re-validating {bold(len(prepend))} "
                      "previous alive finds first", flush=True)
        except Exception:
            pass

    if args.limit > 0:
        candidates = candidates[: args.limit]
        print("   " + y("[test]") + f" --limit {args.limit} -> probing {len(candidates)} only",
              flush=True)

    total = len(candidates)
    state = {
        "total": total,
        "probed": 0,
        "alive": 0,
        "throttle": 0,
        "dead": 0,
        "t0": time.time(),
        "latest": deque(maxlen=4),
    }
    alive_list, throttle_list, dead_list = [], [], []
    stop_at = state["t0"] + args.deadline

    time.sleep(1.2)                       # let the intro breathe, then wipe
    clear_screen()
    print("   " + c("[3/3]") + " probing live - Ctrl+C = stop & save", flush=True)
    print()

    view = LiveView()
    view.update(state)

    interrupted = False
    ex = ThreadPoolExecutor(max_workers=args.workers)
    try:
        futs = {ex.submit(work, u): u for u in candidates}
        last_draw = 0.0
        for fut in as_completed(futs):
            url, verdict = fut.result()
            state["probed"] += 1
            if verdict == "alive":
                state["alive"] += 1
                alive_list.append(url)
                state["latest"].appendleft(url)
            elif verdict == "throttle":
                state["throttle"] += 1
                throttle_list.append(url)
            else:
                state["dead"] += 1
                dead_list.append(url)
            now = time.time()
            if now - last_draw >= 0.5:
                last_draw = now
                view.update(state)
            if now >= stop_at:
                interrupted = True
                break
    except KeyboardInterrupt:
        interrupted = True
    finally:
        ex.shutdown(wait=False, cancel_futures=True)

    view.clear()
    el = time.time() - state["t0"]

    # ------------------------------------------------------------- save
    with open(ALIVE_FILE, "w", encoding="utf-8") as f:
        f.write("# alive_proxies.txt - verified by proxiech (golden probe) "
                f"{time.strftime('%Y-%m-%d %H:%M')}\n")
        for u in alive_list:
            f.write(u + "\n")
    with open(DEAD_FILE, "w", encoding="utf-8") as f:
        f.write("# dead/throttled proxies (not usable right now)\n")
        for u in throttle_list:
            f.write(u + "  # throttled\n")
        for u in dead_list:
            f.write(u + "\n")

    print()
    print("  " + dim("=" * 60))
    status = y("PARTIAL - deadline hit") if interrupted else g("COMPLETE")
    print(f"   DONE in {bold(hhmmss(el))}   {status}")
    print(f"   probed   : {state['probed']} / {total}")
    print(f"   {g('ALIVE')}    : {g(bold(str(len(alive_list))))}  -> {g(ALIVE_FILE)}")
    print(f"   {y('throttle')} : {y(len(throttle_list))}   " + dim("(busy, skipped)"))
    print(f"   {r('dead')}     : {r(len(dead_list))}   -> {r(DEAD_FILE)}")
    if alive_list:
        print()
        print("   " + bold("top finds:") + " " + ", ".join(g(u) for u in alive_list[:3]))
        print("   next: " + bold("'ho gaya'") + " bolo -> bhai bot me load kar denge")
    elif state["probed"]:
        print()
        print("   " + y("No alive found - run again (lists refresh) ya workers badhao"))
    print("  " + dim("=" * 60))
    print()


if __name__ == "__main__":
    main()
