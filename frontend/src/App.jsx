import { useEffect, useMemo, useState } from "react";

const apiBase = "/api";
const destructiveActions = new Set(["stop", "delete"]);

async function parseResponse(response) {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.detail || "Request failed");
  }
  return body;
}

export default function App() {
  const [repoUrl, setRepoUrl] = useState("");
  const [projects, setProjects] = useState([]);
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [selectedProject, setSelectedProject] = useState(null);
  const [logs, setLogs] = useState({ build_logs: [], runtime_logs: [] });
  const [error, setError] = useState("");
  const [actionInFlight, setActionInFlight] = useState("");
  const [streamState, setStreamState] = useState("idle");
  const [theme, setTheme] = useState(localStorage.getItem("theme") || "dark");
  const [detectedServices, setDetectedServices] = useState(null);
  const [analyzing, setAnalyzing] = useState(false);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
  }, [theme]);

  const selectedProjectSummary = useMemo(() => projects.find((project) => project.id === selectedProjectId) || null, [projects, selectedProjectId]);

  async function loadProjects() {
    const data = await parseResponse(await fetch(`${apiBase}/projects`));
    setProjects(data);
    if (!selectedProjectId && data.length > 0) {
      setSelectedProjectId(data[0].id);
    }
  }

  async function loadLogs(projectId) {
    if (!projectId) {
      setLogs({ build_logs: [], runtime_logs: [] });
      return;
    }

    const data = await parseResponse(await fetch(`${apiBase}/logs/${projectId}`));
    setLogs(data);
  }

  async function loadProjectDetail(projectId) {
    if (!projectId) {
      setSelectedProject(null);
      return;
    }

    const data = await parseResponse(await fetch(`${apiBase}/projects/${projectId}`));
    setSelectedProject(data);
  }

  useEffect(() => {
    loadProjects().catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    loadProjectDetail(selectedProjectId).catch((err) => setError(err.message));
    loadLogs(selectedProjectId).catch((err) => setError(err.message));
  }, [selectedProjectId]);

  useEffect(() => {
    if (!selectedProjectId) {
      return undefined;
    }

    const stream = new EventSource(`${apiBase}/logs/${selectedProjectId}/stream`);
    setStreamState("live");

    stream.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        setLogs({
          build_logs: data.build_logs || [],
          runtime_logs: data.runtime_logs || [],
        });
        setStreamState("live");
      } catch {
        setError("Failed to parse live logs stream");
      }
    };

    stream.onerror = () => {
      setStreamState("polling");
      stream.close();
    };

    return () => stream.close();
  }, [selectedProjectId]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      // Skip polling while the SSE stream is delivering live updates
      if (streamState === "live") return;
      loadProjects().catch(() => {});
      if (selectedProjectId) {
        loadProjectDetail(selectedProjectId).catch(() => {});
        loadLogs(selectedProjectId).catch(() => {});
      }
    }, 5000);

    return () => window.clearInterval(interval);
  }, [selectedProjectId, streamState]);

  async function handleCreateProject(event) {
    if (event) event.preventDefault();
    setError("");
    setAnalyzing(true);
    setDetectedServices(null);

    try {
      const response = await fetch(`${apiBase}/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo_url: repoUrl }),
      });

      if (!response.ok) throw new Error("Analysis failed");
      const data = await response.json();
      
      if (data.services && data.services.length > 1) {
        setDetectedServices(data.services);
      } else if (data.services && data.services.length === 1) {
        // Only one service? Just deploy it.
        await deployService(data.services[0]);
      } else {
        setError("No deployable services detected in this repository.");
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setAnalyzing(false);
    }
  }

  async function deployService(service) {
    setActionInFlight("create");
    try {
      const response = await fetch(`${apiBase}/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          repo_url: repoUrl,
          context_path: service.path,
          service_name: service.name
        }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "Failed to create project");
      }

      setRepoUrl("");
      setDetectedServices(null);
      await loadProjects();
    } catch (err) {
      setError(err.message);
    } finally {
      setActionInFlight("");
    }
  }

  async function handleProjectAction(action, projectId) {
    if (destructiveActions.has(action)) {
      const confirmed = window.confirm(
        action === "delete"
          ? "Delete this project and clean its container, image, repo clone, and generated Dockerfile?"
          : "Stop this project and remove its running container?",
      );
      if (!confirmed) {
        return;
      }
    }

    setActionInFlight(action);
    setError("");

    try {
      if (action === "delete") {
        const response = await fetch(`${apiBase}/projects/${projectId}`, { method: "DELETE" });
        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          throw new Error(body.detail || "Delete failed");
        }
      } else {
        const endpoint = {
          deploy: `${apiBase}/deploy/${projectId}`,
          redeploy: `${apiBase}/redeploy/${projectId}`,
          stop: `${apiBase}/stop/${projectId}`,
        }[action];
        await parseResponse(await fetch(endpoint, { method: "POST" }));
      }

      if (action === "delete") {
        setSelectedProjectId("");
        setSelectedProject(null);
        setLogs({ build_logs: [], runtime_logs: [] });
      } else {
        setSelectedProjectId(projectId);
      }
      await loadProjects();
      if (action !== "delete") {
        await loadProjectDetail(projectId);
        await loadLogs(projectId);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setActionInFlight("");
    }
  }

  const projectForActions = selectedProject || selectedProjectSummary;

  return (
    <main className="layout">
      <button 
        type="button" 
        className="theme-toggle" 
        onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
        title="Toggle Theme"
      >
        {theme === "dark" ? "☀️" : "🌙"}
      </button>

      <section className="panel hero-panel">
        <div className="hero-content">
          <h1>DeployHub</h1>
          <p className="subtitle">Modern application orchestration for Kubernetes. Built for developers, scaled for production.</p>
          
          <form className="repo-form" onSubmit={handleCreateProject}>
            <input
              type="url"
              placeholder="https://github.com/owner/repo"
              value={repoUrl}
              onChange={(event) => setRepoUrl(event.target.value)}
              required
            />
            <button type="submit" disabled={analyzing || Boolean(actionInFlight)}>
              {analyzing ? "Analyzing..." : (actionInFlight === "create" ? "Initializing..." : "Add Project")}
            </button>
          </form>
          
          {detectedServices && (
            <div className="service-selector panel" style={{marginTop: '2rem', background: 'var(--bg-deep)'}}>
              <h3>Detected Services</h3>
              <p className="subtitle">We found multiple deployable units. Which one would you like to deploy?</p>
              <div className="project-list" style={{marginTop: '1rem', display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(250px, 1fr))', gap: '1rem'}}>
                {detectedServices.map((service, idx) => (
                  <div key={idx} className="project-card" style={{cursor: 'default'}}>
                    <strong>{service.name}</strong>
                    <div className="card-meta">
                      <span>{service.type} {service.framework ? `(${service.framework})` : ''}</span>
                      <button onClick={() => deployService(service)}>Deploy</button>
                    </div>
                    <span style={{fontSize: '0.7rem', color: 'var(--text-muted)'}}>Path: {service.path || '/'}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {error ? <p className="error" style={{marginTop: '1rem'}}>{error}</p> : null}
        </div>
      </section>

      <section className="workspace">
        <section className="panel">
          <h2>Projects</h2>
          <div className="project-list">
            {projects.map((project) => (
              <button
                key={project.id}
                type="button"
                className={`project-card ${selectedProjectId === project.id ? "selected" : ""}`}
                onClick={() => setSelectedProjectId(project.id)}
              >
                <strong>{project.service_name || project.repo_url}</strong>
                <div className="card-meta">
                  <span>{project.project_type} {project.context_path ? `(${project.context_path})` : ''}</span>
                  <div style={{display: 'flex', gap: '0.5rem', alignItems: 'center'}}>
                    <span className={`status-badge status-${project.status}`}>{project.status}</span>
                    {project.service_url ? (
                      <a href={project.service_url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} style={{fontSize: '0.7rem', fontWeight: 'bold', textDecoration: 'underline'}}>
                        Open
                      </a>
                    ) : null}
                  </div>
                </div>
              </button>
            ))}

            {projects.length === 0 ? <p>No projects yet.</p> : null}
          </div>
        </section>

        <section className="panel detail-panel">
          <div className="detail-header">
            <div>
              <h2>Project Detail</h2>
              <p className="subtitle">Configuration and deployment metrics.</p>
            </div>
            {projectForActions ? <span className={`status-badge status-${projectForActions.status}`}>{projectForActions.status}</span> : null}
          </div>

          {projectForActions ? (
            <>
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
                <div><span>Last Updated</span><strong>{projectForActions.updated_at ? new Date(projectForActions.updated_at).toLocaleString() : "N/A"}</strong></div>
              </div>

              <div className="webhook-section">
                <h3>CI/CD Webhook</h3>
                <p className="subtitle">Add this URL to your GitHub repository settings to enable auto-deploy on push.</p>
                <div className="webhook-box">
                  <code>{`http://${window.location.hostname}:3081/api/webhooks/github/${projectForActions.id}`}</code>
                  <button 
                    type="button" 
                    className="copy-button"
                    onClick={() => {
                      navigator.clipboard.writeText(`http://${window.location.hostname}:3081/api/webhooks/github/${projectForActions.id}`);
                      alert("Webhook URL copied to clipboard!");
                    }}
                  >
                    Copy
                  </button>
                </div>
              </div>

              {projectForActions.last_error ? <p className="error inline-error">{projectForActions.last_error}</p> : null}

              <div className="action-row">
                <button type="button" disabled={Boolean(actionInFlight)} onClick={() => handleProjectAction("deploy", projectForActions.id)}>
                  Deploy
                </button>
                <button type="button" disabled={Boolean(actionInFlight)} onClick={() => handleProjectAction("redeploy", projectForActions.id)}>
                  Redeploy
                </button>
                <button type="button" className="secondary-button" disabled={Boolean(actionInFlight)} onClick={() => handleProjectAction("stop", projectForActions.id)}>
                  Stop
                </button>
                <button type="button" className="danger-button" disabled={Boolean(actionInFlight)} onClick={() => handleProjectAction("delete", projectForActions.id)}>
                  Delete
                </button>
                <button type="button" className="secondary-button" onClick={() => loadLogs(projectForActions.id).catch((err) => setError(err.message))}>
                  Refresh Logs
                </button>
              </div>
            </>
          ) : (
            <p>Select a project to inspect it.</p>
          )}
        </section>
      </section>

      <section className="panel logs-panel">
        <div className="logs-header">
          <div>
            <h2>Logs</h2>
            <p className="subtitle">Stream state: {streamState}</p>
          </div>
        </div>
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
      </section>
    </main>
  );
}
