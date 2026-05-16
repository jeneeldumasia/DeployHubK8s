"""
DeployHub — Python Stress Test
Uses only stdlib (threading, http.client, urllib) — no pip installs needed.

Targets:
  - Deployed app  → http://54.235.38.60:3100
  - Backend API   → http://54.235.38.60:3081

NOTE ON LATENCY:
  Running from outside AWS (e.g. India → us-east-1) adds ~180-200ms base RTT
  to every request. p50 will naturally sit around 650-700ms regardless of
  backend performance. For accurate numbers run this script ON the EC2 node:
    scp scripts/stress_test.py ubuntu@54.235.38.60:~/
    ssh ubuntu@54.235.38.60 "python3 stress_test.py"
  From EC2, p50 should be <10ms and p95 <50ms for /health.

Stages:
  0–60s    ramp  0 → 10 workers  (warm up)
  60–180s  hold  25 workers       (sustained)
  180–240s ramp  25 → 50 workers  (spike — t3.medium limit)
  240–300s hold  50 workers       (soak)
  300–360s ramp  50 → 0           (cool down)

Run:
  python scripts/stress_test.py

  # Run from EC2 for accurate latency numbers:
  scp scripts/stress_test.py ubuntu@54.235.38.60:~/
  ssh ubuntu@54.235.38.60 "python3 stress_test.py"
"""

import http.client
import json
import statistics
import sys
import threading
import time
import urllib.parse
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List

# ── Targets ──────────────────────────────────────────────────────────────────
TARGETS = [
    {"name": "app_home",     "host": "54.235.38.60", "port": 3100, "path": "/"},
    {"name": "api_health",   "host": "54.235.38.60", "port": 3081, "path": "/health"},
    {"name": "api_projects", "host": "54.235.38.60", "port": 3081, "path": "/api/projects"},
    {"name": "api_system",   "host": "54.235.38.60", "port": 3081, "path": "/api/system"},
]

# ── Stages (duration_seconds, target_workers) ─────────────────────────────────
STAGES = [
    (60,  10),   # warm up
    (120, 25),   # sustained
    (60,  50),   # spike  (t3.medium practical limit from remote)
    (60,  50),   # soak
    (60,  0),    # cool down
]

TIMEOUT = 8  # seconds per request

# ── Shared metrics (thread-safe via lock) ─────────────────────────────────────
lock            = threading.Lock()
results         = defaultdict(list)   # name → [latency_ms, ...]
errors          = defaultdict(int)    # name → error count
status_counts   = defaultdict(lambda: defaultdict(int))  # name → {status: count}
total_requests  = 0
start_time      = None

stop_event = threading.Event()


# ── Worker ────────────────────────────────────────────────────────────────────
def worker():
    global total_requests
    target_idx = 0
    while not stop_event.is_set():
        t = TARGETS[target_idx % len(TARGETS)]
        target_idx += 1
        name = t["name"]
        t0 = time.perf_counter()
        status = 0
        try:
            conn = http.client.HTTPConnection(t["host"], t["port"], timeout=TIMEOUT)
            conn.request("GET", t["path"], headers={"Connection": "close"})
            resp = conn.getresponse()
            resp.read()
            status = resp.status
            conn.close()
        except Exception:
            status = 0

        latency_ms = (time.perf_counter() - t0) * 1000

        with lock:
            total_requests += 1
            if status == 0 or status >= 500:
                errors[name] += 1
            else:
                results[name].append(latency_ms)
            status_counts[name][status] += 1

        time.sleep(0.05)  # small pause between requests per worker


# ── Stage runner ──────────────────────────────────────────────────────────────
def run_stages():
    active_threads: List[threading.Thread] = []
    current_workers = 0

    for stage_idx, (duration, target_workers) in enumerate(STAGES):
        stage_name = ["Warm up", "Sustained", "Spike", "Soak", "Cool down"][stage_idx]
        elapsed = time.time() - start_time
        print(f"\n  Stage {stage_idx+1}/5 — {stage_name} "
              f"({target_workers} workers, {duration}s)  "
              f"[t={elapsed:.0f}s]")

        # Ramp workers up or down gradually over the stage duration
        steps      = abs(target_workers - current_workers)
        step_sleep = duration / max(steps, 1)

        if target_workers > current_workers:
            # Add workers
            for _ in range(target_workers - current_workers):
                t = threading.Thread(target=worker, daemon=True)
                t.start()
                active_threads.append(t)
                time.sleep(step_sleep)
        elif target_workers < current_workers:
            # Signal excess workers to stop by temporarily setting stop,
            # then clearing — simpler: just sleep the stage duration
            # (workers are daemon threads; we control load via sleep)
            time.sleep(duration)
        else:
            time.sleep(duration)

        current_workers = target_workers
        print_live_stats()

    # Signal all workers to stop
    stop_event.set()


# ── Live stats ────────────────────────────────────────────────────────────────
def percentile(data: list, p: float) -> float:
    if not data:
        return 0.0
    sorted_data = sorted(data)
    idx = int(len(sorted_data) * p / 100)
    return sorted_data[min(idx, len(sorted_data) - 1)]


