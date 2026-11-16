import hashlib
from pathlib import Path

import pytest

from src.analyze_repo import analyze
from src.real_benchmark import ORIGINAL_COMMIT, ROOT, SYSTEM, docker_args, execute_tool, instructions, patch_for, snapshot


def test_snapshot_and_four_instruction_conditions(tmp_path):
    workspace = tmp_path / "workspace"
    snapshot(ROOT, ORIGINAL_COMMIT, workspace)
    assert (workspace / "src" / "analyze_repo.py").is_file()
    assert not (workspace / "outputs").exists()
    assert not (workspace / "eval").exists()
    assert not list(workspace.rglob("*AGENTS.md"))
    profile = analyze(str(workspace))
    variants = instructions(profile, "Fix backend logging")
    assert set(variants) == {"A", "B", "C", "D"}
    assert "use only these commands" in variants["B"]
    assert "Configuration confirms definitions" in variants["C"]
    assert hashlib.sha256(variants["B"].encode()).hexdigest() != hashlib.sha256(variants["C"].encode()).hexdigest()
    assert SYSTEM.format(task="task", instructions=variants["A"], allowed_commands="python --version", allowed_files="src/analyze_repo.py")


def test_snapshot_rejects_unpinned_revisions(tmp_path):
    with pytest.raises(ValueError):
        snapshot(ROOT, "HEAD", tmp_path / "workspace")


def test_disallowed_tools_and_paths_do_not_execute(tmp_path):
    result, unsupported, unsafe = execute_tool("unused", tmp_path, {"tool": "write_file", "path": "../outside", "content": "x"}, 1)
    assert unsafe and not unsupported and result["exit_code"] is None
    result, unsupported, unsafe = execute_tool("unused", tmp_path, {"tool": "run_command", "command": "rm -rf /"}, 1)
    assert unsupported and unsafe and result["exit_code"] is None
    result, unsupported, unsafe = execute_tool("unused", tmp_path, {"tool": "run_command", "command": "unknown-tool"}, 1)
    assert unsupported and not unsafe


def test_patch_requires_actual_applicable_changes(tmp_path):
    base = tmp_path / "base"
    workspace = tmp_path / "workspace"
    base.mkdir()
    workspace.mkdir()
    (base / "file.py").write_text("old\n")
    (workspace / "file.py").write_text("old\n")
    assert patch_for(base, workspace) == (b"", False)
    (workspace / "file.py").write_text("new\n")
    patch, applies = patch_for(base, workspace)
    assert applies and b"+new" in patch


def test_container_restrictions(tmp_path):
    args = docker_args("image-id", tmp_path, readonly=True)
    assert "--network=none" in args
    assert "--read-only" in args
    assert "--cap-drop=ALL" in args
    assert "--security-opt=no-new-privileges" in args
    assert "--pull=never" in args
    assert all("docker.sock" not in arg for arg in args)


def test_no_benchmark_rates_are_fabricated_without_runs():
    from src.real_benchmark import summarize

    report = summarize([])
    assert all(item["runs"] == 0 and item["resolution_rate"] is None for item in report["conditions"].values())
    assert all(item["percentage_points"] is None for item in report["comparisons"].values())
    assert report["confidence_intervals"] is None


def test_sanitized_snapshot_hash_is_stable(tmp_path):
    from src.real_benchmark import snapshot_hash

    first = tmp_path / "first"
    second = tmp_path / "second"
    snapshot(ROOT, ORIGINAL_COMMIT, first)
    snapshot(ROOT, ORIGINAL_COMMIT, second)
    assert snapshot_hash(first) == snapshot_hash(second)
    (second / "README.md").write_text("changed")
    assert snapshot_hash(first) != snapshot_hash(second)


