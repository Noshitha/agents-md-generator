import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.analyze_repo import analyze
from src.generate_agents import classify_task, generate_agents_md, select_task_instructions, instruction_metrics
from src.validate_instructions import validate_instructions


@pytest.fixture
def profile(tmp_path):
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "app.py").write_text("from fastapi import FastAPI\nfrom sqlmodel import SQLModel\n")
    (tmp_path / "backend" / "pyproject.toml").write_text('[tool.taskipy.tasks]\ndev = "echo backend-dev"\ncheck = "echo backend-check"\n')
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "package.json").write_text(json.dumps({"scripts": {"build": "vite build", "dev": "vite", "generate-client": "echo generate"}, "dependencies": {"react": "1"}}))
    (tmp_path / "compose.yml").write_text("services: {}")
    (tmp_path / ".env.example").write_text("")
    return analyze(str(tmp_path))


def test_component_selection_and_mandatory_safety(profile):
    full = generate_agents_md(profile)
    backend = select_task_instructions(profile, "Fix backend logging")
    frontend = select_task_instructions(profile, "Fix frontend button styling")
    assert "echo backend-dev" in backend and "npm run dev" not in backend
    assert "npm run dev" in frontend and "echo backend-dev" not in frontend
    assert "npm run build" in backend and "echo backend-check" in frontend
    for selected in (backend, frontend):
        assert selected.split("## Safety Boundaries")[1] == full.split("## Safety Boundaries")[1]
        assert "Auth, JWT, and password flows are security-sensitive" in selected
        assert "Never hardcode credentials" in selected


def test_task_areas_and_cross_component_changes(profile):
    assert "database" in classify_task("Create a database migration", profile)
    assert "security" in classify_task("Fix login authentication", profile)
    assert "docker" in classify_task("Change deployment configuration", profile)
    assert "testing" in classify_task("Improve tests", profile)
    assert {"backend", "frontend"} <= set(classify_task("Change API response schema", profile))
    selected = select_task_instructions(profile, "Change API response schema")
    assert "echo backend-check" in selected and "npm run generate-client" in selected
    assert "frontend API clients" in selected
    assert {"frontend", "database"} <= set(classify_task("Update frontend and database migration", profile))


@pytest.mark.parametrize("task", ["Fix the bug", "", "Maybe fix frontend", "Investigate an unknown issue"])
def test_unknown_and_ambiguous_tasks_keep_full_guidance(profile, task):
    assert select_task_instructions(profile, task) == generate_agents_md(profile)


def test_legacy_and_unverified_information_is_preserved(profile):
    profile["evidence"]["commands"].append({"value": "pytest --custom", "source": "README.md", "type": "documentation", "key": "pytest --custom", "classification": "documented"})
    assert "pytest --custom" in select_task_instructions(profile, "Fix frontend button")
    del profile["evidence"]
    assert select_task_instructions(profile, "Fix frontend button") == generate_agents_md(profile)


def test_metrics_and_determinism(profile):
    full = generate_agents_md(profile)
    selected = select_task_instructions(profile, "Fix frontend button")
    assert selected == select_task_instructions(profile, "Fix frontend button")
    metrics = instruction_metrics(full, selected)
    assert metrics["original_bytes"] == len(full.encode("utf-8"))
    assert metrics["selected_words"] == len(selected.split())
    assert metrics["reduction_percent"] > 0
    assert validate_instructions(selected, Path(profile["repo_path"]), profile) == []


def test_cli_does_not_overwrite_full_output(profile, tmp_path):
    project = Path(__file__).resolve().parents[1]
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "repo_profile.json").write_text(json.dumps(profile))
    full_path = outputs / "generated_AGENTS.md"
    full_path.write_text("original research artifact")
    command = [sys.executable, str(project / "src" / "generate_agents.py"), "--task", "Fix frontend button"]
    first = subprocess.run(command + ["--validate", "--repo", profile["repo_path"]], cwd=tmp_path, text=True, capture_output=True, check=True)
    second = subprocess.run(command, cwd=tmp_path, text=True, capture_output=True, check=True)
    assert first.stdout == second.stdout
    assert "Validation findings" in first.stderr
    assert "original_bytes" in first.stderr
    assert full_path.read_text() == "original research artifact"
    target = tmp_path / "selected.md"
    subprocess.run(command + ["--output", str(target)], cwd=tmp_path, capture_output=True, check=True)
    assert target.read_text() == first.stdout
    failed = subprocess.run(command + ["--output", str(full_path)], cwd=tmp_path, capture_output=True)
    assert failed.returncode != 0
    assert full_path.read_text() == "original research artifact"


def test_default_cli_and_task_output_preserve_generated_file(profile, tmp_path):
    project = Path(__file__).resolve().parents[1]
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "repo_profile.json").write_text(json.dumps(profile))
    command = [sys.executable, str(project / "src" / "generate_agents.py")]
    subprocess.run(command, cwd=tmp_path, capture_output=True, check=True)
    assert (outputs / "generated_AGENTS.md").read_text() == generate_agents_md(profile)


def test_validation_reports_issues_excluded_from_selection(profile, tmp_path):
    project = Path(__file__).resolve().parents[1]
    repo = Path(profile["repo_path"])
    package = repo / "backend" / "package.json"
    package.write_text('{"scripts": {"dev": "echo dev"}}')
    profile = analyze(str(repo))
    package.write_text('{"scripts": {}}')
    outputs = tmp_path / "outputs"
    outputs.mkdir(exist_ok=True)
    (outputs / "repo_profile.json").write_text(json.dumps(profile))
    command = [sys.executable, str(project / "src" / "generate_agents.py"), "--task", "Fix frontend styling", "--validate", "--repo", str(repo)]
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, check=True)
    report = result.stderr.split("Validation findings (full and selected):\n", 1)[1]
    findings = json.loads(report)
    assert "npm_script_missing" in {item["rule"] for item in findings["full"]}
    assert "npm_script_missing" not in {item["rule"] for item in findings["selected"]}


def test_unknown_scope_and_non_dev_commands_are_retained(profile):
    evidence = profile["evidence"]["commands"]
    evidence.append({"value": "echo backend-start", "source": "backend/pyproject.toml", "type": "pyproject.toml", "key": "tool.taskipy.tasks.start", "classification": "verified", "working_directory": "backend"})
    evidence.append({"value": "echo unknown", "source": "README.md", "type": "documentation", "key": "echo unknown", "classification": "documented"})
    selected = select_task_instructions(profile, "Fix frontend button")
    assert "echo backend-start" in selected
    assert "echo unknown" in selected


def test_conservative_tasks_keep_full_guidance(profile):
    for task in ("Create database migration", "Fix login authentication", "Change Docker deployment", "Improve tests"):
        assert select_task_instructions(profile, task) == generate_agents_md(profile)


def test_api_endpoint_keeps_both_components_and_does_not_mutate_profile(profile):
    before = json.dumps(profile, sort_keys=True)
    selected = select_task_instructions(profile, "Change API endpoint")
    assert "echo backend-dev" in selected
    assert "npm run dev" in selected
    assert json.dumps(profile, sort_keys=True) == before
