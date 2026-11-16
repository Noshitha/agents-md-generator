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


def test_command_evidence_and_working_directories(tmp_path):
    (tmp_path / "README.md").write_text("npm run missing\npytest --verbose\n")
    (tmp_path / "package.json").write_text('{"scripts": {"build": "echo root"}}')
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "package.json").write_text('{"scripts": {"build": "echo frontend", "test:ui": "echo test"}}')
    profile = analyze(str(tmp_path))
    evidence = profile["evidence"]["commands"]
    builds = [item for item in evidence if item["value"] == "npm run build"]
    assert {item["working_directory"] for item in builds} == {".", "frontend"}
    assert all(item["classification"] == "verified" and item["key"] == "scripts.build" for item in builds)
    assert any(item["value"] == "pytest --verbose" and item["classification"] == "documented" for item in evidence)
    generated = generate_agents_md(profile)
    assert "npm run missing" not in generated
    assert "npm run build" in generated and "frontend" in generated
    assert "pytest --verbose" in generated and "Documented" in generated


def test_signal_evidence_and_conservative_guidance(repo):
    profile = analyze(str(repo))
    frameworks = profile["evidence"]["frameworks"]
    risks = profile["evidence"]["risks"]
    assert any(item["value"] == "fastapi" and item["source"] == "backend/app.py" and item["classification"] == "inferred" for item in frameworks)
    assert any(item["value"] == "react" and item["source"] == "frontend/package.json" and item["classification"] == "verified" for item in frameworks)
    assert all(item["classification"] == "inferred" for item in risks)
    assert any(item["key"] == "tool.taskipy.tasks.a" and item["classification"] == "verified" for item in profile["evidence"]["commands"])
    generated = generate_agents_md(profile)
    assert "npm run generate-client" not in generated
    assert "Use `docker compose up -d`" not in generated


def test_legacy_profile_is_not_verified(repo):
    profile = analyze(str(repo))
    del profile["evidence"]
    generated = generate_agents_md(profile)
    assert "unverified" in generated.lower()
    assert "npm run generate-client" not in generated
    assert "Verified configuration" not in generated


def test_escaping_symlinks_are_not_read(tmp_path):
    outside = tmp_path.parent / (tmp_path.name + "_outside")
    outside.mkdir()
    (outside / "package.json").write_text('{"scripts": {"secret": "value"}, "dependencies": {"react": "1"}}')
    (outside / "leak.py").write_text("FastAPI")
    (outside / "README.md").write_text("pytest leaked")
    (tmp_path / "frontend").symlink_to(outside, target_is_directory=True)
    (tmp_path / "backend").symlink_to(outside, target_is_directory=True)
    (tmp_path / "README.md").symlink_to(outside / "README.md")
    profile = analyze(str(tmp_path))
    assert "react" not in profile["frameworks"]
    assert "fastapi" not in profile["frameworks"]
    assert "pytest leaked" not in profile["commands"]["backend"]
    assert "secret" not in json.dumps(profile["evidence"])


def test_readme_npm_is_documented_but_not_promoted(tmp_path):
    (tmp_path / "README.md").write_text("npm run build\nnpm test\n")
    (tmp_path / "package.json").write_text('{"scripts": {"build": "echo build"}}')
    profile = analyze(str(tmp_path))
    evidence = profile["evidence"]["commands"]
    assert any(item["value"] == "npm run build" and item["classification"] == "documented" for item in evidence)
    assert any(item["value"] == "npm run build" and item["classification"] == "verified" for item in evidence)
    generated = generate_agents_md(profile)
    assert generated.count("`npm run build`") == 1
    assert "`npm test`" not in generated
    assert "source: `package.json`: `scripts.build`" in generated


def test_config_symlinks_and_env_are_not_read(tmp_path):
    outside = tmp_path.parent / (tmp_path.name + "_outside")
    outside.mkdir()
    (outside / "pyproject.toml").write_text('[tool.taskipy.tasks]\nleak = "outside secret"\n')
    (tmp_path / "pyproject.toml").symlink_to(outside / "pyproject.toml")
    (tmp_path / ".env").write_text("pytest secret_value")
    (tmp_path / "README.md").symlink_to(tmp_path / ".env")
    profile = analyze(str(tmp_path))
    assert "secret_value" not in json.dumps(profile)
    assert "outside secret" not in json.dumps(profile)
    assert profile["commands"]["pyproject"] == []
    assert profile["commands"]["backend"] == []


def test_invalid_package_scripts_are_not_verified(tmp_path):
    (tmp_path / "README.md").write_text("npm run missing\n")
    (tmp_path / "package.json").write_text('{"scripts": {"missing": null, "build": "echo build"}}')
    profile = analyze(str(tmp_path))
    assert not any(item["value"] == "npm run missing" and item["classification"] == "verified" for item in profile["evidence"]["commands"])
    assert "`npm run missing`" not in generate_agents_md(profile)


def test_package_script_names_are_quoted_and_tasks_do_not_invent_scripts(tmp_path):
    (tmp_path / "package.json").write_text('{"scripts": {"bad; echo injected": "echo ok", "": "echo no"}}')
    (tmp_path / "pyproject.toml").write_text('[tool.taskipy.tasks]\nfrontend = "npm run missing"\n')
    profile = analyze(str(tmp_path))
    generated = generate_agents_md(profile)
    assert "npm run 'bad; echo injected'" in generated
    assert "npm run missing" not in generated
    assert not any(item["key"] == "scripts." for item in profile["evidence"]["commands"])


def test_framework_classification_is_visible(repo):
    generated = generate_agents_md(analyze(str(repo)))
    assert "Configuration: react, vite; inferred: fastapi, sqlmodel" in generated


def test_package_file_symlink_outside_is_ignored(tmp_path):
    outside = tmp_path.parent / (tmp_path.name + "_outside")
    outside.mkdir()
    (outside / "package.json").write_text('{"scripts": {"external": "echo external"}}')
    (tmp_path / "package.json").symlink_to(outside / "package.json")
    profile = analyze(str(tmp_path))
    assert "npm run external" not in profile["commands"]["frontend"]
    assert not profile["evidence"]["commands"]


def test_commands_with_credentials_are_not_recorded(tmp_path):
    (tmp_path / "README.md").write_text("pip install https://user:pass@example.invalid/package\npytest --token=private-value\n")
    (tmp_path / "pyproject.toml").write_text('[tool.taskipy.tasks]\nsecret_task = "echo token=private-value"\n')
    profile = analyze(str(tmp_path))
    assert "private-value" not in json.dumps(profile)
    assert "user:pass" not in json.dumps(profile)
