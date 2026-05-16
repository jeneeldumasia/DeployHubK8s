import { useState, useEffect, useCallback } from "react";

const apiBase = "/api";

/* ── tiny hook: fetch /api/system on mount + interval ── */
function useSystemStats(intervalMs = 10000) {
  const [data, setData]     = useState(null);
  const [error, setError]   = useState(null);
  const [loading, setLoading] = useState(true);

  const fetch_ = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/system`);
      if (!res.ok) throw new Error("Failed to fetch system stats");
      setData(await res.json());
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetch_();
    const id = setInterval(fetch_, intervalMs);
    return () => clearInterval(id);
  }, [fetch_, intervalMs]);

  return { data, error, loading, refresh: fetch_ };
}

/* ── parse raw prometheus text into { metricName: [{labels, value}] } ── */
function parsePrometheusText(text) {
  const result = {};
  for (const line of text.split("\n")) {
    if (line.startsWith("#") || !line.trim()) continue;
    const spaceIdx = line.lastIndexOf(" ");
    const labelEnd = line.indexOf("{") === -1 ? spaceIdx : line.indexOf("{");
    const name = line.slice(0, labelEnd).trim();
    const value = parseFloat(line.slice(spaceIdx + 1));
    if (isNaN(value)) continue;

    // parse labels
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
      const text = await res.text();
      setMetrics(parsePrometheusText(text));
      setError(null);
    } catch (e) {
      setError(e.message);
    }
  }, []);

  useEffect(() => {
    fetch_();
    const id = setInterval(fetch_, intervalMs);
    return () => clearInterval(id);
  }, [fetch_, intervalMs]);

  return { metrics, error };
}

/* ── helpers ── */
function metricSum(metrics, name) {
  return (metrics?.[name] ?? []).reduce((s, e) => s + e.value, 0);
}

function metricByLabel(metrics, name, labelKey) {
  return (metrics?.[name] ?? []).map(e => ({
    label: e.labels[labelKey] ?? "—",
    value: e.value,
  }));
}

/* ── sub-components ── */
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
      display: "inline-block",
      width: 8, height: 8,
      borderRadius: "50%",
      background: ok ? "var(--status-running)" : "var(--status-failed)",
      marginRight: "0.5rem",
      flexShrink: 0,
    }} />
  );
}

function MetricRow({ label, value, unit = "" }) {
  return (
    <div style={{
      display: "flex",
      justifyContent: "space-between",
      alignItems: "center",
      padding: "0.6rem 0",
      borderBottom: "1px solid var(--border)",
      fontSize: "0.85rem",
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
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      style={{ textDecoration: "none" }}
    >
      <div className="stat-card" style={{
        cursor: "pointer",
        transition: "border-color 0.15s, box-shadow 0.15s",
        flexDirection: "row",
        alignItems: "center",
        gap: "1rem",
      }}
        onMouseEnter={e => e.currentTarget.style.borderColor = "var(--accent-primary)"}
        onMouseLeave={e => e.currentTarget.style.borderColor = ""}
      >
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 800, fontSize: "0.9rem", color: "var(--text-primary)" }}>{label}</div>
          <div style={{ fontSize: "0.78rem", color: "var(--text-muted)", marginTop: "0.2rem" }}>{description}</div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: "0.2rem" }}>
          <span style={{
            fontSize: "0.68rem", fontWeight: 800, textTransform: "uppercase",
            color: "var(--text-muted)", letterSpacing: "0.05em",
          }}>
            :{port}
          </span>
          <span style={{ fontSize: "0.8rem", color: "var(--accent-primary)" }}>Open ↗</span>
        </div>
      </div>
    </a>
  );
}

/* ── main page ── */
export default function MonitoringPage({ projects }) {
  const { data: sys, error: sysErr, loading } = useSystemStats(10000);
  const { metrics, error: metErr } = useMetrics(15000);

  const host = window.location.hostname;

  const totalDeployments   = metricSum(metrics, "deployhub_deployments_total");
  const totalFailures      = metricSum(metrics, "deployhub_deployment_failures_total");
  const totalSuccesses     = metricSum(metrics, "deployhub_deployment_success_total");
  const hcFailures         = metricSum(metrics, "deployhub_health_check_failures_total");
  const httpTotal          = metricSum(metrics, "http_requests_total");
  const deployByAction     = metricByLabel(metrics, "deployhub_deployments_total", "action");
  const failuresByPhase    = metricByLabel(metrics, "deployhub_deployment_failures_total", "phase");
  const httpByPath         = metricByLabel(metrics, "http_requests_total", "path")
    .sort((a, b) => b.value - a.value)
    .slice(0, 8);
  const podRestarts        = metricByLabel(metrics, "deployhub_pod_restarts_total", "pod_name");

  const successRate = totalDeployments > 0
    ? ((totalSuccesses / totalDeployments) * 100).toFixed(1)
    : "—";

  return (
    <div>
      <div className="page-header">
        <h1>Monitoring</h1>
        <p>Live system health, deployment metrics, and links to Grafana &amp; Prometheus.</p>
      </div>

      {(sysErr || metErr) && (
        <p className="error inline-error" style={{ marginBottom: "1.5rem" }}>
          {sysErr || metErr}
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
                <div className="stat-label">{sys.docker_available !== undefined ? (window._k8sMode ? "Kubernetes" : "Runtime") : "Runtime"}</div>
                <div style={{ fontWeight: 700, fontSize: "0.85rem", color: sys.docker_available ? "var(--status-running)" : "var(--status-failed)" }}>
                  {sys.docker_available ? "Connected" : "Unavailable"}
                </div>
              </div>
            </div>
            <StatTile label="Backend Version" value={`v${sys.backend_version}`} />
            <StatTile label="Active Deployments" value={sys.active_deployments} sub="currently building" />
            <StatTile label="Queued" value={sys.queued_deployments} sub="waiting to build" />
            <StatTile label="Running Containers" value={sys.running_container_count} accent="var(--status-running)" />
          </div>
        ) : null}
      </div>

      {/* ── Deployment metrics ── */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "1.25rem", marginBottom: "1.5rem" }}>
        <StatTile label="Total Deployments" value={totalDeployments.toFixed(0)} sub="all time" />
        <StatTile label="Successful" value={totalSuccesses.toFixed(0)} sub={`${successRate}% success rate`} accent="var(--status-running)" />
        <StatTile label="Failed" value={totalFailures.toFixed(0)} sub="all phases" accent={totalFailures > 0 ? "var(--status-failed)" : undefined} />
        <StatTile label="Health Check Failures" value={hcFailures.toFixed(0)} sub="triggered rollback" accent={hcFailures > 0 ? "var(--status-building)" : undefined} />
        <StatTile label="HTTP Requests" value={httpTotal.toFixed(0)} sub="total handled" />
      </div>

      {/* ── Breakdown tables ── */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "1.5rem", marginBottom: "1.5rem" }}>
        {/* Deployments by action */}
        <div className="panel">
          <h3 style={{ fontSize: "0.8rem", fontWeight: 800, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-muted)", marginBottom: "0.5rem" }}>
            Deployments by Action
          </h3>
          {deployByAction.length > 0
            ? deployByAction.map(({ label, value }) => (
                <MetricRow key={label} label={label} value={value} />
              ))
            : <p style={{ color: "var(--text-muted)", fontSize: "0.82rem", paddingTop: "0.5rem" }}>No data yet</p>
          }
        </div>

        {/* Failures by phase */}
        <div className="panel">
          <h3 style={{ fontSize: "0.8rem", fontWeight: 800, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-muted)", marginBottom: "0.5rem" }}>
            Failures by Phase
          </h3>
          {failuresByPhase.length > 0
            ? failuresByPhase.map(({ label, value }) => (
                <MetricRow key={label} label={label} value={value} />
              ))
            : <p style={{ color: "var(--text-muted)", fontSize: "0.82rem", paddingTop: "0.5rem" }}>No failures recorded</p>
          }
        </div>

        {/* Pod restarts */}
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
          ? httpByPath.map(({ label, value }) => (
              <MetricRow key={label} label={label} value={value} />
            ))
          : <p style={{ color: "var(--text-muted)", fontSize: "0.82rem", paddingTop: "0.5rem" }}>No HTTP data yet</p>
        }
      </div>

      {/* ── External tools ── */}
      <div className="panel">
        <h2 style={{ fontSize: "1rem", fontWeight: 800, marginBottom: "1.25rem" }}>Observability Stack</h2>
        <p style={{ fontSize: "0.82rem", color: "var(--text-secondary)", marginBottom: "1.25rem" }}>
          Prometheus, Grafana, and Loki are deployed in the cluster. Access them via their NodePorts below.
        </p>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: "1rem" }}>
          <ExternalLink
            href={`http://${host}:3091`}
            label="Grafana"
            description="Pre-built DeployHub dashboard — deployment rates, latency, pod restarts"
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
            href={`/metrics`}
            label="Raw /metrics"
            description="Prometheus scrape endpoint — all DeployHub and HTTP metrics"
            port="metrics"
          />
        </div>
      </div>
    </div>
  );
}
