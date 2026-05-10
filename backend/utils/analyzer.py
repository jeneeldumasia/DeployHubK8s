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
    def __init__(self, repo_path: str | Path):
        self.repo_path = Path(repo_path)

    def analyze(self) -> List[DetectedService]:
        services = []
        
        # We perform a recursive scan, but skip common heavy directories
        skip_dirs = {'.git', 'node_modules', 'venv', '.venv', '__pycache__', 'dist', 'build'}
        
        for root, dirs, files in os.walk(self.repo_path):
            # Modify dirs in-place to skip unwanted ones
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            
            rel_path = os.path.relpath(root, self.repo_path)
            if rel_path == '.':
                rel_path = ""

            # 1. Check for Node.js
            if 'package.json' in files:
                services.append(self._analyze_node(root, rel_path))
                # If we find a package.json, we usually don't need to look deeper in THIS specific folder
                # unless it's a monorepo root (but we'll handle subfolders separately anyway)
            
            # 2. Check for Python
            elif any(f in files for f in ['requirements.txt', 'pyproject.toml', 'manage.py']):
                services.append(self._analyze_python(root, rel_path))

            # 3. Check for Static (HTML) - only if no other service found in this dir
            elif 'index.html' in files and not any(s.path == rel_path for s in services):
                services.append(DetectedService(
                    name=os.path.basename(root) or "root-static",
                    path=rel_path,
                    type="static"
                ))

        return services

    def _analyze_node(self, full_path: str, rel_path: str) -> DetectedService:
        name = os.path.basename(full_path) or "root-node"
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
        name = os.path.basename(full_path) or "root-python"
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
