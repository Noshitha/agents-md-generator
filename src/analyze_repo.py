import json
import os
import re
import shlex
from pathlib import Path


IMPORTANT_FILES = [
    "README.md",
    "docker-compose.yml",
    "docker-compose.override.yml",
    "compose.yml",
    "compose.override.yml",
    "pyproject.toml",
    "package.json",
    ".env",
    ".env.example",
    ".github/workflows",
]



def safe_path(repo_path: Path, path: Path):
    try:
        return path.resolve().is_relative_to(repo_path.resolve())
    except (OSError, RuntimeError, ValueError):
        return False


def read_repo_file(repo_path: Path, path: Path):
    if not safe_path(repo_path, path):
        return None
    if path.resolve().name == ".env" or path.resolve().name.startswith(".env."):
        return None
    try:
        return path.read_text(errors="ignore")
    except (OSError, ValueError):
        return None


def repo_files(repo_path: Path):
    files = []
    for directory, dirs, names in os.walk(repo_path, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in {".git", "node_modules", ".venv"} and not (Path(directory) / d).is_symlink() and safe_path(repo_path, Path(directory) / d))
        for name in sorted(names):
            path = Path(directory) / name
            if safe_path(repo_path, path):
                files.append(path)
    return files


def sensitive_command(command):
    return bool(re.search(r"(?i)(?:password|passwd|secret|token|api[_-]?key|authorization|credential|://[^/\s]+@)", command))


def add_evidence(evidence, value, source, source_type, key, classification, working_directory=None):
    if evidence is not None:
        item = {"value": value, "source": source, "type": source_type, "key": key, "classification": classification}
        if working_directory is not None:
            item["working_directory"] = working_directory
        if item not in evidence:
            evidence.append(item)

def list_top_level(repo_path: Path):
    dirs, files = [], []

    for item in repo_path.iterdir():
        if item.name.startswith(".git") or not safe_path(repo_path, item):
            continue
        if item.is_dir():
            dirs.append(item.name)
        else:
            files.append(item.name)

    return sorted(dirs), sorted(files)


def find_files(repo_path: Path, names):
    found = []
    for name in names:
        path = repo_path / name
        if safe_path(repo_path, path) and path.exists():
            found.append(name)
    return found


def detect_languages(repo_path: Path):
    languages = set()
    files = repo_files(repo_path)

    if safe_path(repo_path, repo_path / "backend") and (repo_path / "backend").exists():
        languages.add("python")
    if safe_path(repo_path, repo_path / "frontend") and (repo_path / "frontend").exists():
        languages.add("typescript")
    if any(p.suffix == ".py" for p in files):
        languages.add("python")
    if any(p.suffix in {".ts", ".tsx"} for p in files):
        languages.add("typescript")
    if any(p.name == "Dockerfile" or p.name.startswith(("docker-compose", "compose")) and p.suffix == ".yml" for p in files):
        languages.add("docker")
    return sorted(languages)


def detect_frameworks(repo_path: Path, evidence=None):
    frameworks = set()
    for path in repo_files(repo_path):
        relative = path.relative_to(repo_path).as_posix()
        if relative.startswith("backend/") and path.suffix == ".py":
            text = read_repo_file(repo_path, path)
            if text is not None:
                for name in ("fastapi", "sqlmodel"):
                    if name in text[:5000].lower():
                        frameworks.add(name)
                        add_evidence(evidence, name, relative, "source", name, "inferred")
        elif path.name == "package.json":
            text = read_repo_file(repo_path, path)
            try:
                data = json.loads(text) if text is not None else {}
                for section in ("dependencies", "devDependencies"):
                    dependencies = data.get(section, {})
                    if isinstance(dependencies, dict):
                        for name in ("react", "vite"):
                            if name in dependencies:
                                frameworks.add(name)
                                add_evidence(evidence, name, relative, "package.json", f"{section}.{name}", "verified")
            except (ValueError, AttributeError):
                pass
    return sorted(frameworks)


def detect_commands_from_pyproject(repo_path: Path, evidence=None):
    import tomllib

    candidates = [repo_path / "pyproject.toml", repo_path / "backend" / "pyproject.toml"]
    commands = []
    for pyproject in candidates:
        text = read_repo_file(repo_path, pyproject)
        if text is None:
            continue
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            continue
        tools = data.get("tool", {})
        if not isinstance(tools, dict):
            continue
        source = pyproject.relative_to(repo_path).as_posix()
        directory = pyproject.parent.relative_to(repo_path).as_posix()
        if tools.get("pytest"):
            commands.append("pytest")
            add_evidence(evidence, "pytest", source, "pyproject.toml", "tool.pytest", "inferred", directory)
        if tools.get("ruff"):
            commands.append("ruff check .")
            add_evidence(evidence, "ruff check .", source, "pyproject.toml", "tool.ruff", "inferred", directory)
        taskipy = tools.get("taskipy", {})
        if isinstance(taskipy, dict):
            scripts = taskipy.get("tasks", taskipy)
            if isinstance(scripts, dict):
                for name, value in scripts.items():
                    if isinstance(value, str) and not sensitive_command(name) and not sensitive_command(value):
                        commands.append(value)
                        key = f"tool.taskipy.tasks.{name}" if "tasks" in taskipy else f"tool.taskipy.{name}"
                        add_evidence(evidence, value, source, "pyproject.toml", key, "verified", directory)
    return sorted(set(commands))


