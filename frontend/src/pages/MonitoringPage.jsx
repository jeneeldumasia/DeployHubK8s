import { useState, useEffect, useCallback } from "react";

const apiBase = "/api";

/* ── Data hooks ─────────────────────────────────────────────────────────────── */

function useSystemStats(intervalMs = 10000) {
  const [data, setData]       = useState(null);
  const [error, setError]     = useState(null);
  const [loading, setLoading] = useState(true);

  const fetch_ = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/system`);
      if (!res.ok) throw new Error("Failed to fetch system stats");
      setData(await res.json());
      setError(null);
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    fetch_();
    const id = setInterval(fetch_, intervalMs);
    return () => clearInterval(id);
  }, [fetch_, intervalMs]);

  return { data, error, loading };
}

function usePersistentStats(intervalMs = 15000) {
  const [data, setData]   = useState(null);
  const [error, setError] = useState(null);

  const fetch_ = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/stats`);
      if (!res.ok) throw new Error("Failed to fetch stats");
      setData(await res.json());
      setError(null);
    } catch (e) { setError(e.message); }
  }, []);

  useEffect(() => {
    fetch_();
    const id = setInterval(fetch_, intervalMs);
    return () => clearInterval(id);
  }, [fetch_, intervalMs]);

  return { data, error };
}

function parsePrometheusText(text) {
  const result = {};
  for (const line of text.split("\n")) {
    if (line.startsWith("#") || !line.trim()) continue;
    const spaceIdx = line.lastIndexOf(" ");
    const labelEnd = line.indexOf("{") === -1 ? spaceIdx : line.indexOf("{");
    const name = line.slice(0, labelEnd).trim();
    const value = parseFloat(line.slice(spaceIdx + 1));
    if (isNaN(value)) continue;
    const labelStr = line.slice(labelEnd, spaceIdx);
    const labels = {};
    const labelMatch = labelStr.match(/\{([^}]*)\}/);
    if (labelMatch) {
      for (const pair of labelMatch[1].split(",")) {
        const [k, v] = pair.split("=");
        if (k && v) labels[k.trim()] = v.replace(/"/g, "").trim();
      }
    }
    if (!result[name]) result[name] = [];
    result[name].push({ labels, value });
  }
  return result;
}

function useMetrics(intervalMs = 15000) {
  const [metrics, setMetrics] = useState(null);
  const [error, setError]     = useState(null);

  const fetch_ = useCallback(async () => {
    try {
      const res = await fetch("/metrics");
      if (!res.ok) throw new Error("Failed to fetch metrics");
      setMetrics(parsePrometheusText(await res.text()));
      setError(null);
    } catch (e) { setError(e.message); }
  }, []);

  useEffect(() => {
    fetch_();
    const id = setInterval(fetch_, intervalMs);
    return () => clearInterval(id);
  }, [fetch_, intervalMs]);

  return { metrics, error };
}

