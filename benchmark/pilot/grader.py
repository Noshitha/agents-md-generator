import hashlib


def acceptance(query, grading_nonce):
    nonce = hashlib.sha256((grading_nonce + ":pilot-command-order").encode()).hexdigest()[:16]
    backend = [f"pytest -k {nonce}{number}" for number in range(5)] + ["pip list", "python -V"]
    frontend = ["npm run build", "npm run lint"]
    files = {
        "README.md": "\n".join(backend + frontend),
        "compose.yml": "services: {}",
        "pyproject.toml": '[tool.pytest.ini_options]\naddopts = "-q"\n[tool.ruff]\nline-length = 88\n',
    }
    expected = {
        "backend": sorted(backend),
        "frontend": sorted(frontend),
        "docker": sorted(["docker compose up -d", "docker compose down", "docker compose logs"]),
        "pyproject": sorted(["pytest", "ruff check ."]),
    }
    for seed in ("1", "2", "3", "4", "5"):
        result = query({"files": files}, seed)
        if result.get("commands") != expected:
            raise AssertionError("Command lists differ from expected sorted values")


def regression(query, grading_nonce):
    profile = query({"files": {}}, "1")
    expected = {
        "repo_name": "fixture",
        "top_level_dirs": [],
        "top_level_files": [],
        "commands": {"backend": [], "frontend": [], "docker": [], "pyproject": []},
        "inferred_risks": [],
        "summary": {"has_backend": False, "has_frontend": False, "has_docker": False, "has_env_example": False},
    }
    for key, value in expected.items():
        if profile.get(key) != value:
            raise AssertionError(f"Unexpected profile field: {key}")
