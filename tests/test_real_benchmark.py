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
    assert SYSTEM.format(task="task", instructions=variants["A"], allowed_commands="python --version")


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
    args = docker_args("image-id", tmp_path, readonly=True, grading=tmp_path)
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
        "task_id": "task", "attempt": 1, "condition": "A", "functional_pass": True,
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
