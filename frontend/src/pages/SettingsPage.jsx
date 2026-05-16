export default function SettingsPage({ theme, setTheme }) {
  return (
    <div>
      <div className="page-header">
        <h1>Settings</h1>
        <p>Preferences and configuration for your DeployHub instance.</p>
      </div>

      <div className="panel" style={{ maxWidth: 600 }}>
        <h2 style={{ fontSize: "1rem", fontWeight: 800, marginBottom: "1.25rem" }}>Appearance</h2>
        <div className="settings-section">
          <div className="settings-row">
            <div className="settings-row-label">
              <strong>Theme</strong>
              <span>Switch between light and dark mode</span>
            </div>
            <button
              type="button"
              className="secondary-button"
              style={{ minWidth: 100 }}
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            >
              {theme === "dark" ? "☀️  Light" : "🌙  Dark"}
            </button>
          </div>
        </div>

        <h2 style={{ fontSize: "1rem", fontWeight: 800, margin: "2rem 0 1.25rem" }}>Instance</h2>
        <div className="settings-section">
          <div className="settings-row">
            <div className="settings-row-label">
              <strong>API Base URL</strong>
              <span>Backend endpoint used by the frontend</span>
            </div>
            <code style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.8rem", color: "var(--accent-primary)" }}>
              /api
            </code>
          </div>
          <div className="settings-row">
            <div className="settings-row-label">
              <strong>Webhook Port</strong>
              <span>Port exposed for GitHub webhooks</span>
            </div>
            <code style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.8rem", color: "var(--accent-primary)" }}>
              3081
            </code>
          </div>
        </div>
      </div>
    </div>
  );
}