function usePodHealth(projectId, intervalMs = 10000) {
  const [data, setData]       = useState(null);
  const [logs, setLogs]       = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState(null);

  const fetchHealth = useCallback(async (id) => {
    if (!id) { setData(null); setLogs([]); return; }
    setLoading(true);
    try {
      const [healthRes, logsRes] = await Promise.all([
        fetch(`${apiBase}/projects/${id}/health`),
        fetch(`${apiBase}/logs/${id}`),
      ]);
      if (healthRes.ok) setData(await healthRes.json());
      if (logsRes.ok) {
        const l = await logsRes.json();
        setLogs((l.runtime_logs || []).slice(-30));
      }
      setError(null);
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    fetchHealth(projectId);
    if (!projectId) return undefined;
    const id = setInterval(() => fetchHealth(projectId), intervalMs);
    return () => clearInterval(id);
  }, [projectId, fetchHealth, intervalMs]);

  return { data, logs, loading, error };
}

/* ── Helpers ────────────────────────────────────────────────────────────────── */

function metricSum(metrics, name) {
  return (metrics?.[name] ?? []).reduce((s, e) => s + e.value, 0);
}

function metricByLabel(metrics, name, labelKey) {
  return (metrics?.[name] ?? []).map(e => ({
    label: e.labels[labelKey] ?? "—",
    value: e.value,
  }));
}

function parseMi(memStr) {
  if (!memStr) return null;
  const n = parseInt(memStr);
  return isNaN(n) ? null : n;
}

function parseMilli(cpuStr) {
  if (!cpuStr) return null;
  const n = parseInt(cpuStr);
  return isNaN(n) ? null : n;
}

/* ── Sub-components ─────────────────────────────────────────────────────────── */

function StatTile({ label, value, sub, accent }) {
  return (
    <div className="stat-card" style={accent ? { borderColor: accent, boxShadow: `0 0 0 1px ${accent}22` } : {}}>
      <span className="stat-label">{label}</span>
      <span className="stat-value" style={accent ? { color: accent } : {}}>{value ?? "—"}</span>
      {sub && <span className="stat-sub">{sub}</span>}
    </div>
  );
}

function StatusDot({ ok }) {
  return (
    <span style={{
      display: "inline-block", width: 8, height: 8, borderRadius: "50%",
      background: ok ? "var(--status-running)" : "var(--status-failed)",
      marginRight: "0.5rem", flexShrink: 0,
    }} />
  );
}

function MetricRow({ label, value, unit = "" }) {
  return (
    <div style={{
      display: "flex", justifyContent: "space-between", alignItems: "center",
      padding: "0.6rem 0", borderBottom: "1px solid var(--border)", fontSize: "0.85rem",
    }}>
      <span style={{ color: "var(--text-secondary)" }}>{label}</span>
      <span style={{ fontFamily: "'JetBrains Mono', monospace", color: "var(--accent-primary)", fontWeight: 700 }}>
        {typeof value === "number" ? value.toFixed(value < 10 ? 3 : 0) : value}{unit}
      </span>
    </div>
  );
}

function ExternalLink({ href, label, description, port }) {
  return (
    <a href={href} target="_blank" rel="noreferrer" style={{ textDecoration: "none" }}>
      <div
        className="stat-card"
        style={{ cursor: "pointer", transition: "border-color 0.15s, box-shadow 0.15s", flexDirection: "row", alignItems: "center", gap: "1rem" }}
        onMouseEnter={e => e.currentTarget.style.borderColor = "var(--accent-primary)"}
        onMouseLeave={e => e.currentTarget.style.borderColor = ""}
      >
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 800, fontSize: "0.9rem", color: "var(--text-primary)" }}>{label}</div>
          <div style={{ fontSize: "0.78rem", color: "var(--text-muted)", marginTop: "0.2rem" }}>{description}</div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: "0.2rem" }}>
          <span style={{ fontSize: "0.68rem", fontWeight: 800, textTransform: "uppercase", color: "var(--text-muted)", letterSpacing: "0.05em" }}>
            :{port}
          </span>
          <span style={{ fontSize: "0.8rem", color: "var(--accent-primary)" }}>Open ↗</span>
        </div>
      </div>
    </a>
  );
}

/* ── PhaseBadge ─────────────────────────────────────────────────────────────── */
function PhaseBadge({ phase, ready }) {
  const isRunning = phase === "Running" && ready;
  const isPending = phase === "Pending" || (phase === "Running" && !ready);
  const color = isRunning ? "var(--status-running)" : isPending ? "var(--status-building)" : "var(--status-failed)";
  const label = isRunning ? "Running" : isPending ? "Starting…" : phase || "Unknown";
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: "0.4rem",
      padding: "0.2rem 0.65rem", borderRadius: "999px",
      background: `${color}22`, border: `1px solid ${color}`,
      fontSize: "0.78rem", fontWeight: 700, color,
    }}>
      <span style={{
        width: 7, height: 7, borderRadius: "50%", background: color,
        boxShadow: isRunning ? `0 0 0 3px ${color}44` : "none",
        animation: isRunning ? "pulse 2s infinite" : "none",
      }} />
      {label}
    </span>
  );
}

