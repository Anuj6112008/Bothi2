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

    # registered: email echoed back + full recovery screen embedded
    if echoed and has_screen and size > 100000:
        return "ig_connected", f"len={size}"
    # unknown: small payload, no echo, no embedded screen
    if (not echoed) and (not has_screen) and size < 100000:
        return "ig_not_connected", f"len={size}"
    # anything else is unexpected -> don't guess, don't bill
    return "ig_error", f"unexpected len={size} echoed={echoed} embedded={has_screen}"


def _try_proxy(email):
    """One pass over the shared pool: up to INSTA_MAX_ATTEMPTS live proxies."""
    tried = set()
    attempts = max(1, config.INSTA_MAX_ATTEMPTS)
    while len(tried) < attempts:
        px = proxy_pool.acquire()
        if not px or px in tried:
            # pool may be tiny/exhausted right now; avoid an infinite loop
            if not px:
                break
            continue
        tried.add(px)
        try:
            resp = _post(email, proxy=px)
            status, detail = _classify(email, resp)
            if status == "ig_error":
                # blocked/dead exit IP -> cool it down in the shared pool
                proxy_pool.report(
                    px, "throttle" if "http_4" in detail else "net")
                continue
            proxy_pool.report(px, "ok")
            return {"email": email, "status": status, "via": "proxy"}
        except Exception:
            proxy_pool.report(px, "net")
            continue
    return None


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
    if config.INSTA_PROXY_FIRST:
        got = _try_proxy(email)
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
        got = _try_proxy(email)
        if got:
            return got

    try:
        print(f"[insta] {email}: error (direct={first_err})")
    except Exception:
        pass
    return {"email": email, "status": "ig_error", "via": "-"}
