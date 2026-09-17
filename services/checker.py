"""
Email availability checker – preserves original logic from the provided main.py.
"""
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
import config


def recaptcha():
    try:
        key = config.RECAPTCHA_SITE_KEY or "6LfEUPkgAAAAAKTgbMoewQkWBEQhO2VPL4QviKct"
        anuj = "aHR0cHM6Ly9oaTIuaW46NDQz"
        ps = (
            f"https://www.google.com/recaptcha/api2/anchor?ar=1&k={key}"
            f"&co={anuj}&hl=en&v=XrIDux0s7SoNe6_IHkjGC92W&size=invisible"
        ).split("?")[1]
        tokval = (
            requests.get(
                f"https://www.google.com/recaptcha/enterprise/anchor?{ps}",
                timeout=30,
            )
            .text.split('recaptcha-token" value="')[1]
            .split('"')[0]
        )
        response = requests.post(
            "https://www.google.com/recaptcha/enterprise/reload",
            data=(
                f"v={ps.split('v=')[1].split('&')[0]}&reason=q&c={tokval}"
                f"&k={key}&co={anuj}&hl=en&size=invisible"
            ),
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": f"https://www.google.com/recaptcha/enterprise/anchor?{ps}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=30,
        )
        return response.text.split('resp","')[1].split('"')[0]
    except Exception as e:
        print(f"Recaptcha error: {e}")
        return None


SUPPORTED_DOMAINS = ("@hi2.in", "@telegmail.com")


def check_single_email(email: str) -> dict:
    """
    Returns a dict:
      {
        "email": str,
        "status": "available" | "taken" | "invalid" | "wrong_domain" | "timeout" | "error" | "retry",
        "message": str  # human readable with emoji
      }
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
        domain = email.split("@")[1]
        prefix = email.split("@")[0]
        time.sleep(0.5)

        token = recaptcha()
        response = requests.post(
            "https://hi2.in/api/custom",
            data={"domain": domain, "prefix": prefix, "recaptcha": token},
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json, text/plain, */*",
                "authorization": "Basic bnVsbA==",
                "Origin": "https://hi2.in",
                "Referer": "https://hi2.in/",
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=25,
        )

        try:
            response_json = response.json()
            response_text = str(response_json).lower()
            if "already taken" in response_text:
                return {"email": email, "status": "taken", "message": f"❌ TAKEN: {email}"}
            return {"email": email, "status": "available", "message": f"✅ AVAILABLE: {email}"}
        except Exception:
            response_text = response.text.lower()
            if "already taken" in response_text:
                return {"email": email, "status": "taken", "message": f"❌ TAKEN: {email}"}
            if "true" in response_text or "false" in response_text:
                return {"email": email, "status": "available", "message": f"✅ AVAILABLE: {email}"}
            return {
                "email": email,
                "status": "retry",
                "message": f"⚠️ RETRY: {email} - Invalid response",
            }

    except requests.exceptions.Timeout:
        return {"email": email, "status": "timeout", "message": f"⏱️ TIMEOUT: {email} - Server slow"}
    except requests.exceptions.ConnectionError:
        return {
            "email": email,
            "status": "error",
            "message": f"🔌 CONNECTION ERROR: {email} - Network issue",
        }
    except Exception as e:
        return {
            "email": email,
            "status": "error",
            "message": f"⚠️ ERROR: {email} - {str(e)[:50]}",
        }


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
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(check_single_email, e): e for e in emails}
        for future in as_completed(future_map):
            try:
                results.append(future.result(timeout=40))
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