def detect_commands(repo_path: Path, evidence=None):
    commands = {"backend": [], "frontend": [], "docker": [], "pyproject": []}
    readme = repo_path / "README.md"
    text = read_repo_file(repo_path, readme)
    if text is not None:
        for line in text.splitlines():
            stripped = line.strip()
            category = None
            if stripped.startswith(("docker ", "docker-compose")):
                category = "docker"
            elif stripped.startswith(("pytest", "python ", "uv ", "poetry ", "pip ", "alembic ")):
                category = "backend"
            elif stripped.startswith(("npm ", "pnpm ", "yarn ", "bun ")):
                category = "frontend"
            if category and not sensitive_command(stripped):
                commands[category].append(stripped)
                add_evidence(evidence, stripped, "README.md", "documentation", stripped, "documented", None)

    for compose_file in ["compose.yml", "docker-compose.yml"]:
        path = repo_path / compose_file
        if safe_path(repo_path, path) and path.is_file():
            for command in ("docker compose up -d", "docker compose down", "docker compose logs"):
                commands["docker"].append(command)
                add_evidence(evidence, command, compose_file, "configuration", "compose file", "inferred", ".")
            break
    for package in (p for p in repo_files(repo_path) if p.name == "package.json"):
        text = read_repo_file(repo_path, package)
        try:
            pkg = json.loads(text) if text is not None else {}
            scripts = pkg.get("scripts", {})
            if isinstance(scripts, dict):
                for name, value in sorted(scripts.items()):
                    if isinstance(value, str) and name and not name.startswith("-") and not sensitive_command(name):
                        command = f"npm run {shlex.quote(name)}"
                        commands["frontend"].append(command)
                        add_evidence(evidence, command, package.relative_to(repo_path).as_posix(), "package.json", f"scripts.{name}", "verified", package.parent.relative_to(repo_path).as_posix())
        except (ValueError, AttributeError):
            pass
    commands["pyproject"] = detect_commands_from_pyproject(repo_path, evidence)
    for key in commands:
        commands[key] = sorted(set(commands[key]))
    return commands


def infer_risks(repo_path: Path, frameworks, important_files):
    risks = []

    if "fastapi" in frameworks and "react" in frameworks:
        risks.append("backend_frontend_api_contract_drift")

    if "sqlmodel" in frameworks:
        risks.append("database_model_or_schema_change")

    if ".env" in important_files or ".env.example" in important_files:
        risks.append("secrets_or_environment_config")

    if any(name in important_files for name in ("docker-compose.yml", "compose.yml")):
        risks.append("local_service_dependency_docker")

    if safe_path(repo_path, repo_path / "backend") and (repo_path / "backend").exists():
        risks.append("auth_or_backend_security_sensitive_change")

    return risks


def analyze(repo_path: str):
    repo_path = Path(repo_path).resolve()

    dirs, files = list_top_level(repo_path)
    important_files = find_files(repo_path, IMPORTANT_FILES)
    languages = detect_languages(repo_path)
    evidence = {"commands": [], "frameworks": [], "risks": []}
    frameworks = detect_frameworks(repo_path, evidence["frameworks"])
    commands = detect_commands(repo_path, evidence["commands"])
    risks = infer_risks(repo_path, frameworks, important_files)
    for risk in risks:
        if risk == "backend_frontend_api_contract_drift":
            sources = [item["source"] for item in evidence["frameworks"] if item["value"] in ("fastapi", "react")]
        elif risk == "database_model_or_schema_change":
            sources = [item["source"] for item in evidence["frameworks"] if item["value"] == "sqlmodel"]
        elif risk == "secrets_or_environment_config":
            sources = [name for name in (".env", ".env.example") if name in important_files]
        elif risk == "local_service_dependency_docker":
            sources = [name for name in ("compose.yml", "docker-compose.yml") if name in important_files]
        else:
            sources = ["backend"] if "backend" in dirs else []
        for source in sorted(set(sources)):
            add_evidence(evidence["risks"], risk, source, "repository signal", risk, "inferred")
    for items in evidence.values():
        items.sort(key=lambda item: (item["value"], item["source"], item["key"]))

    profile = {
        "repo_name": repo_path.name,
        "repo_path": str(repo_path),
        "top_level_dirs": dirs,
        "top_level_files": files,
        "important_files": important_files,
        "languages": languages,
        "frameworks": frameworks,
        "commands": commands,
        "inferred_risks": risks,
        "evidence": evidence,
        "summary": {
            "has_backend": "backend" in dirs,
            "has_frontend": "frontend" in dirs,
            "has_docker": any("docker" in f.lower() or "compose" in f.lower() for f in files),
            "has_env_example": ".env.example" in files or ".env" in files,
        },
    }

    return profile


if __name__ == "__main__":
    repo = "target_repos/full-stack-fastapi-template"
    profile = analyze(repo)

    output_path = Path("outputs/repo_profile.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(profile, indent=2))

    print(json.dumps(profile, indent=2))
    print(f"\nWrote {output_path}")