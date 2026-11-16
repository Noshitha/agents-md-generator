import json
import os
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


def list_top_level(repo_path: Path):
    dirs, files = [], []

    for item in repo_path.iterdir():
        if item.name.startswith(".git"):
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
        if path.exists():
            found.append(name)
    return found


def detect_languages(repo_path: Path):
    languages = set()

    if (repo_path / "backend").exists():
        languages.add("python")
    if (repo_path / "frontend").exists():
        languages.add("typescript")
    if list(repo_path.rglob("*.py")):
        languages.add("python")
    if list(repo_path.rglob("*.ts")) or list(repo_path.rglob("*.tsx")):
        languages.add("typescript")
    if list(repo_path.rglob("Dockerfile")) or list(repo_path.rglob("docker-compose*.yml")) or list(repo_path.rglob("compose*.yml")):
        languages.add("docker")

    return sorted(languages)


def detect_frameworks(repo_path: Path):
    frameworks = []

    backend = repo_path / "backend"
    frontend = repo_path / "frontend"

    if backend.exists():
        backend_text = " ".join(
            p.read_text(errors="ignore")[:5000]
            for p in backend.rglob("*.py")
            if p.is_file()
        )
        if "FastAPI" in backend_text or "fastapi" in backend_text:
            frameworks.append("fastapi")
        if "SQLModel" in backend_text or "sqlmodel" in backend_text:
            frameworks.append("sqlmodel")

    if frontend.exists():
        package_json = frontend / "package.json"
        if package_json.exists():
            text = package_json.read_text(errors="ignore")
            if "react" in text.lower():
                frameworks.append("react")
            if "vite" in text.lower():
                frameworks.append("vite")

    return sorted(set(frameworks))

def detect_commands_from_pyproject(repo_path: Path):
    import tomllib

    candidates = [repo_path / "pyproject.toml", repo_path / "backend" / "pyproject.toml"]
    commands = []

    for pyproject in candidates:
        if not pyproject.exists():
            continue
        try:
            with open(pyproject, "rb") as f:
                data = tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError):
            continue
        tools = data.get("tool", {})
        if not isinstance(tools, dict):
            continue
        # extract pytest config
        if tools.get("pytest"):
            commands.append("pytest")
        # extract ruff/lint
        if tools.get("ruff"):
            commands.append("ruff check .")
        # extract scripts
        taskipy = tools.get("taskipy", {})
        if isinstance(taskipy, dict):
            scripts = taskipy.get("tasks", taskipy)
            if isinstance(scripts, dict):
                commands.extend(value for value in scripts.values() if isinstance(value, str))

    return sorted(set(commands))

def detect_commands(repo_path: Path):
    commands = {
        "backend": [],
        "frontend": [],
        "docker": [],
        "pyproject": [],
    }

    # --- from README (bare lines + fenced code blocks) ---
    readme = repo_path / "README.md"
    if readme.exists():
        import re
        text = readme.read_text(errors="ignore")
        # collect lines both inside and outside code blocks
        all_lines = text.splitlines()
        code_block_lines = [
            line
            for block in re.findall(r"```(?:bash|sh|shell|console)?\n(.*?)```", text, re.DOTALL)
            for line in block.splitlines()
        ]
        candidate_lines = list(set(all_lines + code_block_lines))
        for line in candidate_lines:
            stripped = line.strip()
            if stripped.startswith(("docker ", "docker compose", "docker-compose")):
                commands["docker"].append(stripped)
            if stripped.startswith(("pytest", "python ", "uv ", "poetry ", "pip ", "alembic ")):
                commands["backend"].append(stripped)
            if stripped.startswith(("npm ", "pnpm ", "yarn ", "bun ")):
                commands["frontend"].append(stripped)
                
    # --- from compose files directly ---
    for compose_file in ["compose.yml", "docker-compose.yml"]:
        if (repo_path / compose_file).exists():
            commands["docker"].append(f"docker compose up -d")
            commands["docker"].append(f"docker compose down")
            commands["docker"].append(f"docker compose logs")
            break
    # --- from frontend/package.json ---
    frontend_package = repo_path / "frontend" / "package.json"
    if frontend_package.exists():
        try:
            pkg = json.loads(frontend_package.read_text(errors="ignore"))
            scripts = pkg.get("scripts", {})
            if isinstance(scripts, dict):
                for name in scripts:
                    commands["frontend"].append(f"npm run {name}")
        except Exception:
            pass

    # --- from pyproject.toml ---
    commands["pyproject"] = detect_commands_from_pyproject(repo_path)

    # deduplicate
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

    if (repo_path / "docker-compose.yml").exists() or (repo_path / "compose.yml").exists():
        risks.append("local_service_dependency_docker")

    if (repo_path / "backend").exists():
        risks.append("auth_or_backend_security_sensitive_change")

    return risks


def analyze(repo_path: str):
    repo_path = Path(repo_path).resolve()

    dirs, files = list_top_level(repo_path)
    important_files = find_files(repo_path, IMPORTANT_FILES)
    languages = detect_languages(repo_path)
    frameworks = detect_frameworks(repo_path)
    commands = detect_commands(repo_path)
    risks = infer_risks(repo_path, frameworks, important_files)

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