import json

import pytest

from src.analyze_repo import analyze
from src.generate_agents import generate_agents_md
from src.validate_instructions import validate_instructions


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "package.json").write_text(json.dumps({"scripts": {"build": "vite build"}, "dependencies": {"react": "1"}}))
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "app.py").write_text("from fastapi import FastAPI\n")
    return tmp_path


def rules(findings):
    return {item["rule"] for item in findings}


def test_npm_scripts_and_working_directories(repo):
    profile = analyze(str(repo))
    assert not rules(validate_instructions("Run `npm run build` (working directory: `frontend`).", repo, profile))
    assert "npm_script_missing" in rules(validate_instructions("Run `npm run missing` (working directory: `frontend`).", repo, profile))
    assert "working_directory" in rules(validate_instructions("Run `npm run build`.", repo, profile))
    assert "working_directory" in rules(validate_instructions("Run `npm run build` (working directory: `backend`).", repo, profile))
    assert not rules(validate_instructions("Run `cd frontend && npm run build`.", repo, profile))


def test_missing_or_malformed_package_is_unverified(repo):
    (repo / "frontend" / "package.json").write_text("invalid")
    findings = validate_instructions("Run `npm run build` (working directory: `frontend`).", repo, {})
    assert findings[0]["severity"] == "unverified"
    assert findings[0]["rule"] == "npm_unverified"


def test_explicit_paths(repo):
    assert not rules(validate_instructions("Inspect `backend/app.py`.", repo, {}))
    findings = validate_instructions("Inspect `backend/missing.py`.", repo, {})
    assert findings[0]["rule"] == "path_missing"
    assert findings[0]["severity"] == "error"
    assert not rules(validate_instructions("The example `backend/missing.py` illustrates a path.", repo, {}))
    assert not rules(validate_instructions("Create `backend/new.py`.", repo, {}))


def test_framework_evidence(repo):
    profile = analyze(str(repo))
    assert not rules(validate_instructions("The project uses React.", repo, profile))
    findings = validate_instructions("The project uses FastAPI.", repo, profile)
    assert findings[0]["rule"] == "framework_unverified"
    assert findings[0]["severity"] == "unverified"
    findings = validate_instructions("The project uses Vite.", repo, profile)
    assert findings[0]["rule"] == "framework_conflict"
    assert findings[0]["severity"] == "warning"
    assert findings[0]["evidence"]


def test_legacy_profile_and_verified_command(repo):
    profile = analyze(str(repo))
    findings = validate_instructions("Verified: run `pytest` (working directory: `.`).", repo, profile)
    assert "command_unverified" in rules(findings)
    del profile["evidence"]
    findings = validate_instructions("Verified: run `npm run build` (working directory: `frontend`).", repo, profile)
    assert "command_unverified" in rules(findings)


def test_contradictions_only_for_same_unconditional_action(repo):
    text = "Always run tests.\nNever run tests."
    findings = validate_instructions(text, repo, {})
    assert "contradictory_instruction" in rules(findings)
    assert findings[0]["severity"] == "warning"
    assert not rules(validate_instructions("Always run tests.\nNever run tests automatically.", repo, {}))
    assert not rules(validate_instructions("Always run tests before release.\nNever run tests in production.", repo, {}))


def test_unsafe_commands_and_non_instructions(repo):
    findings = validate_instructions("Run `rm -rf /`.", repo, {})
    assert findings[0]["rule"] == "unsafe_command"
    assert findings[0]["severity"] == "warning"
    text = "The command `rm -rf /` is dangerous.\nFor example, `npm run missing` is illustrative.\n> Run `rm -rf /`.\nDo not run `rm -rf /`."
    assert not validate_instructions(text, repo, {})


def test_deterministic_findings_and_generated_output(repo):
    profile = analyze(str(repo))
    text = "Run `npm run missing` (working directory: `frontend`).\nInspect `backend/no.py`."
    first = validate_instructions(text, repo, profile)
    assert first == validate_instructions(text, repo, profile)
    assert all(set(item) == {"rule", "severity", "explanation", "instruction", "line", "evidence"} for item in first)
    assert not validate_instructions(generate_agents_md(profile), repo, profile)


def test_framework_legacy_profile_checks_real_config(repo):
    assert not validate_instructions("The project uses React.", repo, {})


def test_condition_specific_contradictions_and_examples(repo):
    text = "Always run tests before release.\nNever run tests before release."
    assert "contradictory_instruction" in rules(validate_instructions(text, repo, {}))
    text = "## Examples\nRun `rm -rf /`.\nRun `npm run missing`."
    assert not validate_instructions(text, repo, {})


