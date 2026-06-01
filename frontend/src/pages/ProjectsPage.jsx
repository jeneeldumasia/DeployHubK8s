import { useState } from "react";
import { copyToClipboard } from "../utils/clipboard";

export default function ProjectsPage({
  projects,
  actionInFlight,
  error,
  onProjectAction,
  onGoToLogs,
  onRefreshLogs,
}) {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [typeFilter, setTypeFilter] = useState("all");

  const filteredProjects = projects.filter(p => {
    if (statusFilter !== "all" && p.status !== statusFilter) return false;
    if (typeFilter !== "all" && p.project_type !== typeFilter) return false;
    if (search) {
      const s = search.toLowerCase();
      if (!p.repo_url.toLowerCase().includes(s) && !(p.service_name && p.service_name.toLowerCase().includes(s))) {
        return false;
      }
    }
    return true;
  });

  const uniqueTypes = [...new Set(projects.map(p => p.project_type))].filter(Boolean);

  return (
    <div>
      <div className="page-header">
        <h1>Projects</h1>
        <p>Manage and monitor all deployed services.</p>
      </div>

      <div className="search-bar">
        <input 
          type="text" 
          placeholder="Search repositories or names..." 
          value={search} 
          onChange={e => setSearch(e.target.value)} 
        />
        <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
          <option value="all">All Statuses</option>
          <option value="running">Running</option>
          <option value="building">Building</option>
          <option value="failed">Failed</option>
        </select>
        <select value={typeFilter} onChange={e => setTypeFilter(e.target.value)}>
          <option value="all">All Types</option>
          {uniqueTypes.map(t => <option key={t} value={t}>{t}</option>)}
        </select>
      </div>

      {error && <p className="error inline-error" style={{marginBottom: "2rem"}}>{error}</p>}

      <div className="projects-layout">
        {filteredProjects.map((p) => {
          const url = p.service_url ? p.service_url.replace("http://", "https://") : null;

          return (
            <div key={p.id} className="project-card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <strong style={{ fontSize: '1.2rem' }}>{p.service_name || p.repo_url.split("/").pop()}</strong>
                <span className={`status-badge status-${p.status}`}>{p.status}</span>
              </div>
              
              <div className="card-meta">
                <div>
                  <span>Type: </span>
                  <strong>{p.project_type}{p.context_path ? ` (${p.context_path})` : ""}</strong>
                </div>
                <div>
                  <span>URI: </span>
                  {url ? (
                    <a href={url} target="_blank" rel="noreferrer" style={{color: 'var(--accent-primary)', textDecoration: 'underline'}}>
                      {url.replace("http://", "")}
                    </a>
                  ) : <strong>Pending</strong>}
                </div>
                <div>
                  <span>Last Updated: </span>
                  <strong>{new Date(p.updated_at).toLocaleString()}</strong>
                </div>
              </div>

              <div className="project-card-actions">
                <button
                  type="button"
                  disabled={Boolean(actionInFlight)}
                  onClick={() => onProjectAction("redeploy", p.id)}
                >
                  Redeploy
                </button>
                <button
                  type="button"
                  className="secondary-button"
                  disabled={Boolean(actionInFlight)}
                  onClick={() => onProjectAction("redeploy_magic", p.id)}
                  title="Fixes case-sensitivity build errors by creating lowercase symlinks"
                >
                  ✨ Fix Case & Redeploy
                </button>
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => onGoToLogs(p.id)}
                >
                  Logs
                </button>
                {url && p.status === "running" && (
                  <a
                    href={url}
                    target="_blank"
                    rel="noreferrer"
                    className="button"
                    style={{ textDecoration: 'none' }}
                  >
                    Open ↗
                  </a>
                )}
                <button
                  type="button"
                  className="danger-button"
                  style={{ marginLeft: 'auto' }}
                  disabled={Boolean(actionInFlight)}
                  onClick={() => onProjectAction("delete", p.id)}
                >
                  Delete
                </button>
              </div>
            </div>
          );
        })}

        {filteredProjects.length === 0 && (
          <div className="empty-state" style={{ gridColumn: '1 / -1' }}>
            <div className="empty-icon">🔍</div>
            <p>No projects match your filters.</p>
          </div>
        )}
      </div>
    </div>
  );
}
