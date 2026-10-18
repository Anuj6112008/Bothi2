"""
reCAPTCHA solver for hi2.in – moved out of checker.py so the token pool
and the checker can both import it without circular imports.
"""
import requests
import config


def recaptcha():
    """Solve the invisible reCAPTCHA used by hi2.in. Returns token str or None."""
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
        # Server-side only: never print token/URL internals
        print(f"Recaptcha error: {type(e).__name__}")
        return None