def test_bare_npm_command_and_other_unsafe_flag(repo):
    assert "working_directory" in rules(validate_instructions("Run npm run build.", repo, analyze(str(repo))))
    assert "unsafe_command" in rules(validate_instructions("Run `rm -fr /`.", repo, {}))


def test_working_directory_for_other_known_commands(repo):
    (repo / "backend" / "pyproject.toml").write_text('[tool.taskipy.tasks]\ncheck = "echo checks"\n')
    profile = analyze(str(repo))
    assert "working_directory" in rules(validate_instructions("Run `echo checks`.", repo, profile))
    assert "working_directory" in rules(validate_instructions("Run `echo checks` (working directory: `.`).", repo, profile))
    assert not rules(validate_instructions("Run `echo checks` (working directory: `backend`).", repo, profile))
    assert not rules(validate_instructions("Run `npm run build` from `frontend`.", repo, profile))


def test_legacy_and_malformed_framework_configuration(repo):
    (repo / "frontend" / "package.json").write_text('{"dependencies": "invalid"}')
    findings = validate_instructions("The project uses React.", repo, {})
    assert findings[0]["rule"] == "framework_unverified"


def test_independent_cli_and_optional_generation(repo, tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    project = Path(__file__).resolve().parents[1]
    instruction = tmp_path / "instructions.md"
    instruction.write_text("Inspect `missing.py`.\n")
    output = subprocess.check_output([sys.executable, str(project / "src" / "validate_instructions.py"), str(instruction), "--repo", str(repo)], text=True)
    assert json.loads(output)[0]["rule"] == "path_missing"
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "repo_profile.json").write_text(json.dumps(analyze(str(repo))))
    command = [sys.executable, str(project / "src" / "generate_agents.py")]
    subprocess.check_output(command, cwd=tmp_path, text=True)
    generated = (outputs / "generated_AGENTS.md").read_text()
    output = subprocess.check_output(command + ["--validate", "--repo", str(repo)], cwd=tmp_path, text=True)
    assert "Validation findings:" in output
    assert (outputs / "generated_AGENTS.md").read_text() == generated


def test_verified_labels_and_inferred_evidence(repo):
    (repo / "README.md").write_text("pytest -q\n")
    profile = analyze(str(repo))
    text = "## Verified commands\n- `pytest -q` (working directory: `.`)"
    findings = validate_instructions(text, repo, profile)
    assert "command_unverified" in rules(findings)
    assert findings[0]["severity"] == "unverified"
    assert findings[0]["evidence"][0]["classification"] == "documented"


def test_symlinks_outside_do_not_verify_paths_or_packages(repo, tmp_path):
    outside = tmp_path.parent / (tmp_path.name + "_external")
    outside.mkdir()
    (outside / "package.json").write_text('{"scripts": {"hidden": "echo x"}}')
    (repo / "linked").symlink_to(outside, target_is_directory=True)
    findings = validate_instructions("Inspect `linked/package.json`.\nRun `npm run hidden` (working directory: `linked`).", repo, {})
    assert rules(findings) == {"path_outside", "working_directory"}


def test_recommendation_and_negation(repo):
    assert "unsafe_command" in rules(validate_instructions("Use `rm -rf /`.", repo, {}))
    assert not validate_instructions("Never use `rm -rf /`.", repo, {})
    assert not validate_instructions("```sh\nrm -rf /\n```", repo, {})


def test_named_directory_and_legacy_npm_location(repo):
    findings = validate_instructions("Inspect directory `missing`.\nRun `npm run build` (working directory: `backend`).", repo, {})
    assert rules(findings) == {"path_missing", "working_directory"}
    assert findings[1]["evidence"][0]["source"] == "frontend/package.json"


def test_npm_bare_command_with_dot_in_name(repo):
    (repo / "frontend" / "package.json").write_text('{"scripts": {"test.unit": "echo test"}}')
    findings = validate_instructions("Run npm run test.unit --prefix frontend.", repo, analyze(str(repo)))
    assert not findings


def test_missing_scripts_table_is_a_confirmed_error(repo):
    (repo / "frontend" / "package.json").write_text('{}')
    findings = validate_instructions("Run `npm run build` (working directory: `frontend`).", repo, {})
    assert findings[0]["rule"] == "npm_script_missing"
    assert findings[0]["severity"] == "error"


def test_framework_claim_checks_current_configuration(repo):
    profile = analyze(str(repo))
    (repo / "frontend" / "package.json").write_text('{"dependencies": {}}')
    findings = validate_instructions("The project uses React.", repo, profile)
    assert findings[0]["rule"] == "framework_conflict"
    assert findings[0]["severity"] == "warning"
