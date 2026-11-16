import pytest

from src.multiturn_agent import AgentTrace, MultiTurnAgent


@pytest.fixture
def agent(tmp_path):
    return MultiTurnAgent(client=None, model="test", task="test", repo_root=tmp_path)


def test_valid_paths_and_simulated_write(agent, tmp_path):
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "file.txt").write_text("original")
    trace = AgentTrace()

    assert agent._execute("read_file", {"path": "nested/file.txt"}, trace) == "original"
    assert "file.txt" in agent._execute("list_directory", {"path": "nested"}, trace)
    assert agent._execute("write_file", {"path": "nested/file.txt", "content": "changed"}, trace) == "Written: nested/file.txt (7 chars)"
    assert trace.written_files == {"nested/file.txt": "changed"}
    assert (tmp_path / "nested" / "file.txt").read_text() == "original"
    assert agent._execute("write_file", {"path": "new/file.txt", "content": "new"}, trace).startswith("Written:")
    assert not (tmp_path / "new").exists()


@pytest.mark.parametrize("tool", ["read_file", "write_file", "list_directory"])
@pytest.mark.parametrize("path", ["../outside", "nested/../file.txt", "/tmp/outside"])
def test_invalid_paths(agent, tool, path):
    trace = AgentTrace()
    assert agent._execute(tool, {"path": path, "content": "changed"}, trace).startswith("Error:")
    assert trace.written_files == {}


@pytest.mark.parametrize("tool", ["read_file", "write_file", "list_directory"])
def test_escaping_symlink(agent, tmp_path, tool):
    outside = tmp_path.parent / (tmp_path.name + "_outside")
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    (tmp_path / "link").symlink_to(outside, target_is_directory=True)
    trace = AgentTrace()

    assert agent._execute(tool, {"path": "link/secret.txt", "content": "changed"}, trace).startswith("Error:")
    assert trace.written_files == {}
    assert (outside / "secret.txt").read_text() == "secret"


def test_internal_symlink_and_missing_paths(agent, tmp_path):
    (tmp_path / "file.txt").write_text("content")
    (tmp_path / "link").symlink_to(tmp_path / "file.txt")
    trace = AgentTrace()

    assert agent._execute("read_file", {"path": "link"}, trace) == "content"
    assert agent._execute("read_file", {"path": "missing"}, trace) == "Error: file not found: missing"
    assert agent._execute("list_directory", {"path": "missing"}, trace) == "Error: directory not found: missing"


@pytest.mark.parametrize("tool", ["read_file", "write_file", "list_directory"])
def test_existing_outside_paths(agent, tmp_path, tool):
    outside = tmp_path.parent / (tmp_path.name + "_outside")
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    trace = AgentTrace()

    for path in (str(tmp_path / "file.txt"), f"../{outside.name}", f"../{outside.name}/secret.txt"):
        assert agent._execute(tool, {"path": path, "content": "changed"}, trace).startswith("Error:")
    assert trace.written_files == {}


def test_escaping_and_broken_symlinks(agent, tmp_path):
    outside = tmp_path.parent / (tmp_path.name + "_outside")
    outside.mkdir()
    (tmp_path / "external").symlink_to(outside, target_is_directory=True)
    (tmp_path / "broken").symlink_to(outside / "missing")
    trace = AgentTrace()

    assert agent._execute("list_directory", {"path": "external"}, trace).startswith("Error:")
    assert agent._execute("write_file", {"path": "external/new.txt", "content": "x"}, trace).startswith("Error:")
    assert agent._execute("read_file", {"path": "broken"}, trace).startswith("Error:")
    assert "external" in agent._execute("list_directory", {"path": "."}, trace)
    assert trace.written_files == {}


