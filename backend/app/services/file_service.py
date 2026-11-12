import os
import json
import shutil
from pathlib import Path

# Đường dẫn tuyệt đối đến thư mục sandbox
SANDBOX_DIR = Path(__file__).resolve().parent.parent.parent.parent / "sandbox"

SOURCE_SUFFIXES = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue", ".svelte", ".html", ".css", ".scss", ".json", ".toml", ".ini", ".yml", ".yaml", ".txt", ".md", ".conf", ".sql", ".example"}
IGNORED_DIRS = {"node_modules", ".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".sdlc", "dist", "build", ".next", "coverage"}


def project_path(id_project: str) -> Path:
    root = SANDBOX_DIR.resolve()
    target = (root / id_project).resolve()
    if target == root or not target.is_relative_to(root):
        raise ValueError("Invalid project sandbox path")
    return target


def is_test_path(name: str) -> bool:
    path = Path(name.replace("\\", "/"))
    return (bool({"tests", "__tests__", "test"}.intersection(path.parts))
            or path.name.startswith("test_") or ".test." in path.name
            or ".spec." in path.name or path.name == "conftest.py")


def source_snapshot(id_project: str, include_tests: bool = False) -> dict:
    root = project_path(id_project)
    files = []
    if not root.exists():
        return {"files": files}
    for directory, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in IGNORED_DIRS)
        for name in sorted(names):
            path = Path(directory) / name
            rel = path.relative_to(root).as_posix()
            if path.is_symlink() or (name.startswith(".env") and not name.endswith((".example", ".sample"))):
                continue
            if not include_tests and is_test_path(rel):
                continue
            if path.suffix.lower() not in SOURCE_SUFFIXES and name not in {"Dockerfile", ".dockerignore", ".gitignore"}:
                continue
            if name in {"package-lock.json", "yarn.lock", "pnpm-lock.yaml"} or path.stat().st_size > 500_000:
                continue
            files.append({"file_path": rel, "code": path.read_text(encoding="utf-8", errors="replace")})
    return {"files": files}


def source_context(id_project: str, preferred=(), max_chars: int = 90000) -> str:
    """Keep complete selected files and the complete tree; never slice a JSON payload."""
    files = source_snapshot(id_project)["files"]
    preferred = set(preferred)
    def priority(item):
        path = item["file_path"]
        if path in preferred:
            return 0
        if Path(path).name in {"package.json", "requirements.txt", "pyproject.toml", "main.py", "server.js", "app.js", "index.html", "docker-compose.yml", "Dockerfile"}:
            return 1
        if any(part in path.lower() for part in ("config", "database", "routes", "router", "schema", "service")):
            return 2
        return 3
    result = ["PROJECT FILES:\n" + "\n".join(f["file_path"] for f in files)]
    used = len(result[0])
    for item in sorted(files, key=lambda f: (priority(f), f["file_path"])):
        chunk = f"\n--- {item['file_path']} ---\n{item['code']}\n"
        if used + len(chunk) <= max_chars:
            result.append(chunk)
            used += len(chunk)
        else:
            result.append(f"\n[Content omitted: {item['file_path']}]")
    return "".join(result)


def merge_dependency_manifest(path: Path, code: str) -> str:
    """Partial agent patches must not discard another module's dependencies/scripts."""
    if not path.exists():
        return code
    if path.name == "package.json":
        old, new = json.loads(path.read_text(encoding="utf-8")), json.loads(code)
        merged = {**old, **new}
        for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies", "scripts"):
            if key in old or key in new:
                merged[key] = {**old.get(key, {}), **new.get(key, {})}
        return json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
    if path.name == "requirements.txt":
        import re
        lines = {}
        for text in (path.read_text(encoding="utf-8"), code):
            for line in text.splitlines():
                value = line.strip()
                if not value:
                    continue
                match = re.match(r"([a-zA-Z0-9_.-]+)(?:\[|\s|[<>=!~;]|$)", value)
                key = re.sub(r"[-_.]+", "-", match.group(1)).lower() if match else value
                lines[key] = line
        return "\n".join(lines.values()) + "\n"
    return code


def export_code_to_sandbox(id_project: str, code_json_str: str):
    """Validate all paths/content before writing; preserve dotfiles and source strings."""
    from app.services.json_utils import extract_pure_json, merge_code_files
    try:
        data = json.loads(merge_code_files('{"files": []}', extract_pure_json(code_json_str)))
        root = project_path(id_project)
        prepared = []
        for item in data["files"]:
            rel = item["file_path"].replace("\\", "/")
            if rel.startswith("/") or ":" in rel or ".." in Path(rel).parts or ".sdlc" in Path(rel).parts:
                raise ValueError(f"Unsafe generated path: {rel}")
            target = (root / rel).resolve()
            if target == root or not target.is_relative_to(root):
                raise ValueError(f"Unsafe generated path: {rel}")
            prepared.append((target, merge_dependency_manifest(target, item["code"]), rel))
        for target, code, rel in prepared:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(code, encoding="utf-8")
        return True, [item[2] for item in prepared]
    except Exception as exc:
        return False, str(exc)


def save_module_snapshot(id_project: str, module_id: str, attempt: int):
    """Chụp ảnh (Backup) mã nguồn của module tại một lần thử cụ thể"""
    project_dir = SANDBOX_DIR / id_project
    snapshot_dir = SANDBOX_DIR / f"{id_project}_snapshots" / f"{module_id}_attempt_{attempt}"
    
    if project_dir.exists():
        shutil.copytree(project_dir, snapshot_dir, dirs_exist_ok=True)
    return snapshot_dir

def restore_module_snapshot(id_project: str, module_id: str, best_attempt: int):
    """Khôi phục (Rollback) dự án về phiên bản tốt nhất của module đó"""
    project_dir = SANDBOX_DIR / id_project
    snapshot_dir = SANDBOX_DIR / f"{id_project}_snapshots" / f"{module_id}_attempt_{best_attempt}"
    
    if snapshot_dir.exists():
        # Xóa code hiện tại đang lỗi của attempt 3
        shutil.rmtree(project_dir)
        # Khôi phục về bản snapshot tốt nhất
        shutil.copytree(snapshot_dir, project_dir)
        print(f"--> [HỆ THỐNG] Đã Rollback module '{module_id}' về Attempt {best_attempt} (Best-Effort).")
        return True
    return False