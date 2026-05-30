import os
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class DetectedService:
    name: str
    path: str  # Relative to repo root
    type: str  # 'node', 'python', 'static', 'go', etc.
    framework: Optional[str] = None
    entrypoint: Optional[str] = None

class RepoAnalyzer:
    def __init__(self, repo_path: str | Path, repo_name: str | None = None):
        self.repo_path = Path(repo_path)
        # Use provided name, or fall back to the directory name
        self._repo_name = repo_name or self.repo_path.name

    def analyze(self) -> List[DetectedService]:
        services = []
        
        # We perform a recursive scan, but skip common heavy and hidden/cache directories
        skip_dirs = {'node_modules', 'venv', '.venv', '__pycache__', 'dist', 'build'}
        
        for root, dirs, files in os.walk(self.repo_path):
            # Modify dirs in-place to skip unwanted ones and any hidden directories (starting with '.')
            dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith('.')]
            
            rel_path = os.path.relpath(root, self.repo_path)
            if rel_path == '.':
                rel_path = ""

            # 1. Check for Node.js
            if 'package.json' in files:
                services.append(self._analyze_node(root, rel_path))
            
            # 2. Check for Python
            elif any(f in files for f in ['requirements.txt', 'pyproject.toml', 'manage.py']):
                services.append(self._analyze_python(root, rel_path))

            # 3. Check for PHP
            elif 'composer.json' in files or 'index.php' in files:
                services.append(DetectedService(name=os.path.basename(root) or self._repo_name, path=rel_path, type="php"))

            # 4. Check for Go
            elif 'go.mod' in files:
                services.append(DetectedService(name=os.path.basename(root) or self._repo_name, path=rel_path, type="go"))

            # 5. Check for Rust
            elif 'Cargo.toml' in files:
                services.append(DetectedService(name=os.path.basename(root) or self._repo_name, path=rel_path, type="rust"))

            # 6. Check for Java
            elif 'pom.xml' in files or 'build.gradle' in files:
                services.append(DetectedService(name=os.path.basename(root) or self._repo_name, path=rel_path, type="java"))

            # 7. Check for Ruby
            elif 'Gemfile' in files:
                services.append(DetectedService(name=os.path.basename(root) or self._repo_name, path=rel_path, type="ruby"))

            # 8. Check for Static (HTML) 
            # Restrict to root or common web build directories to avoid legacy PHP dummy index.html files
            elif 'index.html' in files and not any(s.path == rel_path for s in services):
                basename = os.path.basename(root).lower()
                if rel_path == "" or basename in {'public', 'dist', 'build', 'www', 'html', 'client', 'web'}:
                    services.append(DetectedService(
                        name=os.path.basename(root) or self._repo_name,
                        path=rel_path,
                        type="static"
                    ))

        return services

    def _analyze_node(self, full_path: str, rel_path: str) -> DetectedService:
        # If at repo root, use repo name; otherwise use directory name
        name = (self._repo_name if not rel_path else os.path.basename(full_path)) or "app"
        framework = None
        
        # Simple framework detection
        pkg_json_path = Path(full_path) / "package.json"
        try:
            with open(pkg_json_path, 'r') as f:
                content = f.read()
                if '"next"' in content: framework = "nextjs"
                elif '"vite"' in content: framework = "vite"
                elif '"express"' in content: framework = "express"
        except:
            pass

        return DetectedService(
            name=name,
            path=rel_path,
            type="node",
            framework=framework
        )

    def _analyze_python(self, full_path: str, rel_path: str) -> DetectedService:
        # If at repo root, use repo name; otherwise use directory name
        name = (self._repo_name if not rel_path else os.path.basename(full_path)) or "app"
        framework = None
        
        # Simple framework detection
        files = os.listdir(full_path)
        if 'manage.py' in files: framework = "django"
        
        req_path = Path(full_path) / "requirements.txt"
        if req_path.exists():
            try:
                content = req_path.read_text().lower()
                if "fastapi" in content: framework = "fastapi"
                elif "flask" in content: framework = "flask"
            except:
                pass

        return DetectedService(
            name=name,
            path=rel_path,
            type="python",
            framework=framework
        )
