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
        skip_dirs = {'node_modules', 'venv', '.venv', '__pycache__', 'dist', 'build'}
        
        base_path = self.repo_path.resolve()
        if not base_path.exists() or not base_path.is_dir():
            return services

        def walk_path(current_path: Path):
            if current_path != base_path:
                if current_path.name in skip_dirs or current_path.name.startswith('.'):
                    return

            rel_path = ""
            if current_path != base_path:
                rel_path = current_path.relative_to(base_path).as_posix()

            try:
                files = {p.name for p in current_path.iterdir() if p.is_file()}
            except Exception:
                return

            if 'package.json' in files:
                services.append(self._analyze_node(str(current_path), rel_path))
            elif any(f in files for f in ['requirements.txt', 'pyproject.toml', 'manage.py']):
                services.append(self._analyze_python(str(current_path), rel_path))
            elif 'composer.json' in files or 'index.php' in files:
                services.append(DetectedService(name=current_path.name or self._repo_name, path=rel_path, type="php"))
            elif 'go.mod' in files:
                services.append(DetectedService(name=current_path.name or self._repo_name, path=rel_path, type="go"))
            elif 'Cargo.toml' in files:
                services.append(DetectedService(name=current_path.name or self._repo_name, path=rel_path, type="rust"))
            elif 'pom.xml' in files or 'build.gradle' in files:
                services.append(DetectedService(name=current_path.name or self._repo_name, path=rel_path, type="java"))
            elif 'Gemfile' in files:
                services.append(DetectedService(name=current_path.name or self._repo_name, path=rel_path, type="ruby"))
            elif 'index.html' in files and not any(s.path == rel_path for s in services):
                basename = current_path.name.lower()
                if rel_path == "" or basename in {'public', 'dist', 'build', 'www', 'html', 'client', 'web'}:
                    services.append(DetectedService(
                        name=current_path.name or self._repo_name,
                        path=rel_path,
                        type="static"
                    ))

            try:
                for d in current_path.iterdir():
                    if d.is_dir():
                        walk_path(d)
            except Exception:
                pass

        walk_path(base_path)
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
