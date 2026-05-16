/**
 * DeployHub — k6 Stress Test
 *
 * Targets:
 *   - DeployHub backend API  → http://54.235.38.60:3081
 *   - Deployed app (me)      → http://54.235.38.60:3100
 *
 * Stages:
 *   0–1 min   ramp from 0 → 20 VUs   (warm up)
 *   1–3 min   hold at 50 VUs          (sustained load)
 *   3–4 min   spike to 100 VUs        (stress)
 *   4–5 min   hold at 100 VUs         (soak at peak)
 *   5–6 min   ramp down to 0          (cool down)
 *
 * Run:
 *   k6 run scripts/stress-test.js
 *
 * Install k6 on the EC2 node:
 *   sudo snap install k6
 *   OR
 *   sudo gpg --no-default-keyring --keyring /usr/share/keyrings/k6-archive-keyring.gpg \
 *     --keyserver hkp://keyserver.ubuntu.com:80 --recv-keys C5AD17C747E3415A3642D57D77C6C491D6AC1D69
 *   echo "deb [signed-by=/usr/share/keyrings/k6-archive-keyring.gpg] https://dl.k6.io/deb stable main" \
 *     | sudo tee /etc/apt/sources.list.d/k6.list
 *   sudo apt-get update && sudo apt-get install k6
 */

import http from "k6/http";
import { check, sleep, group } from "k6";
import { Rate, Trend, Counter } from "k6/metrics";

/* ── custom metrics ─────────────────────────────────────────── */
const errorRate       = new Rate("error_rate");
const appLatency      = new Trend("app_latency_ms",  true);
const apiLatency      = new Trend("api_latency_ms",  true);
const totalRequests   = new Counter("total_requests");

/* ── targets ────────────────────────────────────────────────── */
const API = "http://54.235.38.60:3081";
const APP = "http://54.235.38.60:3100";

/* ── thresholds — test FAILS if these are breached ─────────── */
export const options = {
  stages: [
    { duration: "1m",  target: 20  },   // warm up
    { duration: "2m",  target: 50  },   // sustained
    { duration: "1m",  target: 100 },   // spike
    { duration: "1m",  target: 100 },   // soak at peak
    { duration: "1m",  target: 0   },   // cool down
  ],
  thresholds: {
    // 95% of API requests must complete under 500ms
    "api_latency_ms":  ["p(95)<500"],
    // 95% of app requests must complete under 1000ms
    "app_latency_ms":  ["p(95)<1000"],
    // Error rate must stay below 5%
    "error_rate":      ["rate<0.05"],
    // Overall http failure rate
    "http_req_failed": ["rate<0.05"],
  },
};

/* ── main VU loop ───────────────────────────────────────────── */
export default function () {

  /* 1. Hit the deployed app */
  group("deployed_app", () => {
    const res = http.get(APP, { timeout: "10s" });
    const ok  = check(res, {
      "app: status 2xx": (r) => r.status >= 200 && r.status < 400,
      "app: not empty":  (r) => r.body && r.body.length > 0,
    });
    errorRate.add(!ok);
    appLatency.add(res.timings.duration);
    totalRequests.add(1);
  });

  sleep(0.1);

  /* 2. Hit the DeployHub health endpoint */
  group("api_health", () => {
    const res = http.get(`${API}/health`, { timeout: "5s" });
    const ok  = check(res, {
      "api /health: 200":        (r) => r.status === 200,
      "api /health: status ok":  (r) => {
        try { return JSON.parse(r.body).status === "ok"; } catch { return false; }
      },
    });
    errorRate.add(!ok);
    apiLatency.add(res.timings.duration);
    totalRequests.add(1);
  });

  sleep(0.1);

  /* 3. Hit the projects list */
  group("api_projects", () => {
    const res = http.get(`${API}/api/projects`, { timeout: "5s" });
    const ok  = check(res, {
      "api /projects: 200":   (r) => r.status === 200,
      "api /projects: array": (r) => {
        try { return Array.isArray(JSON.parse(r.body)); } catch { return false; }
      },
    });
    errorRate.add(!ok);
    apiLatency.add(res.timings.duration);
    totalRequests.add(1);
  });

  sleep(0.1);

  /* 4. Hit the system endpoint */
  group("api_system", () => {
    const res = http.get(`${API}/api/system`, { timeout: "5s" });
    const ok  = check(res, {
      "api /system: 200": (r) => r.status === 200,
    });
    errorRate.add(!ok);
    apiLatency.add(res.timings.duration);
    totalRequests.add(1);
  });

  sleep(0.2);
}

/* ── summary printed after the run ─────────────────────────── */
export function handleSummary(data) {
  const passed = Object.values(data.metrics)
    .every((m) => !m.thresholds || Object.values(m.thresholds).every((t) => !t.ok === false));

  console.log("\n══════════════════════════════════════════");
  console.log("  DeployHub Stress Test — Summary");
  console.log("══════════════════════════════════════════");
  console.log(`  Total requests : ${data.metrics.total_requests?.values?.count ?? "—"}`);
  console.log(`  Error rate     : ${((data.metrics.error_rate?.values?.rate ?? 0) * 100).toFixed(2)}%`);
  console.log(`  API p95 latency: ${data.metrics.api_latency_ms?.values?.["p(95)"]?.toFixed(1) ?? "—"} ms`);
  console.log(`  App p95 latency: ${data.metrics.app_latency_ms?.values?.["p(95)"]?.toFixed(1) ?? "—"} ms`);
  console.log(`  Peak VUs       : ${data.metrics.vus_max?.values?.max ?? "—"}`);
  console.log("══════════════════════════════════════════\n");

  return {
    stdout: JSON.stringify(data, null, 2),
  };
}