@pytest.mark.parametrize("command", [
    "pytest",
    "ruff check .",
    "docker compose up -d",
    'alembic revision --autogenerate -m "Add category"',
    "alembic upgrade head",
    "npm run generate-client",
])
def test_recognized_commands_are_simulated(agent, command):
    trace = AgentTrace()
    result = agent._execute("run_command", {"command": command}, trace)
    assert result.startswith("[simulated]")
    assert trace.commands_run == [command]
    assert trace.hallucinated_commands == []


@pytest.mark.parametrize("command", [
    "unknown-command",
    "npm run nonexistent",
    "npm run build --unknown",
    "docker compose nonexistent",
    "docker compose exec backend imaginary",
    "pytest --not-a-real-option",
    "echo hi && pytest",
    "alembic revision --autogenerate --bad-option",
])
def test_unsupported_commands_are_recorded(agent, command):
    trace = AgentTrace()
    result = agent._execute("run_command", {"command": command}, trace)
    assert result.startswith("Error:")
    assert trace.commands_run == [command]
    assert trace.hallucinated_commands == [command]
    assert trace.written_files == {}


def test_npm_scripts_use_target_package(agent, tmp_path):
    (tmp_path / "package.json").write_text('{"scripts": {"custom:check": "echo ok"}}')
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "package.json").write_text('{"scripts": {"build": "vite build"}}')
    trace = AgentTrace()

    for command in ("npm run custom:check", "cd frontend && npm run build", "npm run build --prefix frontend"):
        assert agent._execute("run_command", {"command": command}, trace).startswith("[simulated]")
    for command in ("npm run build", "cd frontend && npm run custom:check", "npm run build --prefix ../outside"):
        assert agent._execute("run_command", {"command": command}, trace).startswith("Error:")
    assert trace.hallucinated_commands == ["npm run build", "cd frontend && npm run custom:check", "npm run build --prefix ../outside"]


def test_simulated_migration_and_metrics(agent, monkeypatch):
    import importlib
    from pathlib import Path

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "src"))
    extract_metrics = importlib.import_module("run_task1_abc_multiturn_eval").extract_metrics
    trace = AgentTrace()
    for command in ('alembic revision --autogenerate -m "Add category"', "unknown-command"):
        agent._execute("run_command", {"command": command}, trace)
    metrics = extract_metrics(trace)

    assert "backend/alembic/versions/a1b2c3_add_category.py" in trace.written_files
    assert metrics["hallucinated_commands_count"] == 1
    assert metrics["hallucination_rate"] == 0.5
    assert metrics["commands_run"] == trace.commands_run
    assert metrics["hallucinated_commands"] == ["unknown-command"]
    assert metrics["migration_created"] is True


def test_simulator_existing_output_and_package_errors(agent, tmp_path):
    from src.multiturn_agent import simulate_command

    output, valid = simulate_command("pytest", tmp_path)
    assert valid is True
    assert "No command was executed" in output
    assert "23 passed" in output
    (tmp_path / "package.json").write_text("invalid json")
    assert simulate_command("npm run build", tmp_path)[1] is False
    assert simulate_command("npm run unknown", tmp_path)[1] is False


def test_rejected_migration_has_no_simulated_write(agent):
    trace = AgentTrace()
    command = 'alembic revision --autogenerate -m "Add category" --bad-option'
    assert agent._execute("run_command", {"command": command}, trace).startswith("Error:")
    assert trace.hallucinated_commands == [command]
    assert trace.written_files == {}


def test_unsupported_command_text_remains_a_metric_proxy(agent, monkeypatch):
    import importlib
    from pathlib import Path

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "src"))
    extract_metrics = importlib.import_module("run_task1_abc_multiturn_eval").extract_metrics
    trace = AgentTrace()
    agent._execute("run_command", {"command": "npm run generate-client --bad-option"}, trace)
    metrics = extract_metrics(trace)

    assert metrics["hallucinated_commands_count"] == 1
    assert metrics["client_regenerated"] is True
    assert metrics["plan_adherence_checklist"]["run_generate_client_command"] is True
