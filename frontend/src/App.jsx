import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import DashboardPage  from "./pages/DashboardPage";
import ProjectsPage   from "./pages/ProjectsPage";
import LogsPage       from "./pages/LogsPage";
import SettingsPage   from "./pages/SettingsPage";
import MonitoringPage from "./pages/MonitoringPage";
import InfoPage       from "./pages/InfoPage";
import ContextRing    from "./ContextRing";

const apiBase = "/api";
const destructiveActions = new Set(["stop", "delete"]);

async function parseResponse(response) {
  const text = await response.text();
  let body = {};
  try {
    body = JSON.parse(text);
  } catch {
    // Server returned non-JSON (e.g. a 500 HTML error page or plain text)
    body = { detail: text.slice(0, 300) || "Request failed" };
  }
  if (!response.ok) {
    throw new Error(body.detail || `Request failed (${response.status})`);
  }
  return body;
}

/* ── Nav items — now handled by RadialNav ──────────────────── */

export default function App() {
  /* ── State ─────────────────────────────────────────────────── */
  const queryClient = useQueryClient();
  const [page, setPage]                       = useState("dashboard");
  const [repoUrl, setRepoUrl]                 = useState("");
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [error, setError]                     = useState("");
  const [actionInFlight, setActionInFlight]   = useState("");
  const [streamState, setStreamState]         = useState("idle");
  const [theme, setTheme]                     = useState(localStorage.getItem("theme") || "light");
  const [detectedServices, setDetectedServices] = useState(null);
  const [analyzing, setAnalyzing]             = useState(false);
  const [envVars, setEnvVars]                 = useState("");
  const [toast, setToast]                     = useState(null);

  /* ── Toast auto-dismiss ────────────────────────────────────── */
  useEffect(() => {
    if (!toast) return undefined;
    const timer = setTimeout(() => setToast(null), 10000);
    return () => clearTimeout(timer);
  }, [toast]);

  /* ── Theme sync ────────────────────────────────────────────── */
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
  }, [theme]);

  /* ── React Query ───────────────────────────────────────────── */
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: async () => await parseResponse(await fetch(`${apiBase}/projects`)),
    refetchInterval: 5000,
  });

  const { data: selectedProject = null } = useQuery({
    queryKey: ['project', selectedProjectId],
    queryFn: async () => await parseResponse(await fetch(`${apiBase}/projects/${selectedProjectId}`)),
    enabled: !!selectedProjectId,
    refetchInterval: 5000,
  });

  const { data: logs = { build_logs: [], runtime_logs: [] } } = useQuery({
    queryKey: ['logs', selectedProjectId],
    queryFn: async () => await parseResponse(await fetch(`${apiBase}/logs/${selectedProjectId}`)),
    enabled: !!selectedProjectId,
    refetchInterval: streamState === "live" ? false : 5000,
  });

  /* ── Derived ───────────────────────────────────────────────── */
  const selectedProjectSummary = useMemo(
    () => projects.find((p) => p.id === selectedProjectId) || null,
    [projects, selectedProjectId]
  );

  const systemStatus = useMemo(() => {
    if (projects.some(p => p.status === "failed")) return "failed";
    if (projects.some(p => p.status === "building")) return "building";
    return "running";
  }, [projects]);

  const activePulses = useMemo(() => {
    const now = Date.now();
    return {
      logs: projects.some(p => p.status === "building"),
      monitoring: projects.some(p => p.status === "failed"),
      projects: projects.some(p => p.status === "running" && (now - new Date(p.updated_at).getTime() < 60000)),
    };
  }, [projects]);

  /* ── Auto-select first project ─────────────────────────────── */
  useEffect(() => {
    if (!selectedProjectId && projects.length > 0) {
      setSelectedProjectId(projects[0].id);
    }
  }, [projects, selectedProjectId]);

  /* ── SSE live log stream ───────────────────────────────────── */
  useEffect(() => {
    if (!selectedProjectId) return undefined;
    const stream = new EventSource(`${apiBase}/logs/${selectedProjectId}/stream`);
    setStreamState("live");
    stream.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        queryClient.setQueryData(['logs', selectedProjectId], {
          build_logs: data.build_logs || [],
          runtime_logs: data.runtime_logs || []
        });
        setStreamState("live");
      } catch { setError("Failed to parse live logs stream"); }
    };
    stream.onerror = () => { setStreamState("polling"); stream.close(); };
    return () => stream.close();
  }, [selectedProjectId, queryClient]);

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
      if (!res.ok) {
        const e = await res.json().catch(() => ({}));
        throw new Error(e.detail || "Analysis failed");
      }
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
    // Parse KEY=VALUE lines from the env vars textarea
    const parsedEnvVars = {};
    for (const line of envVars.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) continue;
      const eqIdx = trimmed.indexOf("=");
      if (eqIdx > 0) {
        const key = trimmed.slice(0, eqIdx).trim();
        const val = trimmed.slice(eqIdx + 1).trim();
        if (key) parsedEnvVars[key] = val;
      }
    }
    try {
      const res = await fetch(`${apiBase}/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          repo_url: repoUrl,
          context_path: service.path,
          service_name: service.name,
          env_vars: parsedEnvVars,
        }),
      });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail || "Failed to create project"); }
      const newProject = await res.json();
      setRepoUrl("");
      setEnvVars("");
      setDetectedServices(null);
      
      if (newProject && newProject.id) {
        setSelectedProjectId(newProject.id);
        setPage("logs");
      }
      
      await queryClient.invalidateQueries({ queryKey: ['projects'] });
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
          redeploy_magic: `${apiBase}/redeploy/${projectId}?magic=true`,
          rollback: `${apiBase}/projects/${projectId}/rollback`,
          stop:     `${apiBase}/stop/${projectId}`,
        }[action];
        await parseResponse(await fetch(endpoint, { method: "POST" }));
      }
      if (action === "delete") {
        setSelectedProjectId("");
        queryClient.setQueryData(['logs', projectId], { build_logs: [], runtime_logs: [] });
      } else {
        setSelectedProjectId(projectId);
        if (action === "deploy" || action === "redeploy" || action === "redeploy_magic") {
          setPage("logs");
        }
      }
      await queryClient.invalidateQueries({ queryKey: ['projects'] });
      if (action !== "delete") {
        await queryClient.invalidateQueries({ queryKey: ['project', projectId] });
        await queryClient.invalidateQueries({ queryKey: ['logs', projectId] });
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
      <ContextRing
        page={page}
        setPage={setPage}
        systemStatus={systemStatus}
        activePulses={activePulses}
      />

      {/* ── Page content ── */}
      <main className="page-content">
        {page === "dashboard" && (
          <DashboardPage
            projects={projects}
            repoUrl={repoUrl}
            setRepoUrl={setRepoUrl}
            envVars={envVars}
            setEnvVars={setEnvVars}
            analyzing={analyzing}
            actionInFlight={actionInFlight}
            detectedServices={detectedServices}
            error={error}
            onCreateProject={handleCreateProject}
            onDeployService={deployService}
            setPage={setPage}
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
            onGoToLogs={(id) => { setSelectedProjectId(id); setPage("logs"); }}
            onRefreshLogs={(id) => queryClient.invalidateQueries({ queryKey: ['logs', id] })}
          />
        )}

        {page === "logs" && (
          <LogsPage
            projects={projects}
            selectedProjectId={selectedProjectId}
            setSelectedProjectId={setSelectedProjectId}
            logs={logs}
            streamState={streamState}
            onRefreshLogs={(id) => queryClient.invalidateQueries({ queryKey: ['logs', id] })}
          />
        )}

        {page === "settings" && (
          <SettingsPage theme={theme} setTheme={setTheme} />
        )}

        {page === "monitoring" && (
          <MonitoringPage projects={projects} />
        )}

        {page === "info" && (
          <InfoPage />
        )}
      </main>

      {toast && (
        <div className="toast-notification">
          <div className="toast-content">
            <span className="toast-icon">🚀</span>
            <span className="toast-message">{toast.message}</span>
          </div>
          <div className="toast-actions">
            {toast.actionLabel && (
              <button onClick={toast.action} className="toast-action-btn">
                {toast.actionLabel}
              </button>
            )}
            <button onClick={() => setToast(null)} className="toast-close-btn">×</button>
          </div>
        </div>
      )}
    </div>
  );
}
