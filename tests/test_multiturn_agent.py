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
