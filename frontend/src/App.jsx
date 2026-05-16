import { useEffect, useMemo, useState } from "react";
import DashboardPage  from "./pages/DashboardPage";
import ProjectsPage   from "./pages/ProjectsPage";
import LogsPage       from "./pages/LogsPage";
import SettingsPage   from "./pages/SettingsPage";
import MonitoringPage from "./pages/MonitoringPage";
import RadialNav      from "./RadialNav";

const apiBase = "/api";
const destructiveActions = new Set(["stop", "delete"]);

async function parseResponse(response) {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "Request failed");
  return body;
}

/* ── Nav items — now handled by RadialNav ──────────────────── */

export default function App() {
  /* ── State ─────────────────────────────────────────────────── */
  const [page, setPage]                       = useState("dashboard");
  const [repoUrl, setRepoUrl]                 = useState("");
  const [projects, setProjects]               = useState([]);
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [selectedProject, setSelectedProject] = useState(null);
  const [logs, setLogs]                       = useState({ build_logs: [], runtime_logs: [] });
  const [error, setError]                     = useState("");
  const [actionInFlight, setActionInFlight]   = useState("");
  const [streamState, setStreamState]         = useState("idle");
  const [theme, setTheme]                     = useState(localStorage.getItem("theme") || "light");
  const [detectedServices, setDetectedServices] = useState(null);
  const [analyzing, setAnalyzing]             = useState(false);

  /* ── Theme sync ────────────────────────────────────────────── */
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
  }, [theme]);

  /* ── Derived ───────────────────────────────────────────────── */
  const selectedProjectSummary = useMemo(
    () => projects.find((p) => p.id === selectedProjectId) || null,
    [projects, selectedProjectId]
  );

  /* ── Data loaders ──────────────────────────────────────────── */
  async function loadProjects() {
    const data = await parseResponse(await fetch(`${apiBase}/projects`));
    setProjects(data);
    if (!selectedProjectId && data.length > 0) setSelectedProjectId(data[0].id);
  }

  async function loadLogs(projectId) {
    if (!projectId) { setLogs({ build_logs: [], runtime_logs: [] }); return; }
    const data = await parseResponse(await fetch(`${apiBase}/logs/${projectId}`));
    setLogs(data);
  }

  async function loadProjectDetail(projectId) {
    if (!projectId) { setSelectedProject(null); return; }
    const data = await parseResponse(await fetch(`${apiBase}/projects/${projectId}`));
    setSelectedProject(data);
  }

  /* ── Effects ───────────────────────────────────────────────── */
  useEffect(() => { loadProjects().catch((e) => setError(e.message)); }, []);

  useEffect(() => {
    loadProjectDetail(selectedProjectId).catch((e) => setError(e.message));
    loadLogs(selectedProjectId).catch((e) => setError(e.message));
  }, [selectedProjectId]);

  // SSE live log stream
  useEffect(() => {
    if (!selectedProjectId) return undefined;
    const stream = new EventSource(`${apiBase}/logs/${selectedProjectId}/stream`);
    setStreamState("live");
    stream.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        setLogs({ build_logs: data.build_logs || [], runtime_logs: data.runtime_logs || [] });
        setStreamState("live");
      } catch { setError("Failed to parse live logs stream"); }
    };
    stream.onerror = () => { setStreamState("polling"); stream.close(); };
    return () => stream.close();
  }, [selectedProjectId]);

  // Polling fallback
  useEffect(() => {
    const interval = window.setInterval(() => {
      if (streamState === "live") return;
      loadProjects().catch(() => {});
      if (selectedProjectId) {
        loadProjectDetail(selectedProjectId).catch(() => {});
        loadLogs(selectedProjectId).catch(() => {});
      }
    }, 5000);
    return () => window.clearInterval(interval);
  }, [selectedProjectId, streamState]);

  /* ── Handlers ──────────────────────────────────────────────── */
  async function handleCreateProject(event) {
    if (event) event.preventDefault();
    setError("");
    setAnalyzing(true);
    setDetectedServices(null);
    try {
      const res = await fetch(`${apiBase}/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo_url: repoUrl }),
      });
      if (!res.ok) throw new Error("Analysis failed");
      const data = await res.json();
      if (data.services?.length > 1) {
        setDetectedServices(data.services);
      } else if (data.services?.length === 1) {
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
      const res = await fetch(`${apiBase}/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo_url: repoUrl, context_path: service.path, service_name: service.name }),
      });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail || "Failed to create project"); }
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
      const msg = action === "delete"
        ? "Delete this project and clean its container, image, repo clone, and generated Dockerfile?"
        : "Stop this project and remove its running container?";
      if (!window.confirm(msg)) return;
    }
    setActionInFlight(action);
    setError("");
    try {
      if (action === "delete") {
        const res = await fetch(`${apiBase}/projects/${projectId}`, { method: "DELETE" });
        if (!res.ok) { const b = await res.json().catch(() => ({})); throw new Error(b.detail || "Delete failed"); }
      } else {
        const endpoint = {
          deploy:   `${apiBase}/deploy/${projectId}`,
          redeploy: `${apiBase}/redeploy/${projectId}`,
          stop:     `${apiBase}/stop/${projectId}`,
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

  /* ── Render ────────────────────────────────────────────────── */
  return (
    <div className="app-shell">
      <RadialNav
        page={page}
        setPage={setPage}
        theme={theme}
        setTheme={setTheme}
      />

      {/* ── Page content ── */}
      <main className="page-content">
        {page === "dashboard" && (
          <DashboardPage
            projects={projects}
            repoUrl={repoUrl}
            setRepoUrl={setRepoUrl}
            analyzing={analyzing}
            actionInFlight={actionInFlight}
            detectedServices={detectedServices}
            error={error}
            onCreateProject={handleCreateProject}
            onDeployService={deployService}
            onNavigateProjects={() => setPage("projects")}
          />
        )}

        {page === "projects" && (
          <ProjectsPage
            projects={projects}
            selectedProjectId={selectedProjectId}
            setSelectedProjectId={setSelectedProjectId}
            selectedProject={selectedProject}
            selectedProjectSummary={selectedProjectSummary}
            actionInFlight={actionInFlight}
            error={error}
            onProjectAction={handleProjectAction}
            onRefreshLogs={(id) => loadLogs(id).catch((e) => setError(e.message))}
          />
        )}

        {page === "logs" && (
          <LogsPage
            projects={projects}
            selectedProjectId={selectedProjectId}
            setSelectedProjectId={setSelectedProjectId}
            logs={logs}
            streamState={streamState}
            onRefreshLogs={(id) => loadLogs(id).catch((e) => setError(e.message))}
          />
        )}

        {page === "settings" && (
          <SettingsPage theme={theme} setTheme={setTheme} />
        )}

        {page === "monitoring" && (
          <MonitoringPage projects={projects} />
        )}
      </main>
    </div>
  );
}
