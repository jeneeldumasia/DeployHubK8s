export default function SettingsPage({ theme, setTheme }) {
  const isDark = theme === "dark";

  return (
    <div>
      <div className="page-header">
        <h1>Settings</h1>
        <p>Preferences and configuration for your DeployHub instance.</p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '2rem', alignItems: 'start' }}>
        <div className="panel">
          <h2 style={{ fontSize: "1rem", fontWeight: 800, marginBottom: "1.25rem" }}>Appearance</h2>
          <div className="settings-section" style={{ width: '100%' }}>
            <div className="settings-row">
              <div className="settings-row-label">
                <strong>Theme</strong>
                <span>Switch between light and dark mode</span>
              </div>
              <label className="switch">
                <input 
                  type="checkbox" 
                  checked={isDark} 
                  onChange={() => setTheme(isDark ? "light" : "dark")} 
                />
                <span className="slider"></span>
              </label>
            </div>
          </div>

          <div style={{ marginTop: '2rem' }}>
            <div style={{ fontSize: "0.72rem", fontWeight: 800, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-muted)", marginBottom: "0.75rem" }}>
              Live Preview
            </div>
            <div style={{
              background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: 12, padding: "1.5rem",
              boxShadow: "var(--shadow-sm)"
            }}>
              <strong style={{ display: 'block', fontSize: '1rem', marginBottom: '0.5rem', color: "var(--text-primary)" }}>
                {isDark ? "Dark Theme Active" : "Light Theme Active"}
              </strong>
              <p style={{ fontSize: '0.8rem', color: "var(--text-secondary)", marginBottom: '1rem' }}>
                This is how text and components look in your selected theme.
              </p>
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <button type="button" style={{ padding: '0.4rem 1rem', fontSize: '0.75rem' }}>Primary</button>
                <button type="button" className="secondary-button" style={{ padding: '0.4rem 1rem', fontSize: '0.75rem' }}>Secondary</button>
              </div>
            </div>
          </div>
        </div>

        <div className="panel">
          <h2 style={{ fontSize: "1rem", fontWeight: 800, marginBottom: "1.25rem" }}>Instance Config</h2>
          <div className="settings-section" style={{ width: '100%' }}>
            <div className="settings-row">
              <div className="settings-row-label">
                <strong>API Base URL</strong>
                <span>Backend endpoint used by the frontend</span>
              </div>
              <code style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.75rem", color: "var(--accent-primary)", padding: '0.2rem 0.4rem', background: 'var(--bg-elevated)', borderRadius: 4 }}>
                /api
              </code>
            </div>
            <div className="settings-row">
              <div className="settings-row-label">
                <strong>Host Domain</strong>
                <span>Edge routing configuration</span>
              </div>
              <code style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.75rem", color: "var(--accent-primary)", padding: '0.2rem 0.4rem', background: 'var(--bg-elevated)', borderRadius: 4 }}>
                jeneeldumasia.codes
              </code>
            </div>
          </div>

          <h2 style={{ fontSize: "1rem", fontWeight: 800, margin: "2.5rem 0 1.25rem" }}>Integrations</h2>
          <div className="settings-section" style={{ width: '100%' }}>
            <div className="settings-row">
              <div className="settings-row-label">
                <strong>GitHub Webhooks</strong>
                <span>Automatic deployments on push</span>
              </div>
              <span className="status-badge status-running">Active</span>
            </div>
            <div className="settings-row">
              <div className="settings-row-label">
                <strong>Prometheus Metrics</strong>
                <span>Internal system scraping</span>
              </div>
              <span className="status-badge status-running">Active</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
