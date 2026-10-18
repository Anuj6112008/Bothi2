"""
Email availability checker – fixed pipeline.

Changes vs original:
  * recaptcha() moved to services/recaptcha.py (re-exported for compat)
  * tokens come from services/token_pool (solved once, reused many times)
  * EVERY api attempt goes through services.check_queue (global rate limit
    so 600 users can never burst hi2.in into returning HTML/rate pages)
  * transient failures (non-JSON page, 429, 5xx, timeout, bad token) are
    auto-retried with backoff INSIDE the bot – user never sees "RETRY"
    unless every attempt failed
  * correct classification: only a real success JSON is "available";
    API error bodies are no longer reported as ✅ AVAILABLE
"""
import time
import requests

import config
from services.recaptcha import recaptcha  # noqa: F401  (backward compat)
from services import check_queue, token_pool

SUPPORTED_DOMAINS = ("@hi2.in", "@telegmail.com")

MAX_ATTEMPTS = max(1, config.CHECK_MAX_ATTEMPTS)
BACKOFF = tuple(config.CHECK_RETRY_BACKOFF) or (1.5, 3.0)
API_TIMEOUT = 25
ATTEMPT_TIMEOUT = check_queue.WORKERS * 30 + 60  # generous wait while queued

_API_URL = "https://hi2.in/api/custom"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "authorization": "Basic bnVsbA==",
    "Origin": "https://hi2.in",
    "Referer": "https://hi2.in/",
    "X-Requested-With": "XMLHttpRequest",
}

# Wording that means "the recaptcha token was rejected"
_BAD_TOKEN_MARKERS = ("recaptcha", "captcha", "token")

_SUCCESS_KEYS = ("hash", "expiry")   # real success JSON: {"expiry","email","hash"}


class _Attempt:
    """Outcome of a single rate-limited API attempt."""

    __slots__ = ("kind", "status", "message", "bad_token", "retry_after")

    def __init__(self, kind, status, message="", bad_token=False, retry_after=0.0):
        self.kind = kind            # "done" | "transient" | "permanent"
        self.status = status        # final status to show the user
        self.message = message
        self.bad_token = bad_token  # drop pooled tokens & solve a fresh one
        self.retry_after = retry_after


def _safe_server_detail(body: str, status_code) -> str:
    """
    NEVER leak internals to end users: no reCAPTCHA/token wording, no API
    URLs, no raw error payloads – only a generic, human message.
    (Kept intentionally vague; full detail stays in server logs only.)
    """
    _ = body  # inspected only server-side, never shown to users
    if status_code == 401 or status_code == 403:
        return "Access denied by provider"
    if status_code == 400:
        return "Request rejected by provider"
    return "Provider error"


def _log_server_detail(email, status_code, body):
    """Server-side only log line (VPS logs / admin), never sent to Telegram."""
    try:
        print(f"[checker] {email} -> HTTP {status_code} :: {(body or '')[:120]!r}")
    except Exception:
        pass


def _hit_api(email, domain, prefix, token) -> _Attempt:
    """
    ONE attempt against hi2.in (runs inside the rate-limited queue worker).
    Never raises for expected network problems – classifies instead.
    """
    try:
        resp = requests.post(
            _API_URL,
            data={"domain": domain, "prefix": prefix, "recaptcha": token or ""},
            headers=_HEADERS,
            timeout=API_TIMEOUT,
        )
    except requests.exceptions.Timeout:
        return _Attempt("transient", "timeout", f"⏱️ TIMEOUT: {email} - Server slow")
    except requests.exceptions.RequestException:
        return _Attempt(
            "transient", "error",
            f"🔌 CONNECTION ERROR: {email} - Network issue",
        )

    body = resp.text or ""
    low = body.lower()

    # hi2.in's rate limiter: HTTP 200 + "Too many requests. :(" (text/html)
    # -> pause the whole pipeline briefly instead of hammering further.
    if "too many requests" in low or resp.status_code == 429:
        delay = check_queue.report_throttled()
        retry_after = delay
        if resp.status_code == 429:
            try:
                retry_after = max(delay, float(resp.headers.get("Retry-After", "0") or 0))
            except (TypeError, ValueError):
                pass
        _log_server_detail(email, resp.status_code, body)
        return _Attempt(
            "transient", "retry",
            f"🔄 RETRY: {email} - Server busy",
            retry_after=retry_after,
        )

    # "already taken" is the ONLY other real answer
    if "already taken" in low:
        check_queue.report_ok()
        return _Attempt("done", "taken", f"❌ TAKEN: {email}")

    # Rate limited / server hiccup -> always worth retrying
    if resp.status_code == 429 or resp.status_code >= 500:
        retry_after = 0.0
        try:
            retry_after = float(resp.headers.get("Retry-After", "0") or 0)
        except (TypeError, ValueError):
            retry_after = 0.0
        return _Attempt(
            "transient", "retry",
            f"🔄 RETRY: {email} - Server busy",
            retry_after=retry_after,
        )

    if resp.status_code == 200:
        try:
            data = resp.json()
        except Exception:
            # CDN / Cloudflare HTML page instead of JSON -> transient
            return _Attempt("transient", "retry", f"🔄 RETRY: {email} - Invalid response")
        if isinstance(data, dict) and any(k in data for k in _SUCCESS_KEYS):
            check_queue.report_ok()
            return _Attempt("done", "available", f"✅ AVAILABLE: {email}")
        # 200 JSON that we don't recognise -> do NOT guess "available"
        if any(m in low for m in _BAD_TOKEN_MARKERS):
            return _Attempt("transient", "retry", f"🔄 RETRY: {email} - Temporary failure", bad_token=True)
        return _Attempt("transient", "retry", f"🔄 RETRY: {email} - Unexpected response")

    # 4xx: bad token is common (expired / already used) -> refresh & retry
    if any(m in low for m in _BAD_TOKEN_MARKERS):
        return _Attempt(
            "transient", "retry",
            f"🔄 RETRY: {email} - Temporary failure",
            bad_token=True,
        )
    # Any other API error body -> permanent, surface ONLY a generic message
    _log_server_detail(email, resp.status_code, body)
    return _Attempt(
        "permanent", "error",
        f"⚠️ ERROR: {email} - {_safe_server_detail(body, resp.status_code)}",
    )


