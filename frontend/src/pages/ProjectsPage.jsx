export default function ProjectsPage({
  projects,
  selectedProjectId,
  setSelectedProjectId,
  selectedProject,
  selectedProjectSummary,
  actionInFlight,
  error,
  onProjectAction,
  onRefreshLogs,
}) {
  const projectForActions = selectedProject || selectedProjectSummary;

  return (
    <div>
      <div className="page-header">
        <h1>Projects</h1>
        <p>Select a project to inspect its configuration and manage deployments.</p>
      </div>

      <div className="projects-layout">
        {/* Left: project list */}
        <div className="panel" style={{ padding: "1.5rem" }}>
          <h2 style={{ fontSize: "1rem", fontWeight: 800, marginBottom: "0.25rem" }}>All Projects</h2>
          <p style={{ fontSize: "0.8rem", color: "var(--text-muted)", marginBottom: "1rem" }}>
            {projects.length} project{projects.length !== 1 ? "s" : ""}
          </p>
          <div className="project-list">
            {projects.map((p) => (
              <button
                key={p.id}
                type="button"
                className={`project-card ${selectedProjectId === p.id ? "selected" : ""}`}
                onClick={() => setSelectedProjectId(p.id)}
              >
                <strong>{p.service_name || p.repo_url}</strong>
                <div className="card-meta">
                  <span>{p.project_type}{p.context_path ? ` (${p.context_path})` : ""}</span>
                  <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                    <span className={`status-badge status-${p.status}`}>{p.status}</span>
                    {p.service_url && (
                      <a
                        href={p.service_url}
                        target="_blank"
                        rel="noreferrer"
                        onClick={(e) => e.stopPropagation()}
                        style={{ fontSize: "0.7rem", fontWeight: 700, textDecoration: "underline", color: "var(--accent-primary)" }}
                      >
                        Open ↗
                      </a>
                    )}
                  </div>
                </div>
              </button>
            ))}

            {projects.length === 0 && (
              <div className="empty-state">
                <div className="empty-icon">📦</div>
                <p>No projects yet. Add one from the Dashboard.</p>
              </div>
            )}
          </div>
        </div>

        {/* Right: detail */}
        <div className="panel">
          {projectForActions ? (
            <>
              <div className="detail-header">
                <div>
                  <h2>Project Detail</h2>
                  <p>Configuration and deployment metrics.</p>
                </div>
                <span className={`status-badge status-${projectForActions.status}`}>
                  {projectForActions.status}
                </span>
              </div>

              <div className="detail-grid">
                <div><span>Service Name</span><strong>{projectForActions.service_name || "Root"}</strong></div>
                <div><span>Context Path</span><strong>{projectForActions.context_path || "/"}</strong></div>
                <div><span>Repo URL</span><strong>{projectForActions.repo_url}</strong></div>
                <div><span>Project Type</span><strong>{projectForActions.project_type}</strong></div>
                <div><span>Service URL</span><strong>{projectForActions.service_url || "Not deployed yet"}</strong></div>
                <div><span>Assigned Port</span><strong>{projectForActions.assigned_port || "N/A"}</strong></div>
                <div><span>Container ID</span><strong>{projectForActions.container_id || "N/A"}</strong></div>
                <div><span>Image Tag</span><strong>{projectForActions.image_tag || "N/A"}</strong></div>
                <div><span>Container Name</span><strong>{projectForActions.container_name || "N/A"}</strong></div>
                <div>
                  <span>Last Updated</span>
                  <strong>
                    {projectForActions.updated_at
                      ? new Date(projectForActions.updated_at).toLocaleString()
                      : "N/A"}
                  </strong>
                </div>
              </div>

              <div className="webhook-section">
                <h3>CI/CD Webhook</h3>
                <p>Add this URL to your GitHub repository settings to enable auto-deploy on push.</p>
                <div className="webhook-box">
                  <code>{`http://${window.location.hostname}:3081/api/webhooks/github/${projectForActions.id}`}</code>
                  <button
                    type="button"
                    className="copy-button"
                    onClick={() => {
                      navigator.clipboard.writeText(
                        `http://${window.location.hostname}:3081/api/webhooks/github/${projectForActions.id}`
                      );
                      alert("Webhook URL copied!");
                    }}
                  >
                    Copy
                  </button>
                </div>
              </div>

              {projectForActions.last_error && (
                <p className="error inline-error">{projectForActions.last_error}</p>
              )}

              {error && <p className="error inline-error">{error}</p>}

              <div className="action-row">
                <button
                  type="button"
                  disabled={Boolean(actionInFlight)}
                  onClick={() => onProjectAction("deploy", projectForActions.id)}
                >
                  Deploy
                </button>
                <button
                  type="button"
                  disabled={Boolean(actionInFlight)}
                  onClick={() => onProjectAction("redeploy", projectForActions.id)}
                >
                  Redeploy
                </button>
                <button
                  type="button"
                  className="secondary-button"
                  disabled={Boolean(actionInFlight)}
                  onClick={() => onProjectAction("stop", projectForActions.id)}
                >
                  Stop
                </button>
                <button
                  type="button"
                  className="danger-button"
                  disabled={Boolean(actionInFlight)}
                  onClick={() => onProjectAction("delete", projectForActions.id)}
                >
                  Delete
                </button>
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => onRefreshLogs(projectForActions.id)}
                >
                  Refresh Logs
                </button>
              </div>
            </>
          ) : (
            <div className="empty-state">
              <div className="empty-icon">🔍</div>
              <p>Select a project from the list to inspect it.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
