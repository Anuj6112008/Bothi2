"""vps_insta_test.py - VPS-side live test of the Instagram lookup,
PROXY-FIRST (the whole point: the VPS datacenter IP must not be used).
Runs: registered email, fake email, and prints the pool stats used.
"""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config
from services import proxy_pool
from services.insta_lookup import check_insta_email

n = proxy_pool.load()
print(f"pool loaded: {n}, usable: {proxy_pool.usable_count()}", flush=True)
print(f"INSTA_PROXY_FIRST={config.INSTA_PROXY_FIRST} "
      f"attempts={config.INSTA_MAX_ATTEMPTS} "
      f"interval={config.INSTA_MIN_INTERVAL}s", flush=True)

tests = ["oxjzps@hi2.in", "zzqxfakenotexist999@hi2.in"]
for email in tests:
    r = check_insta_email(email)
    print(f"{email} -> {r['status']} via {r['via']}", flush=True)

print("pool after:", proxy_pool.stats(), flush=True)
print("VPS TEST DONE", flush=True)
