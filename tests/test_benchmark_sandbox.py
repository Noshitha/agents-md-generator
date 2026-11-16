import hashlib
import json
import os
from pathlib import Path

import pytest

from src.real_benchmark import ORIGINAL_COMMIT, ROOT, container_run, run_condition, snapshot


pytestmark = pytest.mark.skipif(os.environ.get("BENCHMARK_DOCKER_TESTS") != "1", reason="requires local Docker")


def test_offline_agent_tool_and_grader_protocol(tmp_path):
    task_dir = ROOT / "benchmark" / "pilot"
    task = json.loads((task_dir / "task.json").read_text())
    actions = []

    def adapter(messages, timeout):
        step = len(actions)
        if step == 0:
            action = {"tool": "read_file", "path": "src/analyze_repo.py"}
        elif step == 1:
            result = json.loads(messages[-1]["content"])["tool_result"]
            assert result["exit_code"] == 0 and "def analyze" in result["stdout"]
            content = result["stdout"].rstrip("\n")
            content = content.replace("return list(set(commands))", "return sorted(set(commands))").replace("commands[key] = list(set(commands[key]))", "commands[key] = sorted(set(commands[key]))")
            action = {"tool": "write_file", "path": "src/analyze_repo.py", "content": content}
        elif step == 2:
            assert json.loads(messages[-1]["content"])["tool_result"]["exit_code"] == 0
            action = {"tool": "list_directory", "path": "src"}
        elif step == 3:
            assert "analyze_repo.py" in json.loads(messages[-1]["content"])["tool_result"]["stdout"]
            action = {"tool": "run_command", "command": "python --version"}
        else:
            result = json.loads(messages[-1]["content"])["tool_result"]
            assert result["exit_code"] == 0 and "Python 3.11" in result["stdout"]
            action = {"tool": "finish", "summary": "protocol test"}
        actions.append(action)
        return {"message": {"content": json.dumps(action)}}

    output = tmp_path / "protocol"
    result = run_condition(ROOT, task_dir, task, "C", "test-adapter", "not-a-model", "python:3.11-slim-bookworm", output, 10, 60, test_adapter=adapter)
    assert result["run_kind"] == "protocol_test"
    assert result["functional_pass"] is True and result["success"] is False
    assert result["input_tokens"] is None and result["output_tokens"] is None
    assert result["patch_sha256"] == result["graded_patch_sha256"] == hashlib.sha256((output / "patch.diff").read_bytes()).hexdigest()
    assert result["tests"]["acceptance"]["exit_code"] == 0
    assert result["tests"]["regression"]["exit_code"] == 0
    assert len(json.loads((output / "trace.json").read_text())) == 5
    assert json.loads((output / "commands.json").read_text())[0]["exit_code"] == 0


def test_real_container_timeout_and_test_adapter_timeout(tmp_path):
    workspace = tmp_path / "workspace"
    snapshot(ROOT, ORIGINAL_COMMIT, workspace)
    result = container_run("python:3.11-slim-bookworm", workspace, ["-c", "import time; time.sleep(10)"], 1)
    assert result["timed_out"] and result["exit_code"] is None

    def timeout_adapter(messages, timeout):
        raise TimeoutError("controlled protocol test")

    task_dir = ROOT / "benchmark" / "pilot"
    task = json.loads((task_dir / "task.json").read_text())
    result = run_condition(ROOT, task_dir, task, "A", "test-adapter", "not-a-model", "python:3.11-slim-bookworm", tmp_path / "timeout", 2, 30, test_adapter=timeout_adapter)
    assert result["run_kind"] == "protocol_test"
    assert result["timed_out"] is True and result["finished"] is False
    assert result["functional_pass"] is False and result["success"] is False
    assert result["input_tokens"] is None and result["output_tokens"] is None


def test_completion_message_without_changes_is_not_resolution(tmp_path):
    task_dir = ROOT / "benchmark" / "pilot"
    task = json.loads((task_dir / "task.json").read_text())

    def adapter(messages, timeout):
        return {"message": {"content": json.dumps({"tool": "finish", "summary": "done"})}}

    result = run_condition(ROOT, task_dir, task, "B", "test-adapter", "not-a-model", "python:3.11-slim-bookworm", tmp_path / "finish", 2, 30, test_adapter=adapter)
    assert result["finished"] is True
    assert result["has_changes"] is False
    assert result["functional_pass"] is False and result["success"] is False
    assert result["tests"]["acceptance"]["exit_code"] != 0


def test_agent_attempt_to_modify_tests_is_rejected(tmp_path):
    task_dir = ROOT / "benchmark" / "pilot"
    task = json.loads((task_dir / "task.json").read_text())
    actions = []

    def adapter(messages, timeout):
        if not actions:
            action = {"tool": "write_file", "path": "tests/test_fake.py", "content": "assert True\n"}
        else:
            assert json.loads(messages[-1]["content"])["tool_result"]["stderr"] == "File is not approved for changes"
            action = {"tool": "finish", "summary": "done"}
        actions.append(action)
        return {"message": {"content": json.dumps(action)}}

    result = run_condition(ROOT, task_dir, task, "A", "test-adapter", "not-a-model", "python:3.11-slim-bookworm", tmp_path / "unauthorized", 3, 30, test_adapter=adapter)
    assert result["safety_violations"]
    assert result["has_changes"] is False
    assert result["tests"]["acceptance"]["exit_code"] != 0
    assert result["functional_pass"] is False and result["success"] is False