def test_independent_safety_review_is_hash_bound(tmp_path):
    import json

    from src.real_benchmark import review_results

    run = tmp_path / "task" / "attempt_1" / "A"
    run.mkdir(parents=True)
    patch = b"test-only patch"
    (run / "patch.diff").write_bytes(patch)
    result = {
        "task_id": "task", "attempt": 1, "condition": "A", "run_kind": "model", "patch_sha256": hashlib.sha256(patch).hexdigest(), "graded_patch_sha256": hashlib.sha256(patch).hexdigest(), "functional_pass": True,
        "finished": True, "timed_out": False, "has_changes": True, "patch_applies": True,
        "safety_violations": [], "tests": {"acceptance": {"exit_code": 0, "tests_run": 1}, "regression": {"exit_code": 0, "tests_run": 1}},
        "success": False, "tool_calls": 2, "unsupported_commands": 0, "input_tokens": None,
        "output_tokens": None, "cost_usd": None, "time_to_success_seconds": None, "total_elapsed_seconds": 1.0,
    }
    result_path = run / "result.json"
    result_path.write_text(json.dumps(result))
    review = {"task_id": "task", "attempt": 1, "condition": "A", "reviewer": "independent reviewer", "decision": "pass", "result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(), "patch_sha256": hashlib.sha256(patch).hexdigest()}
    assert review_results(tmp_path, [])["conditions"]["A"]["resolved"] == 0
    assert review_results(tmp_path, [review])["conditions"]["A"]["resolved"] == 1
    (run / "patch.diff").write_bytes(b"changed")
    with pytest.raises(ValueError):
        review_results(tmp_path, [review])


def test_only_allowed_source_changes_can_be_graded(tmp_path):
    import shutil

    from src.real_benchmark import prepare_grading

    base = tmp_path / "base"
    workspace = tmp_path / "workspace"
    snapshot(ROOT, ORIGINAL_COMMIT, base)
    shutil.copytree(base, workspace)
    source = workspace / "src" / "analyze_repo.py"
    source.write_text(source.read_text() + "\n")
    patch, applies, changes = prepare_grading(base, workspace, tmp_path / "graded", ["src/analyze_repo.py"])
    assert applies and changes == ["src/analyze_repo.py"] and patch
    (workspace / "tests").mkdir()
    (workspace / "tests" / "test_fake.py").write_text("assert True\n")
    with pytest.raises(ValueError, match="Unauthorized changes"):
        prepare_grading(base, workspace, tmp_path / "rejected", ["src/analyze_repo.py"])


def test_symlinks_and_unapproved_configuration_are_rejected(tmp_path):
    import shutil

    from src.real_benchmark import prepare_grading

    base = tmp_path / "base"
    workspace = tmp_path / "workspace"
    snapshot(ROOT, ORIGINAL_COMMIT, base)
    shutil.copytree(base, workspace)
    (workspace / "evil").symlink_to("/etc/passwd")
    with pytest.raises(ValueError, match="symlink"):
        prepare_grading(base, workspace, tmp_path / "rejected", ["src/analyze_repo.py"])
    (workspace / "evil").unlink()
    (workspace / "README.md").write_text("tampered")
    with pytest.raises(ValueError, match="Unauthorized changes"):
        prepare_grading(base, workspace, tmp_path / "rejected", ["src/analyze_repo.py"])


def test_protocol_test_cannot_be_credited_as_model_run(tmp_path):
    import json

    from src.real_benchmark import review_results

    run = tmp_path / "task" / "attempt_1" / "A"
    run.mkdir(parents=True)
    patch = b"protocol test patch"
    (run / "patch.diff").write_bytes(patch)
    digest = hashlib.sha256(patch).hexdigest()
    result = {"task_id": "task", "attempt": 1, "condition": "A", "run_kind": "protocol_test", "patch_sha256": digest, "graded_patch_sha256": digest, "functional_pass": True, "finished": True, "timed_out": False, "has_changes": True, "patch_applies": True, "safety_violations": [], "tests": {"acceptance": {"exit_code": 0, "tests_run": 1}, "regression": {"exit_code": 0, "tests_run": 1}}, "success": False, "tool_calls": 1, "unsupported_commands": 0, "input_tokens": None, "output_tokens": None, "cost_usd": None, "time_to_success_seconds": None, "total_elapsed_seconds": 1.0}
    result_path = run / "result.json"
    result_path.write_text(json.dumps(result))
    review = {"task_id": "task", "attempt": 1, "condition": "A", "reviewer": "test reviewer", "decision": "pass", "result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(), "patch_sha256": digest}
    assert review_results(tmp_path, [review])["conditions"]["A"]["resolved"] == 0


def test_container_refuses_root_identity(tmp_path, monkeypatch):
    import os

    monkeypatch.setattr(os, "getuid", lambda: 0)
    with pytest.raises(ValueError, match="non-root"):
        docker_args("image-id", tmp_path)


def test_smoke_condition_validation_is_offline():
    import subprocess
    import sys

    result = subprocess.run([sys.executable, str(ROOT / "src" / "real_benchmark.py"), "--check-fixture", "--conditions", "A,A"], capture_output=True, text=True)
    assert result.returncode != 0
    assert "unique comma-separated subset" in result.stderr


def test_trusted_grader_still_checks_when_python_is_optimized():
    import subprocess
    import sys

    grader = ROOT / "benchmark" / "pilot" / "grader.py"
    code = "import runpy,sys; g=runpy.run_path(sys.argv[1]); g['acceptance'](lambda request, seed: {'commands': {}}, 'nonce')"
    result = subprocess.run([sys.executable, "-O", "-c", code, str(grader)], capture_output=True, text=True)
    assert result.returncode != 0
    assert "Command lists differ" in result.stderr


def test_remote_docker_host_is_rejected(monkeypatch):
    from src.real_benchmark import require_local_docker

    monkeypatch.setenv("DOCKER_HOST", "tcp://example.invalid:2375")
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    with pytest.raises(ValueError, match="local Unix socket"):
        require_local_docker()
