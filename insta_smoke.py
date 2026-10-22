"""Smoke test for services/insta_lookup.py (laptop)."""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config
from services import proxy_pool
from services.insta_lookup import check_insta_email

n = proxy_pool.load()
print(f"proxy pool loaded: {n} (INSTA_PROXY_FIRST={config.INSTA_PROXY_FIRST})")

tests = ["oxjzps@hi2.in", "zzqxfakenotexist999@hi2.in"]
for email in tests:
    r = check_insta_email(email)
    print(f"{email} -> {r['status']} via {r['via']}", flush=True)
print("SMOKE DONE")