/* ── MiniBar ─────────────────────────────────────────────────────────────────── */
function MiniBar({ label, value, max, unit, color = "var(--accent-primary)" }) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0;
  const warn = pct > 80;
  const barColor = warn ? "var(--status-failed)" : pct > 60 ? "var(--status-building)" : color;
  return (
    <div style={{ marginBottom: "0.75rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.3rem", fontSize: "0.78rem" }}>
        <span style={{ color: "var(--text-secondary)" }}>{label}</span>
        <span style={{ color: barColor, fontFamily: "monospace", fontWeight: 700 }}>
          {value}{unit} / {max}{unit}
        </span>
      </div>
      <div style={{ height: 6, background: "var(--border)", borderRadius: 3, overflow: "hidden" }}>
        <div style={{
          height: "100%", width: `${pct}%`, background: barColor,
          borderRadius: 3, transition: "width 0.5s ease",
        }} />
      </div>
    </div>
  );
}

/* ── AppHealthSection ───────────────────────────────────────────────────────── */
function AppHealthSection({ projects }) {
  const runningProjects = projects.filter(p => ["running", "failed", "building"].includes(p.status));
  const [selectedId, setSelectedId] = useState(runningProjects[0]?.id || "");
  const { data: health, logs, loading, error } = usePodHealth(selectedId, 10000);
  const host = window.location.hostname;

  const selectedProject = projects.find(p => p.id === selectedId);
  const pod = health?.pod;

  const cpuVal  = parseMilli(pod?.cpu);
  const memVal  = parseMi(pod?.memory);

  // Update selection when projects list changes
  useEffect(() => {
    if (!selectedId && runningProjects.length > 0) setSelectedId(runningProjects[0].id);
  }, [projects]);

  const grafanaUrl = pod
    ? `http://${host}:3091/d/app-overview/app-overview?var-app=${encodeURIComponent(pod.name)}`
    : `http://${host}:3091`;

  return (
    <div className="panel" style={{ marginBottom: "1.5rem" }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.25rem", flexWrap: "wrap", gap: "0.75rem" }}>
        <div>
          <h2 style={{ fontSize: "1rem", fontWeight: 800, margin: 0 }}>App Health</h2>
          <p style={{ fontSize: "0.78rem", color: "var(--text-muted)", marginTop: "0.2rem" }}>Live pod status, resource usage, and runtime logs per deployed app.</p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          {runningProjects.length > 0 && (
            <select
              value={selectedId}
              onChange={e => setSelectedId(e.target.value)}
              style={{
                background: "var(--surface)", color: "var(--text-primary)",
                border: "1px solid var(--border)", borderRadius: 8,
                padding: "0.4rem 0.75rem", fontSize: "0.85rem", cursor: "pointer",
              }}
            >
              {runningProjects.map(p => (
                <option key={p.id} value={p.id}>
                  {p.service_name || p.repo_url?.split("/").pop() || p.id}
                </option>
              ))}
            </select>
          )}
          {pod && (
            <a
              href={grafanaUrl}
              target="_blank"
              rel="noreferrer"
              style={{
                display: "inline-flex", alignItems: "center", gap: "0.4rem",
                padding: "0.4rem 0.9rem", borderRadius: 8, fontSize: "0.8rem", fontWeight: 700,
                background: "var(--accent-primary)", color: "#fff", textDecoration: "none",
                transition: "opacity 0.15s",
              }}
              onMouseEnter={e => e.currentTarget.style.opacity = "0.85"}
              onMouseLeave={e => e.currentTarget.style.opacity = "1"}
            >
              Open in Grafana ↗
            </a>
          )}
        </div>
      </div>

      {runningProjects.length === 0 ? (
        <p style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>No deployed apps yet.</p>
      ) : loading && !health ? (
        <p style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>Loading…</p>
      ) : error ? (
        <p className="error inline-error">{error}</p>
      ) : !pod ? (
        <p style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>Pod not found or not yet deployed.</p>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1.5rem" }}>
          {/* Left: status + resources + events */}
          <div>
            {/* Status row */}
            <div style={{ display: "flex", alignItems: "center", gap: "1rem", marginBottom: "1.25rem", flexWrap: "wrap" }}>
              <PhaseBadge phase={pod.phase} ready={pod.ready} />
              {pod.restart_count > 0 && (
                <span style={{
                  padding: "0.15rem 0.55rem", borderRadius: "999px",
                  background: "var(--status-building)22", border: "1px solid var(--status-building)",
                  fontSize: "0.75rem", fontWeight: 700, color: "var(--status-building)",
                }}>
                  ↺ {pod.restart_count} restart{pod.restart_count !== 1 ? "s" : ""}
                </span>
              )}
              <span style={{ fontSize: "0.75rem", color: "var(--text-muted)", fontFamily: "monospace" }}>
                {pod.name}
              </span>
            </div>

            {/* Resource bars */}
            {cpuVal !== null ? (
              <MiniBar label="CPU" value={cpuVal} max={1000} unit="m" />
            ) : (
              <div style={{ fontSize: "0.78rem", color: "var(--text-muted)", marginBottom: "0.75rem" }}>
                CPU — metrics-server data unavailable
              </div>
            )}
            {memVal !== null ? (
              <MiniBar label="Memory" value={memVal} max={512} unit="Mi" color="var(--accent-secondary, #a78bfa)" />
            ) : (
              <div style={{ fontSize: "0.78rem", color: "var(--text-muted)", marginBottom: "0.75rem" }}>
                Memory — metrics-server data unavailable
              </div>
            )}

            {/* Warning events */}
            {pod.events && pod.events.length > 0 && (
              <div style={{ marginTop: "1rem" }}>
                <div style={{ fontSize: "0.72rem", fontWeight: 800, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--status-failed)", marginBottom: "0.4rem" }}>
                  ⚠ K8s Warning Events
                </div>
                {pod.events.map((ev, i) => (
                  <div key={i} style={{
                    fontSize: "0.78rem", color: "var(--text-secondary)",
                    padding: "0.35rem 0.5rem", borderLeft: "2px solid var(--status-failed)",
                    background: "var(--status-failed)0a", borderRadius: "0 4px 4px 0",
                    marginBottom: "0.35rem", fontFamily: "monospace",
                  }}>
                    {ev}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Right: runtime log tail */}
          <div>
            <div style={{ fontSize: "0.72rem", fontWeight: 800, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-muted)", marginBottom: "0.5rem" }}>
              Runtime Logs (last 30 lines)
            </div>
            <pre style={{
              background: "var(--surface)", border: "1px solid var(--border)",
              borderRadius: 8, padding: "0.75rem 1rem",
              fontSize: "0.72rem", lineHeight: 1.55, fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
              overflowY: "auto", maxHeight: 260,
              color: "var(--text-secondary)", margin: 0,
              whiteSpace: "pre-wrap", wordBreak: "break-all",
            }}>
              {logs.length > 0
                ? logs.join("\n")
                : <span style={{ color: "var(--text-muted)" }}>No runtime logs yet.</span>
              }
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Main page ──────────────────────────────────────────────────────────────── */
export default function MonitoringPage({ projects }) {
  const { data: sys, error: sysErr, loading } = useSystemStats(10000);
  const { data: stats, error: statsErr }       = usePersistentStats(15000);
  const { metrics, error: metErr }             = useMetrics(15000);

  const host = window.location.hostname;

  const totalDeployments = stats?.total      ?? 0;
  const totalSuccesses   = stats?.successful ?? 0;
  const totalFailures    = stats?.failed     ?? 0;
  const totalRollbacks   = stats?.rolled_back ?? 0;
  const avgDuration      = stats?.avg_duration_seconds;

  const hcFailures      = metricSum(metrics, "deployhub_health_check_failures_total");
  const httpTotal       = metricSum(metrics, "http_requests_total");
  const deployByAction  = metricByLabel(metrics, "deployhub_deployments_total", "action");
  const failuresByPhase = metricByLabel(metrics, "deployhub_deployment_failures_total", "phase");
  const httpByPath      = metricByLabel(metrics, "http_requests_total", "path")
    .sort((a, b) => b.value - a.value).slice(0, 8);
  const podRestarts     = metricByLabel(metrics, "deployhub_pod_restarts_total", "pod_name");

  const successRate = totalDeployments > 0
    ? ((totalSuccesses / totalDeployments) * 100).toFixed(1)
    : "—";

  return (
    <div>
      <div className="page-header">
        <h1>Monitoring</h1>
        <p>Live system health, per-app pod status, deployment metrics, and links to Grafana &amp; Prometheus.</p>
      </div>

      {(sysErr || metErr || statsErr) && (
        <p className="error inline-error" style={{ marginBottom: "1.5rem" }}>
          {sysErr || statsErr || metErr}
        </p>
      )}

      {/* ── System health ── */}
      <div className="panel" style={{ marginBottom: "1.5rem" }}>
        <h2 style={{ fontSize: "1rem", fontWeight: 800, marginBottom: "1.25rem" }}>System Health</h2>
        {loading ? (
          <p style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>Loading…</p>
        ) : sys ? (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "0.75rem" }}>
            <div className="stat-card" style={{ flexDirection: "row", alignItems: "center", gap: "0.5rem" }}>
              <StatusDot ok={sys.mongodb_available} />
              <div>
                <div className="stat-label">MongoDB</div>
                <div style={{ fontWeight: 700, fontSize: "0.85rem", color: sys.mongodb_available ? "var(--status-running)" : "var(--status-failed)" }}>
                  {sys.mongodb_available ? "Connected" : "Unavailable"}
                </div>
              </div>
            </div>
            <div className="stat-card" style={{ flexDirection: "row", alignItems: "center", gap: "0.5rem" }}>
              <StatusDot ok={sys.docker_available} />
              <div>
                <div className="stat-label">Runtime</div>
                <div style={{ fontWeight: 700, fontSize: "0.85rem", color: sys.docker_available ? "var(--status-running)" : "var(--status-failed)" }}>
                  {sys.docker_available ? "Connected" : "Unavailable"}
                </div>
              </div>
            </div>
            <StatTile label="Backend Version" value={`v${sys.backend_version}`} />
            <StatTile label="Active Deployments" value={sys.active_deployments} sub="currently building" />
            <StatTile label="Queued" value={sys.queued_deployments} sub="waiting to build" />
            <StatTile label="Running Apps" value={sys.running_container_count} accent="var(--status-running)" />
          </div>
        ) : null}
      </div>

      {/* ── App Health (per-project pod visibility) ── */}
      <AppHealthSection projects={projects} />

      {/* ── Deployment metrics ── */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "1.25rem", marginBottom: "1.5rem" }}>
        <StatTile label="Total Deployments" value={totalDeployments} sub="all time (persistent)" />
        <StatTile label="Successful" value={totalSuccesses} sub={`${successRate}% success rate`} accent="var(--status-running)" />
        <StatTile label="Failed" value={totalFailures} sub="all phases" accent={totalFailures > 0 ? "var(--status-failed)" : undefined} />
        <StatTile label="Rolled Back" value={totalRollbacks} sub="auto-rollbacks triggered" accent={totalRollbacks > 0 ? "var(--status-building)" : undefined} />
        <StatTile label="Avg Build Time" value={avgDuration != null ? `${avgDuration}s` : "—"} sub="across all deployments" />
        <StatTile label="HTTP Requests" value={httpTotal.toFixed(0)} sub="this session (resets on restart)" />
      </div>

      {/* ── Breakdown tables ── */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "1.5rem", marginBottom: "1.5rem" }}>
        <div className="panel">
          <h3 style={{ fontSize: "0.8rem", fontWeight: 800, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-muted)", marginBottom: "0.5rem" }}>
            Deployments by Action
          </h3>
          {deployByAction.length > 0
            ? deployByAction.map(({ label, value }) => <MetricRow key={label} label={label} value={value} />)
            : <p style={{ color: "var(--text-muted)", fontSize: "0.82rem", paddingTop: "0.5rem" }}>No data yet</p>
          }
        </div>

        <div className="panel">
          <h3 style={{ fontSize: "0.8rem", fontWeight: 800, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-muted)", marginBottom: "0.5rem" }}>
            Failures by Phase
          </h3>
          {failuresByPhase.length > 0
            ? failuresByPhase.map(({ label, value }) => <MetricRow key={label} label={label} value={value} />)
            : <p style={{ color: "var(--text-muted)", fontSize: "0.82rem", paddingTop: "0.5rem" }}>No failures recorded</p>
          }
        </div>

        <div className="panel">
          <h3 style={{ fontSize: "0.8rem", fontWeight: 800, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-muted)", marginBottom: "0.5rem" }}>
            Pod Restart Counts
          </h3>
          {podRestarts.length > 0
            ? podRestarts.map(({ label, value }) => (
                <MetricRow key={label} label={label.replace("deployhub-", "")} value={value} />
              ))
            : <p style={{ color: "var(--text-muted)", fontSize: "0.82rem", paddingTop: "0.5rem" }}>No pods tracked</p>
          }
        </div>
      </div>

      {/* ── Top HTTP paths ── */}
      <div className="panel" style={{ marginBottom: "1.5rem" }}>
        <h3 style={{ fontSize: "0.8rem", fontWeight: 800, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-muted)", marginBottom: "0.5rem" }}>
          Top API Paths (by request count)
        </h3>
        {httpByPath.length > 0
          ? httpByPath.map(({ label, value }) => <MetricRow key={label} label={label} value={value} />)
          : <p style={{ color: "var(--text-muted)", fontSize: "0.82rem", paddingTop: "0.5rem" }}>No HTTP data yet</p>
        }
      </div>

      {/* ── External tools ── */}
      <div className="panel">
        <h2 style={{ fontSize: "1rem", fontWeight: 800, marginBottom: "1.25rem" }}>Observability Stack</h2>
        <p style={{ fontSize: "0.82rem", color: "var(--text-secondary)", marginBottom: "1.25rem" }}>
          Prometheus, Grafana, and Loki are deployed in the cluster. Grafana is accessible without login (anonymous viewer).
        </p>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: "1rem" }}>
          <ExternalLink
            href={`http://${host}:3091/d/deployhub-overview/deployhub-overview`}
            label="Grafana — DeployHub Overview"
            description="Deployment rates, HTTP latency, pod restarts across the platform"
            port="3091"
          />
          <ExternalLink
            href={`http://${host}:3091/d/app-overview/app-overview`}
            label="Grafana — App Overview"
            description="Per-app log volume, pod restarts, and live Loki logs — filterable by app"
            port="3091"
          />
          <ExternalLink
            href={`http://${host}:3090`}
            label="Prometheus"
            description="Raw metrics explorer and alert rule status"
            port="3090"
          />
          <ExternalLink
            href={`http://${host}:3090/alerts`}
            label="Alert Rules"
            description="4 active rules: backend down, high failure rate, health check failures, pod restarts"
            port="3090/alerts"
          />
          <ExternalLink
            href="/metrics"
            label="Raw /metrics"
            description="Prometheus scrape endpoint — all DeployHub and HTTP metrics"
            port="metrics"
          />
        </div>
      </div>
    </div>
  );
}
