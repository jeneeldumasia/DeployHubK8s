export default function InfoPage() {
  return (
    <div>
      <div className="page-header">
        <h1>Compatibility & Guide</h1>
        <p>Learn how to configure any repository for DeployHub.</p>
      </div>

      <div className="panel" style={{ maxWidth: 800 }}>
        <h2 style={{ fontSize: "1.2rem", fontWeight: 800, marginBottom: "1rem" }}>Auto-Detection</h2>
        <p style={{ marginBottom: "1.5rem", lineHeight: 1.5 }}>
          DeployHub automatically detects and builds the following project types based on their files:
        </p>
        <ul style={{ paddingLeft: "1.5rem", marginBottom: "2rem", lineHeight: 1.6 }}>
          <li><strong>Node.js:</strong> Detects <code>package.json</code>. Runs <code>npm run build</code> and then <code>npm run start</code> or <code>npm run dev</code>.</li>
          <li><strong>Python:</strong> Detects <code>requirements.txt</code> or <code>pyproject.toml</code>. Runs Gunicorn/Uvicorn automatically.</li>
          <li><strong>Go:</strong> Detects <code>go.mod</code>. Compiles and runs the binary.</li>
          <li><strong>Rust:</strong> Detects <code>Cargo.toml</code>. Builds in release mode.</li>
          <li><strong>Java:</strong> Detects <code>pom.xml</code> or <code>build.gradle</code>. Builds with Maven/Gradle.</li>
          <li><strong>Static:</strong> Detects <code>index.html</code> with no other backend. Serves via Nginx.</li>
        </ul>

        <h2 style={{ fontSize: "1.2rem", fontWeight: 800, marginBottom: "1rem" }}>Overriding Build & Start Commands</h2>
        <p style={{ marginBottom: "1rem", lineHeight: 1.5 }}>
          If your project is a Node.js or Python app but requires specific build arguments or a different start command, you can place a <code>deployhub.yml</code> file at the root of your repository to override the auto-detected settings:
        </p>
        
        <div style={{ backgroundColor: "var(--bg-elevated)", padding: "1rem", borderRadius: "8px", fontFamily: "'JetBrains Mono', monospace", fontSize: "0.85rem", marginBottom: "2rem", overflowX: "auto" }}>
<pre style={{ margin: 0 }}>
{`# deployhub.yml
buildCommand: "vite build --base=/"
startCommand: "node src/server/index.js"
installCommand: "npm install --legacy-peer-deps"
port: 8080
healthPath: "/health"
buildContext: "./frontend"
env:
  NODE_ENV: "production"
  API_URL: "https://api.example.com"`}
</pre>
        </div>

        <h2 style={{ fontSize: "1.2rem", fontWeight: 800, marginBottom: "1rem" }}>Custom Dockerfile</h2>
        <p style={{ marginBottom: "1.5rem", lineHeight: 1.5 }}>
          For total control, simply place a <code>Dockerfile</code> at the root of your repository (or in the directory you select as your context path). DeployHub will automatically use it instead of generating one.
        </p>
        
        <div style={{ backgroundColor: "var(--bg-elevated)", padding: "1rem", borderRadius: "8px", borderLeft: "4px solid var(--accent-primary)", marginBottom: "1rem" }}>
          <h3 style={{ fontSize: "0.95rem", fontWeight: 700, margin: "0 0 0.5rem 0" }}>💡 Tip for React/Vite Users</h3>
          <p style={{ fontSize: "0.9rem", margin: 0, lineHeight: 1.5 }}>
            If you are deploying a Vite app with an Express backend, ensure your <code>vite.config.js</code> does not have a hardcoded <code>base: '/repo-name/'</code> meant for GitHub Pages, as DeployHub hosts your app at the root <code>/</code> path. You can fix this by updating your config, or using a <code>deployhub.yml</code> to run a custom <code>buildCommand</code> that overrides the base path.
          </p>
        </div>
      </div>
    </div>
  );
}
