import { useState, useRef, useEffect } from "react";
import { copyToClipboard } from "../utils/clipboard";

function CopyButton({ lines, label }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    const text = lines?.join("\n") || "";
    if (!text) return;
    const ok = await copyToClipboard(text);
    if (ok) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }

  return (
    <button
      type="button"
      className="secondary-button"
      style={{ fontSize: "0.72rem", padding: "0.3rem 0.75rem" }}
      onClick={handleCopy}
      title={`Copy ${label}`}
    >
      {copied ? "✓ Copied" : "Copy"}
    </button>
  );
}

function parseLogLine(line) {
  const upper = line.toUpperCase();
  if (upper.includes("ERR") || upper.includes("EXCEPTION") || upper.includes("FAILED")) return "log-line-error";
  if (upper.includes("WARN")) return "log-line-warn";
  if (upper.match(/HTTP|GET|POST|PUT|DELETE|200|404|500/)) return "log-line-http";
  return "log-line-info";
}

function LogViewer({ title, lines, filterLevel, autoScroll }) {
  const scrollRef = useRef(null);

  const filteredLines = (lines || []).filter(line => {
    if (filterLevel === "all") return true;
    const type = parseLogLine(line);
    if (filterLevel === "ERROR" && type === "log-line-error") return true;
    if (filterLevel === "WARN" && type === "log-line-warn") return true;
    if (filterLevel === "HTTP" && type === "log-line-http") return true;
    if (filterLevel === "INFO" && type === "log-line-info") return true;
    return false;
  });

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [filteredLines, autoScroll]);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem" }}>
        <h3 style={{ margin: 0 }}>{title}</h3>
        <CopyButton lines={filteredLines} label={title.toLowerCase()} />
      </div>
      <pre ref={scrollRef}>
        {filteredLines.length > 0 
          ? filteredLines.map((line, i) => (
              <div key={i} className={parseLogLine(line)}>{line}</div>
            ))
          : `No ${title.toLowerCase()} yet.`}
      </pre>
    </div>
  );
}

export default function LogsPage({ projects, selectedProjectId, setSelectedProjectId, logs, streamState, onRefreshLogs }) {
  const [filterLevel, setFilterLevel] = useState("all");
  const [autoScroll, setAutoScroll] = useState(true);

  return (
    <div>
      <div className="page-header">
        <h1>Logs</h1>
        <p>Build and runtime output for your deployed projects.</p>
      </div>

      <div className="panel" style={{ marginBottom: "1.5rem", padding: "1.25rem 1.5rem" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "1rem", flexWrap: "wrap", justifyContent: "space-between" }}>
          <div style={{ flex: 1, minWidth: 200, display: "flex", gap: "1rem", alignItems: "flex-end" }}>
            <div>
              <label style={{ fontSize: "0.72rem", fontWeight: 800, textTransform: "uppercase", color: "var(--text-muted)", display: "block", marginBottom: "0.4rem" }}>
                Project
              </label>
              <select
                value={selectedProjectId}
                onChange={(e) => setSelectedProjectId(e.target.value)}
                style={{
                  background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: 10,
                  padding: "0.55rem 0.9rem", color: "var(--text-primary)", fontFamily: "inherit",
                  fontSize: "0.875rem", cursor: "pointer", outline: "none", width: "100%", minWidth: 250
                }}
              >
                <option value="">— select a project —</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>{p.service_name || p.repo_url}</option>
                ))}
              </select>
            </div>

            {selectedProjectId && (
              <div className="log-controls">
                <select 
                  value={filterLevel} 
                  onChange={e => setFilterLevel(e.target.value)}
                  style={{
                    background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: 10,
                    padding: "0.55rem 0.9rem", color: "var(--text-primary)", fontFamily: "inherit", fontSize: "0.875rem"
                  }}
                >
                  <option value="all">All Levels</option>
                  <option value="INFO">INFO</option>
                  <option value="HTTP">HTTP</option>
                  <option value="WARN">WARN</option>
                  <option value="ERROR">ERROR</option>
                </select>

                <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontSize: "0.8rem", cursor: "pointer" }}>
                  <div className="switch" style={{ transform: "scale(0.8)" }}>
                    <input type="checkbox" checked={autoScroll} onChange={e => setAutoScroll(e.target.checked)} />
                    <span className="slider"></span>
                  </div>
                  Auto-scroll
                </label>
              </div>
            )}
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginTop: "1.2rem" }}>
            <span className={`stream-pill ${streamState === "live" ? "live" : ""}`}>
              {streamState === "live" ? "Live stream" : streamState === "polling" ? "Polling" : "Idle"}
            </span>
            {selectedProjectId && (
              <button type="button" className="secondary-button" style={{ fontSize: "0.78rem", padding: "0.4rem 0.9rem" }} onClick={() => onRefreshLogs(selectedProjectId)}>
                Refresh
              </button>
            )}
          </div>
        </div>
      </div>

      {selectedProjectId ? (
        <div className="panel">
          <div className="log-columns">
            <LogViewer title="Build Logs" lines={logs.build_logs} filterLevel={filterLevel} autoScroll={autoScroll} />
            <LogViewer title="Runtime Logs" lines={logs.runtime_logs} filterLevel={filterLevel} autoScroll={autoScroll} />
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
