import { useState } from "react";

export default function DashboardPage({
  projects,
  repoUrl,
  setRepoUrl,
  analyzing,
  actionInFlight,
  detectedServices,
  error,
  onCreateProject,
  onDeployService,
  onNavigateProjects,
}) {
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
        <div className="stat-card">
          <span className="stat-label">Running</span>
          <span className="stat-value" style={{ color: "var(--status-running)" }}>{running}</span>
          <span className="stat-sub">live containers</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">Building</span>
          <span className="stat-value" style={{ color: "var(--status-building)" }}>{building}</span>
          <span className="stat-sub">in progress</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">Failed</span>
          <span className="stat-value" style={{ color: "var(--status-failed)" }}>{failed}</span>
          <span className="stat-sub">need attention</span>
        </div>
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
              onClick={onNavigateProjects}
            >
              View all →
            </button>
          </div>
          <div className="project-list">
            {projects.slice(0, 4).map((p) => (
              <button
                key={p.id}
                type="button"
                className="project-card"
                onClick={onNavigateProjects}
              >
                <strong>{p.service_name || p.repo_url}</strong>
                <div className="card-meta">
                  <span>{p.project_type}{p.context_path ? ` (${p.context_path})` : ""}</span>
                  <span className={`status-badge status-${p.status}`}>{p.status}</span>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
