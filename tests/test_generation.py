import json
import subprocess
import sys

import pytest

from src.analyze_repo import analyze
from src.generate_agents import generate_agents_md


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "README.md").write_text("pytest\npip install example\npytest\nnpm run build\n")
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "app.py").write_text("from fastapi import FastAPI\nfrom sqlmodel import SQLModel\n")
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "package.json").write_text(json.dumps({"scripts": {"z-test": "z", "build": "b"}, "dependencies": {"react": "1", "vite": "1"}}))
    (tmp_path / "pyproject.toml").write_text('[tool.pytest.ini_options]\naddopts = "-q"\n[tool.taskipy.tasks]\nz = "echo z"\na = "echo a"\n')
    (tmp_path / "compose.yml").write_text("services: {}\n")
    (tmp_path / ".env.example").write_text("")
    return tmp_path


def test_repeated_analysis_and_generation_across_hash_seeds(repo):
    code = '''import json, sys
from src.analyze_repo import analyze
from src.generate_agents import generate_agents_md
profile = analyze(sys.argv[1])
print(json.dumps([profile, generate_agents_md(profile)]))
'''
    outputs = []
    for seed in ("1", "2", "42"):
        env = {"PYTHONHASHSEED": seed}
        outputs.append(subprocess.check_output([sys.executable, "-c", code, str(repo)], env=env, text=True))
    assert outputs[0] == outputs[1] == outputs[2]
    profile, generated = json.loads(outputs[0])
    assert profile == analyze(str(repo))
    assert generated == generate_agents_md(profile)
    assert profile["commands"]["backend"] == ["pip install example", "pytest"]
    assert profile["commands"]["pyproject"] == ["echo a", "echo z", "pytest"]
    assert profile["inferred_risks"] == [
        "backend_frontend_api_contract_drift",
        "database_model_or_schema_change",
        "secrets_or_environment_config",
        "local_service_dependency_docker",
        "auth_or_backend_security_sensitive_change",
    ]


def test_missing_configuration(tmp_path):
    profile = analyze(str(tmp_path))
    assert profile["commands"] == {"backend": [], "frontend": [], "docker": [], "pyproject": []}
    assert profile["inferred_risks"] == []
    assert "- None detected" in generate_agents_md(profile)


@pytest.mark.parametrize("toml", ["[invalid", 'tool = "invalid"', '[tool.taskipy]\ntasks = "invalid"'])
def test_malformed_configuration(tmp_path, toml):
    (tmp_path / "pyproject.toml").write_text(toml)
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "package.json").write_text("{invalid")
    profile = analyze(str(tmp_path))
    assert profile["commands"]["pyproject"] == []
    assert profile["commands"]["frontend"] == []


def test_malformed_root_config_does_not_hide_backend_commands(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[invalid")
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "pyproject.toml").write_text('[tool.ruff]\nline-length = 100\n')
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "package.json").write_text('{"scripts": "invalid"}')
    profile = analyze(str(tmp_path))
    assert profile["commands"]["pyproject"] == ["ruff check ."]
    assert profile["commands"]["frontend"] == []
