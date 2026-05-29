import { useState } from "react";

export default function DashboardPage({
  projects,
  repoUrl,
  setRepoUrl,
  envVars,
  setEnvVars,
  analyzing,
  actionInFlight,
  detectedServices,
  error,
  onCreateProject,
  onDeployService,
  setPage,
}) {
  const [showEnvVars, setShowEnvVars] = useState(false);
  const total    = projects.length;
  const running  = projects.filter((p) => p.status === "running").length;
  const building = projects.filter((p) => p.status === "building").length;
  const failed   = projects.filter((p) => p.status === "failed").length;

  return (
    <div>
      <div className="page-header">
        <h1>DeployHub</h1>
        <p>Modern application orchestration for Kubernetes. Built for developers, scaled for production.</p>
      </div>

      {/* Stats */}
      <div className="dashboard-grid">
        <div className="stat-card">
          <span className="stat-label">Total Projects</span>
          <span className="stat-value">{total}</span>
          <span className="stat-sub">across all environments</span>
        </div>
        <div className="stat-card running">
          <span className="stat-label">Running</span>
          <span className="stat-value">{running}</span>
          <span className="stat-sub">live containers</span>
        </div>
        <div className="stat-card building">
          <span className="stat-label">Building</span>
          <span className="stat-value">{building}</span>
          <span className="stat-sub">in progress</span>
        </div>
        <div className="stat-card failed">
          <span className="stat-label">Failed</span>
          <span className="stat-value">{failed}</span>
          <span className="stat-sub">need attention</span>
        </div>
      </div>

      <div className="quick-action-bar">
        <button type="button" onClick={() => {
          document.querySelector('input[type="url"]').focus();
          window.scrollTo({ top: 300, behavior: 'smooth' });
        }}>+ New Project</button>
        <button type="button" className="secondary-button" onClick={() => setPage("logs")}>≡ View Logs</button>
        <button type="button" className="secondary-button" onClick={() => setPage("monitoring")}>◎ Monitoring</button>
      </div>

      {/* Add Project */}
      <div className="panel hero-form-panel">
        <h2>Deploy a Repository</h2>
        <p style={{ color: "var(--text-secondary)", fontSize: "0.875rem", marginTop: "0.25rem" }}>
          Paste a GitHub URL and DeployHub will detect, build, and deploy it automatically.
        </p>
        <form className="repo-form" onSubmit={onCreateProject}>
          <input
            type="url"
            placeholder="https://github.com/owner/repo"
            value={repoUrl}
            onChange={(e) => setRepoUrl(e.target.value)}
            required
          />
          <button type="submit" disabled={analyzing || Boolean(actionInFlight)}>
            {analyzing ? "Analyzing…" : actionInFlight === "create" ? "Initializing…" : "Add Project"}
          </button>
        </form>

        {/* Environment variables — optional, collapsed by default */}
        <div style={{ marginTop: "0.75rem", maxWidth: 580 }}>
          <button
            type="button"
            className="secondary-button"
            style={{ fontSize: "0.75rem", padding: "0.3rem 0.8rem", display: "flex", alignItems: "center", gap: "0.4rem" }}
            onClick={() => setShowEnvVars((v) => !v)}
          >
            <span>{showEnvVars ? "▾" : "▸"}</span>
            Environment Variables {envVars.trim() ? `(${envVars.trim().split("\n").filter(l => l.trim() && !l.startsWith("#")).length} set)` : "(optional)"}
          </button>

          {showEnvVars && (
            <div style={{ marginTop: "0.5rem" }}>
              <textarea
                value={envVars}
                onChange={(e) => setEnvVars(e.target.value)}
                placeholder={"KEY=value\nVITE_API_URL=http://34.x.x.x:3101\nNODE_ENV=production"}
                rows={5}
                style={{
                  width: "100%",
                  background: "var(--bg-card)",
                  border: "1px solid var(--border-strong)",
                  borderRadius: 10,
                  padding: "0.75rem 1rem",
                  color: "var(--text-primary)",
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: "0.8rem",
                  lineHeight: 1.6,
                  resize: "vertical",
                  outline: "none",
                }}
              />
              <p style={{ fontSize: "0.72rem", color: "var(--text-muted)", marginTop: "0.3rem" }}>
                One <code style={{ fontFamily: "monospace" }}>KEY=value</code> per line. Lines starting with # are ignored.
                Use this to set API URLs, feature flags, or any runtime config without touching the repo.
              </p>
            </div>
          )}
        </div>

        {detectedServices && (
          <div className="service-selector">
            <h3>Detected Services</h3>
            <p>Multiple deployable units found — pick one to deploy.</p>
            <div className="service-grid">
              {detectedServices.map((svc, i) => (
                <div key={i} className="project-card" style={{ cursor: "default" }}>
                  <strong>{svc.name}</strong>
                  <div className="card-meta">
                    <span>{svc.type}{svc.framework ? ` (${svc.framework})` : ""}</span>
                    <button onClick={() => onDeployService(svc)}>Deploy</button>
                  </div>
                  <span style={{ fontSize: "0.7rem", color: "var(--text-muted)" }}>
                    Path: {svc.path || "/"}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {error && <p className="error">{error}</p>}
      </div>

      {/* Recent projects quick-view */}
      {projects.length > 0 && (
        <div className="panel">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
            <h2 style={{ fontSize: "1rem", fontWeight: 800 }}>Recent Projects</h2>
            <button
              type="button"
              className="secondary-button"
              style={{ fontSize: "0.78rem", padding: "0.4rem 0.9rem" }}
              onClick={() => setPage("projects")}
            >
              View all →
            </button>
          </div>
          <div className="project-list" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '1rem' }}>
            {projects.slice(0, 4).map((p) => {
              const url = p.service_url ? p.service_url.replace("http://", "https://") : null;
              return (
                <div key={p.id} className="project-card" style={{ padding: '1.25rem' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <strong style={{ fontSize: '1rem' }}>{p.service_name || p.repo_url.split("/").pop()}</strong>
                    <span className={`status-badge status-${p.status}`}>{p.status}</span>
                  </div>
                  <div className="card-meta" style={{ flexDirection: 'row', justifyContent: 'space-between', marginTop: '0.5rem', alignItems: 'center' }}>
                    <span>{p.project_type}{p.context_path ? ` (${p.context_path})` : ""}</span>
                    <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                      {new Date(p.updated_at).toLocaleTimeString()}
                    </span>
                  </div>
                  <div className="project-card-actions" style={{ marginTop: '0.75rem', paddingTop: '0.75rem' }}>
                    {url && p.status === "running" && (
                      <a href={url} target="_blank" rel="noreferrer" className="button" style={{ textDecoration: 'none', padding: '0.35rem 0.75rem', fontSize: '0.75rem', borderRadius: '6px' }}>Open App ↗</a>
                    )}
                    <button type="button" className="secondary-button" style={{ padding: '0.35rem 0.75rem', fontSize: '0.75rem', borderRadius: '6px' }} onClick={() => setPage("projects")}>Details</button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
