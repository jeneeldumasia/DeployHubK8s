import { useState, useEffect, useCallback } from "react";

const apiBase = "/api";

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

function PhaseBadge({ phase, ready }) {
  const isRunning = phase === "Running" && ready;
  const isPending = phase === "Pending" || (phase === "Running" && !ready);
  const color = isRunning ? "var(--status-running)" : isPending ? "var(--status-building)" : "var(--status-failed)";
  const label = isRunning ? "Running" : isPending ? "Starting…" : phase || "Unknown";
  return (
    <span className="status-badge" style={{ background: `${color}22`, color }}>
      <span style={{ display: 'inline-block', width: 6, height: 6, borderRadius: '50%', background: color, marginRight: '0.4rem', animation: isRunning ? 'pulse 2s infinite' : 'none' }}></span>
      {label}
    </span>
  );
}

function MiniBar({ label, value, max, unit }) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0;
  return (
    <div style={{ marginBottom: "1rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.3rem", fontSize: "0.78rem" }}>
        <span style={{ color: "var(--text-secondary)", fontWeight: 700 }}>{label}</span>
        <span style={{ color: "var(--text-primary)", fontFamily: "monospace", fontWeight: 700 }}>
          {value}{unit} / {max}{unit}
        </span>
      </div>
      <div className="progress-bar-bg">
        <div className="progress-bar-fill" style={{ width: `${pct}%`, background: pct > 80 ? 'var(--status-failed)' : 'var(--accent-primary)' }} />
      </div>
    </div>
  );
}