def check_single_email(email: str) -> dict:
    """
    Returns a dict:
      {
        "email": str,
        "status": "available" | "taken" | "invalid" | "wrong_domain"
                  | "timeout" | "error" | "retry",
        "message": str  # human readable with emoji
      }
    Transient failures are auto-retried (queue -> backoff -> queue).
    """
    email = (email or "").strip().lower()

    if "@" not in email:
        return {"email": email, "status": "invalid", "message": f"❌ INVALID: {email}"}

    domain_ok = any(d in email for d in SUPPORTED_DOMAINS)
    if not domain_ok:
        return {
            "email": email,
            "status": "wrong_domain",
            "message": f"❌ WRONG DOMAIN: {email} (Only @hi2.in and @telegmail.com allowed)",
        }

    try:
        domain = email.split("@", 1)[1]
        prefix = email.split("@", 1)[0]
    except Exception:
        return {"email": email, "status": "invalid", "message": f"❌ INVALID: {email}"}

    last = _Attempt("permanent", "error", f"⚠️ ERROR: {email} - unknown")

    for attempt in range(1, MAX_ATTEMPTS + 1):
        token = token_pool.get_token()
        if not token:
            last = _Attempt(
                "transient", "error",
                f"⚠️ ERROR: {email} - Verification service busy, try again",
            )
            if attempt < MAX_ATTEMPTS:
                time.sleep(BACKOFF[min(attempt - 1, len(BACKOFF) - 1)])
            continue

        try:
            last = check_queue.run(
                lambda: _hit_api(email, domain, prefix, token),
                timeout=ATTEMPT_TIMEOUT,
            )
        except check_queue.QueueBusy:
            # Pipeline overloaded -> honest, no wasted credits downstream
            return {
                "email": email,
                "status": "retry",
                "message": f"🔄 BUSY: {email} - Server busy, please try again in a moment",
            }
        except Exception as e:
            # Never surface exception internals (may contain URLs/tokens)
            try:
                print(f"[checker] {email} exception: {type(e).__name__}")
            except Exception:
                pass
            last = _Attempt(
                "transient", "error",
                f"⚠️ ERROR: {email} - Temporary failure, try again",
            )

        if last.kind == "done":
            return {"email": email, "status": last.status, "message": last.message}
        if last.kind == "permanent":
            return {"email": email, "status": last.status, "message": last.message}

        # Global throttle already confirmed (2+ strikes) -> don't burn the
        # user's time on more attempts; cooldown handles recovery.
        if last.retry_after and check_queue.throttle_streak() >= 2:
            return {
                "email": email,
                "status": "retry",
                "message": f"🔄 BUSY: {email} - Server busy, please try again in a moment",
            }

        # transient -> refresh token if it was the culprit, then back off
        if last.bad_token:
            token_pool.invalidate_all()
        if attempt < MAX_ATTEMPTS:
            delay = BACKOFF[min(attempt - 1, len(BACKOFF) - 1)]
            delay = max(delay, last.retry_after or 0.0)
            time.sleep(delay)

    # Every attempt failed -> final status for the user
    return {"email": email, "status": last.status, "message": last.message}


def parse_emails(text: str) -> list:
    raw = []
    if "," in text:
        for part in text.split(","):
            part = part.strip()
            if part and "@" in part:
                raw.append(part.lower())
    else:
        for line in text.split("\n"):
            line = line.strip()
            if line and "@" in line:
                raw.append(line.lower())
    # preserve order, remove duplicates
    return list(dict.fromkeys(raw))


def check_bulk_emails(emails: list, max_workers: int = 3) -> list:
    """
    Check many emails concurrently from the user's perspective, while the
    GLOBAL queue still serialises the actual hi2.in traffic.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(check_single_email, e): e for e in emails}
        for future in as_completed(future_map):
            try:
                results.append(future.result(timeout=ATTEMPT_TIMEOUT * 2))
            except Exception:
                email = future_map[future]
                results.append(
                    {
                        "email": email,
                        "status": "error",
                        "message": f"⚠️ FAILED: {email} - System error",
                    }
                )
    return results