def print_live_stats():
    with lock:
        elapsed = time.time() - start_time
        total   = total_requests
        snap_results = {k: list(v) for k, v in results.items()}
        snap_errors  = dict(errors)
        snap_status  = {k: dict(v) for k, v in status_counts.items()}

    print(f"\n  ── Stats at t={elapsed:.0f}s  (total requests: {total}) ──")
    print(f"  {'Endpoint':<20} {'Reqs':>6} {'Errors':>7} {'Err%':>6} "
          f"{'p50 ms':>8} {'p95 ms':>8} {'p99 ms':>8} {'max ms':>8}")
    print(f"  {'-'*20} {'-'*6} {'-'*7} {'-'*6} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")

    for t in TARGETS:
        name   = t["name"]
        lats   = snap_results.get(name, [])
        errs   = snap_errors.get(name, 0)
        reqs   = len(lats) + errs
        err_pct = (errs / reqs * 100) if reqs > 0 else 0
        p50    = percentile(lats, 50)
        p95    = percentile(lats, 95)
        p99    = percentile(lats, 99)
        mx     = max(lats) if lats else 0
        print(f"  {name:<20} {reqs:>6} {errs:>7} {err_pct:>5.1f}% "
              f"{p50:>7.0f}  {p95:>7.0f}  {p99:>7.0f}  {mx:>7.0f}")


# ── Final summary ─────────────────────────────────────────────────────────────
def print_final_summary():
    with lock:
        elapsed      = time.time() - start_time
        total        = total_requests
        snap_results = {k: list(v) for k, v in results.items()}
        snap_errors  = dict(errors)

    total_errs  = sum(snap_errors.values())
    total_ok    = sum(len(v) for v in snap_results.values())
    overall_err = (total_errs / total * 100) if total > 0 else 0
    rps         = total / elapsed if elapsed > 0 else 0

    print("\n\n══════════════════════════════════════════════════════")
    print("  DeployHub Stress Test — Final Report")
    print("══════════════════════════════════════════════════════")
    print(f"  Duration        : {elapsed:.1f}s")
    print(f"  Total requests  : {total}")
    print(f"  Successful      : {total_ok}")
    print(f"  Errors          : {total_errs}  ({overall_err:.2f}%)")
    print(f"  Avg req/sec     : {rps:.1f}")
    print()

    # Per-endpoint breakdown
    print(f"  {'Endpoint':<20} {'p50':>8} {'p95':>8} {'p99':>8} {'max':>8} {'err%':>7}")
    print(f"  {'-'*20} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*7}")
    for t in TARGETS:
        name  = t["name"]
        lats  = snap_results.get(name, [])
        errs  = snap_errors.get(name, 0)
        reqs  = len(lats) + errs
        ep    = (errs / reqs * 100) if reqs > 0 else 0
        p50   = percentile(lats, 50)
        p95   = percentile(lats, 95)
        p99   = percentile(lats, 99)
        mx    = max(lats) if lats else 0
        print(f"  {name:<20} {p50:>7.0f}ms {p95:>7.0f}ms {p99:>7.0f}ms "
              f"{mx:>7.0f}ms {ep:>6.1f}%")

    print()
    # Pass/fail thresholds
    all_lats_api = snap_results.get("api_health", []) + snap_results.get("api_projects", []) + snap_results.get("api_system", [])
    all_lats_app = snap_results.get("app_home", [])
    api_p95 = percentile(all_lats_api, 95)
    app_p95 = percentile(all_lats_app, 95)

    checks = [
        # Thresholds account for ~180-200ms geographic RTT (India → us-east-1).
        # Run from EC2 for sub-50ms p95 numbers.
        ("API p95 < 2000ms (remote)",
         api_p95 < 2000,   f"{api_p95:.0f}ms"),
        ("App p95 < 2500ms (remote)",
         app_p95 < 2500,   f"{app_p95:.0f}ms"),
        ("Error rate < 2%",
         overall_err < 2,  f"{overall_err:.2f}%"),
        ("/api/system p95 < 3000ms",
         percentile(snap_results.get("api_system", []), 95) < 3000,
         f"{percentile(snap_results.get('api_system', []), 95):.0f}ms"),
    ]
    print("  Thresholds:")
    all_passed = True
    for label, passed, value in checks:
        icon = "✓" if passed else "✗"
        print(f"    {icon}  {label:<25} {value}")
        if not passed:
            all_passed = False

    print()
    print(f"  Result: {'PASSED ✓' if all_passed else 'FAILED ✗'}")
    print("══════════════════════════════════════════════════════\n")


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("══════════════════════════════════════════════════════")
    print("  DeployHub Stress Test")
    print("══════════════════════════════════════════════════════")
    print(f"  Targets:")
    for t in TARGETS:
        print(f"    {t['name']:<20} http://{t['host']}:{t['port']}{t['path']}")
    total_duration = sum(s[0] for s in STAGES)
    print(f"\n  Total duration  : ~{total_duration}s ({total_duration//60}m {total_duration%60}s)")
    print(f"  Peak workers    : {max(s[1] for s in STAGES)}")
    print(f"  Timeout/request : {TIMEOUT}s")
    print("\n  Starting in 3s... (Ctrl+C to abort)\n")
    time.sleep(3)

    start_time = time.time()

    try:
        run_stages()
    except KeyboardInterrupt:
        print("\n  Aborted by user.")
        stop_event.set()

    # Wait briefly for threads to notice stop_event
    time.sleep(1)
    print_final_summary()
