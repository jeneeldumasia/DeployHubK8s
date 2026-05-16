export default function LogsPage({ projects, selectedProjectId, setSelectedProjectId, logs, streamState, onRefreshLogs }) {
  const selectedProject = projects.find((p) => p.id === selectedProjectId);

  return (
    <div>
      <div className="page-header">
        <h1>Logs</h1>
        <p>Build and runtime output for your deployed projects.</p>
      </div>

      {/* Project selector + stream state */}
      <div className="panel" style={{ marginBottom: "1.5rem", padding: "1.25rem 1.5rem" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "1rem", flexWrap: "wrap" }}>
          <div style={{ flex: 1, minWidth: 200 }}>
            <label
              htmlFor="log-project-select"
              style={{ fontSize: "0.72rem", fontWeight: 800, textTransform: "uppercase", color: "var(--text-muted)", display: "block", marginBottom: "0.4rem" }}
            >
              Project
            </label>
            <select
              id="log-project-select"
              value={selectedProjectId}
              onChange={(e) => setSelectedProjectId(e.target.value)}
              style={{
                background: "var(--bg-card)",
                border: "1px solid var(--border)",
                borderRadius: 10,
                padding: "0.55rem 0.9rem",
                color: "var(--text-primary)",
                fontFamily: "inherit",
                fontSize: "0.875rem",
                cursor: "pointer",
                outline: "none",
                width: "100%",
                maxWidth: 320,
              }}
            >
              <option value="">— select a project —</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.service_name || p.repo_url}
                </option>
              ))}
            </select>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginTop: "1.2rem" }}>
            <span className={`stream-pill ${streamState === "live" ? "live" : ""}`}>
              {streamState === "live" ? "Live stream" : streamState === "polling" ? "Polling" : "Idle"}
            </span>
            {selectedProjectId && (
              <button
                type="button"
                className="secondary-button"
                style={{ fontSize: "0.78rem", padding: "0.4rem 0.9rem" }}
                onClick={() => onRefreshLogs(selectedProjectId)}
              >
                Refresh
              </button>
            )}
          </div>
        </div>
      </div>

      {selectedProjectId ? (
        <div className="panel">
          <div className="log-columns">
            <div>
              <h3>Build Logs</h3>
              <pre>{logs.build_logs?.join("\n") || "No build logs yet."}</pre>
            </div>
            <div>
              <h3>Runtime Logs</h3>
              <pre>{logs.runtime_logs?.join("\n") || "No runtime logs yet."}</pre>
            </div>
          </div>
        </div>
      ) : (
        <div className="panel">
          <div className="empty-state">
            <div className="empty-icon">📋</div>
            <p>Select a project above to view its logs.</p>
          </div>
        </div>
      )}
    </div>
  );
}