function AppHealthSection({ projects }) {
  const runningProjects = projects.filter(p => ["running", "failed", "building"].includes(p.status));
  const [selectedId, setSelectedId] = useState("");
  
  useEffect(() => {
    if (!selectedId && runningProjects.length > 0) setSelectedId(runningProjects[0].id);
  }, [projects, selectedId, runningProjects]);

  const { data: health, logs, loading, error } = usePodHealth(selectedId, 10000);
  const selectedProject = projects.find(p => p.id === selectedId);
  const pod = health?.pod;

  const cpuVal  = parseMilli(pod?.cpu);
  const memVal  = parseMi(pod?.memory);

  return (
    <div className="panel" style={{ marginTop: "2rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.25rem", flexWrap: "wrap", gap: "0.75rem" }}>
        <div>
          <h2 style={{ fontSize: "1.2rem", fontWeight: 800, margin: 0 }}>App Health Focus</h2>
          <p style={{ fontSize: "0.85rem", color: "var(--text-muted)", marginTop: "0.2rem" }}>Live pod resources and timeline.</p>
        </div>
        
        {runningProjects.length > 0 && (
          <select
            value={selectedId}
            onChange={e => setSelectedId(e.target.value)}
            style={{
              background: "var(--bg-card)", color: "var(--text-primary)",
              border: "1px solid var(--border)", borderRadius: 8,
              padding: "0.4rem 0.75rem", fontSize: "0.85rem", cursor: "pointer",
              outline: "none"
            }}
          >
            {runningProjects.map(p => (
              <option key={p.id} value={p.id}>
                {p.service_name || p.repo_url?.split("/").pop()}
              </option>
            ))}
          </select>
        )}
      </div>

      {!selectedProject ? (
        <p style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>No deployed apps to monitor.</p>
      ) : loading && !health ? (
        <p style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>Loading pod health…</p>
      ) : error ? (
        <p className="error inline-error">{error}</p>
      ) : !pod ? (
        <p style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>Pod not found or not yet deployed.</p>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: "2rem" }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "1rem", marginBottom: "1.5rem" }}>
              <PhaseBadge phase={pod.phase} ready={pod.ready} />
              <span style={{ fontSize: "0.75rem", color: "var(--text-muted)", fontFamily: "monospace" }}>{pod.name}</span>
            </div>

            {cpuVal !== null ? (
              <MiniBar label="CPU Usage" value={cpuVal} max={1000} unit="m" />
            ) : (
              <div style={{ fontSize: "0.78rem", color: "var(--text-muted)", marginBottom: "1rem" }}>CPU — metrics-server fallback enabled.</div>
            )}
            
            {memVal !== null ? (
              <MiniBar label="Memory Usage" value={memVal} max={512} unit="Mi" />
            ) : (
              <div style={{ fontSize: "0.78rem", color: "var(--text-muted)", marginBottom: "1rem" }}>Memory — metrics-server fallback enabled.</div>
            )}
            
            <div style={{ marginTop: "2rem", borderTop: "1px solid var(--border)", paddingTop: "1rem" }}>
              <h3 style={{ fontSize: "0.85rem", fontWeight: 800, marginBottom: "0.75rem" }}>Deployment Timeline</h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
                  <div style={{ width: 10, height: 10, borderRadius: '50%', background: 'var(--status-running)' }}></div>
                  <div>
                    <div style={{ fontSize: '0.85rem', fontWeight: 700 }}>Last Deployed</div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{new Date(selectedProject.updated_at).toLocaleString()}</div>
                  </div>
                </div>
                <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', opacity: 0.5 }}>
                  <div style={{ width: 10, height: 10, borderRadius: '50%', background: 'var(--text-muted)' }}></div>
                  <div>
                    <div style={{ fontSize: '0.85rem', fontWeight: 700 }}>Created</div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{new Date(selectedProject.created_at).toLocaleString()}</div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div>
            <div style={{ fontSize: "0.72rem", fontWeight: 800, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-muted)", marginBottom: "0.5rem" }}>
              Live Log Tail
            </div>
            <pre style={{
              background: "var(--bg-card)", border: "1px solid var(--border)",
              borderRadius: 8, padding: "0.75rem 1rem",
              fontSize: "0.72rem", lineHeight: 1.55, fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
              overflowY: "auto", maxHeight: 320,
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

function GrafanaIframe({ dashboardUid, title }) {
  const url = `${window.location.protocol}//${window.location.host}/grafana/d/${dashboardUid}?kiosk=tv&theme=dark`;
  
  return (
    <div className="panel" style={{ marginTop: "2rem", padding: "1rem", height: "800px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
        <h2 style={{ fontSize: "1.2rem", fontWeight: 800, margin: 0 }}>{title}</h2>
        <a href={`${window.location.protocol}//${window.location.host}/grafana/d/${dashboardUid}`} target="_blank" rel="noreferrer" className="secondary-button" style={{ fontSize: "0.8rem", padding: "0.4rem 0.8rem", textDecoration: "none" }}>
          Open in Grafana ↗
        </a>
      </div>
      <iframe
        src={url}
        width="100%"
        height="100%"
        style={{ border: "none", borderRadius: "8px", background: "#111217" }}
        title={title}
      />
    </div>
  );
}

export default function MonitoringPage({ projects }) {
  const { data: sys } = useSystemStats(10000);
  const [activeTab, setActiveTab] = useState("native");

  const tabs = [
    { id: "native", label: "Native Health" },
    { id: "deployhub", label: "DeployHub Platform" },
    { id: "apps", label: "User Apps" },
    { id: "nodes", label: "Node Resources" },
    { id: "pods", label: "Pod Resources" },
  ];

  return (
    <div>
      <div className="page-header" style={{ marginBottom: "1.5rem" }}>
        <h1>Monitoring</h1>
        <p>System health, cluster metrics, and live application resources.</p>
      </div>

      <div style={{ 
        display: "flex", 
        gap: "0.5rem", 
        marginBottom: "2rem", 
        borderBottom: "1px solid var(--border)", 
        paddingBottom: "0.5rem",
        overflowX: "auto"
      }}>
        {tabs.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            style={{
              background: activeTab === tab.id ? "var(--accent-primary)" : "transparent",
              color: activeTab === tab.id ? "#fff" : "var(--text-secondary)",
              border: "1px solid",
              borderColor: activeTab === tab.id ? "var(--accent-primary)" : "var(--border-strong)",
              padding: "0.4rem 1rem",
              borderRadius: "20px",
              fontSize: "0.85rem",
              fontWeight: 700,
              cursor: "pointer",
              transition: "all 0.2s"
            }}
          >
            {tab.label}
          </button>
        ))}
        
        <a href={`${window.location.protocol}//${window.location.host}/grafana`} target="_blank" rel="noreferrer" style={{
          marginLeft: "auto",
          background: "var(--bg-card)",
          color: "var(--text-primary)",
          border: "1px solid var(--border-strong)",
          padding: "0.4rem 1rem",
          borderRadius: "20px",
          fontSize: "0.85rem",
          fontWeight: 700,
          textDecoration: "none",
          display: "inline-flex",
          alignItems: "center"
        }}>
          Grafana Home ↗
        </a>
      </div>

      {activeTab === "native" && (
        <>
          <div className="panel" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
            <div>
              <h2 style={{ fontSize: "1rem", fontWeight: 800 }}>System Health</h2>
              <p style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>Platform control plane status.</p>
            </div>
            
            <div style={{ display: 'flex', gap: '2rem' }}>
              <div>
                <div style={{ fontSize: '0.7rem', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 800 }}>Backend API</div>
                <div style={{ fontSize: '1.2rem', fontWeight: 800, color: sys ? 'var(--status-running)' : 'var(--status-failed)' }}>
                  {sys ? 'Operational' : 'Down'}
                </div>
              </div>
              <div>
                <div style={{ fontSize: '0.7rem', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 800 }}>Docker / BuildKit</div>
                <div style={{ fontSize: '1.2rem', fontWeight: 800, color: sys?.docker_available ? 'var(--status-running)' : 'var(--status-failed)' }}>
                  {sys?.docker_available ? 'Operational' : 'Down'}
                </div>
              </div>
              <div>
                <div style={{ fontSize: '0.7rem', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 800 }}>Database</div>
                <div style={{ fontSize: '1.2rem', fontWeight: 800, color: sys?.mongodb_available ? 'var(--status-running)' : 'var(--status-failed)' }}>
                  {sys?.mongodb_available ? 'Operational' : 'Down'}
                </div>
              </div>
              <div>
                <div style={{ fontSize: '0.7rem', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 800 }}>Kubernetes</div>
                <div style={{ fontSize: '1.2rem', fontWeight: 800, color: sys?.docker_available ? 'var(--status-running)' : 'var(--status-failed)' }}>
                  {sys?.docker_available ? 'Operational' : 'Down'}
                </div>
              </div>
            </div>
          </div>
          <AppHealthSection projects={projects} />
        </>
      )}

      {activeTab === "deployhub" && <GrafanaIframe dashboardUid="deployhub-overview" title="DeployHub Platform" />}
      {activeTab === "apps" && <GrafanaIframe dashboardUid="app-overview" title="User Applications" />}
      {activeTab === "nodes" && <GrafanaIframe dashboardUid="node-overview" title="Node Resources" />}
      {activeTab === "pods" && <GrafanaIframe dashboardUid="pod-overview" title="Pod Resources" />}
    </div>
  );
}
