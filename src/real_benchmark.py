import argparse
import hashlib
import http.client
import io
import json
import os
import random
import re
import resource
import shlex
import subprocess
import tarfile
import tempfile
import time
import uuid
from pathlib import Path

if __package__:
    from .analyze_repo import analyze
    from .generate_agents import generate_agents_md, select_task_instructions
else:
    from analyze_repo import analyze
    from generate_agents import generate_agents_md, select_task_instructions


ROOT = Path(__file__).resolve().parent.parent
ORIGINAL_COMMIT = "9032cf3982a7b930f70d2ad3b3d157901834145f"
IMAGE = "python:3.11-slim-bookworm"
LOCAL_MODEL_URL = "http://127.0.0.1:11434/api"
ALLOWED_COMMANDS = [
    ["python", "--version"],
    ["python", "-m", "unittest", "discover"],
    ["python", "-m", "unittest", "discover", "-s", "tests"],
]
SYSTEM = """You are a coding agent solving a software task in /workspace.
Only use the tools described below. Reply with one JSON object per turn:
{{"tool":"read_file"|"list_directory"|"write_file","path":"relative/path","content":"for write_file only"}}
{{"tool":"run_command","command":"command from the allowed list"}}
{{"tool":"finish","summary":"short summary"}}
Commands are executed in the isolated workspace. Do not access paths outside it.
Allowed commands: {allowed_commands}.
Task:\n{task}\n\nInstructions:\n{instructions}"""

# Runs inside the container, which can only write to the workspace and /tmp.
FILE_TOOL = r'''import json, pathlib, sys
arg = json.load(sys.stdin)
root = pathlib.Path('/workspace').resolve()
p = pathlib.Path(arg.get('path', ''))
if p.is_absolute() or '..' in p.parts or any(part == '.git' or part.lower() == 'agents.md' or part == '.env' or part.startswith('.env.') for part in p.parts):
    raise ValueError('disallowed path')
full = (root / p).resolve()
if not full.is_relative_to(root):
    raise ValueError('disallowed path')
if arg['tool'] == 'read_file':
    print(full.read_text(errors='replace')[:16000])
elif arg['tool'] == 'list_directory':
    print('\n'.join(sorted(item.name for item in full.iterdir())[:200]))
elif arg['tool'] == 'write_file':
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(arg.get('content', ''), encoding='utf-8')
    print('written')
'''


def git_output(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args])


def snapshot(repo, revision, destination):
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("A full pinned commit hash is required")
    archive = git_output(repo, "archive", "--format=tar", revision)
    destination.mkdir()
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for member in tar:
            path = Path(member.name)
            if path.is_absolute() or ".." in path.parts or not (member.isfile() or member.isdir()):
                raise ValueError(f"Unsafe archive entry: {member.name}")
            if path.parts[0] in {"outputs", "eval"} or any(part.lower().endswith("agents.md") for part in path.parts):
                continue
            if any(part == ".env" or part.startswith(".env.") for part in path.parts):
                raise ValueError(f"Environment file in snapshot: {member.name}")
            target = destination / path
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(member) as source, target.open("wb") as output:
                    output.write(source.read())
                target.chmod(member.mode & 0o777)



def snapshot_hash(root):
    digest = hashlib.sha256()
    for path in sorted(path for path in root.rglob("*") if path.is_file()):
        name = path.relative_to(root).as_posix().encode()
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(hashlib.sha256(path.read_bytes()).digest())
        digest.update((path.stat().st_mode & 0o777).to_bytes(4, "big"))
    return digest.hexdigest()


def instructions(profile, task):
    baseline = git_output(ROOT, "show", f"{ORIGINAL_COMMIT}:outputs/baseline_AGENTS.md").decode()
    source = git_output(ROOT, "show", f"{ORIGINAL_COMMIT}:src/generate_agents.py").decode()
    namespace = {"__name__": "original_generator"}
    exec(compile(source, "historical_generator", "exec"), namespace)
    return {
        "A": baseline,
        "B": namespace["generate_agents_md"](profile),
        "C": generate_agents_md(profile),
        "D": select_task_instructions(profile, task),
    }


def docker_args(image, workspace, readonly=False, grading=None, executable="python"):
    args = ["docker", "run", "--rm", "--pull=never", "--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges", "--pids-limit=64", "--memory=512m", "--cpus=1", "--ulimit", "fsize=16777216:16777216", "--user", f"{os.getuid()}:{os.getgid()}", "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m", "--env", "HOME=/tmp", "--env", "PYTHONDONTWRITEBYTECODE=1", "--env", "PYTHONPATH=/workspace", "--workdir", "/workspace", "--mount", f"type=bind,src={workspace},dst=/workspace" + (",readonly" if readonly else "")]
    if grading is not None:
        args.extend(["--mount", f"type=bind,src={grading},dst=/grader,readonly"])
    return args + ["--entrypoint", executable, image]


def container_run(image, workspace, args, timeout, input_text=None, readonly=False, grading=None, executable="python"):
    name = "agents-benchmark-" + uuid.uuid4().hex
    command = docker_args(image, workspace, readonly, grading, executable)
    command[2:2] = ["--name", name]
    if input_text is not None:
        command.insert(2, "--interactive")
    command += args

    def limit_output():
        resource.setrlimit(resource.RLIMIT_FSIZE, (1000000, 1000000))

    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        timed_out = False
        exit_code = None
        try:
            result = subprocess.run(command, input=input_text, text=True, stdout=stdout, stderr=stderr, timeout=timeout, preexec_fn=limit_output)
            exit_code = result.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            try:
                subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                pass
        stdout.seek(0, os.SEEK_END)
        stdout_truncated = stdout.tell() > 50000
        stderr.seek(0, os.SEEK_END)
        stderr_truncated = stderr.tell() > 50000
        stdout.seek(0)
        stderr.seek(0)
        return {"exit_code": exit_code, "stdout": stdout.read(50000).decode(errors="replace"), "stderr": stderr.read(50000).decode(errors="replace"), "stdout_truncated": stdout_truncated, "stderr_truncated": stderr_truncated, "timed_out": timed_out}


def grade(image, workspace, task_dir, timeout):
    results = {}
    for name in ("acceptance", "regression"):
        results[name] = container_run(image, workspace, ["-m", "unittest", "discover", "-s", "/grader", "-p", "check_*.py", "-v"], timeout, readonly=True, grading=task_dir / name)
        match = re.search(r"Ran (\d+) tests? in", results[name]["stderr"])
        results[name]["tests_run"] = int(match.group(1)) if match else None
    return results


def check_fixture(image, source_repo, task_dir):
    task = json.loads((task_dir / "task.json").read_text())
    with tempfile.TemporaryDirectory(prefix="agent-benchmark-") as folder:
        workspace = Path(folder) / "workspace"
        snapshot(source_repo, task["revision"], workspace)
        baseline = grade(image, workspace, task_dir, 30)
        patch = (task_dir / "reference.patch").read_bytes()
        subprocess.run(["git", "apply", "--check", "--unidiff-zero", "-p2", "-"], cwd=workspace, input=patch, check=True, capture_output=True)
        subprocess.run(["git", "apply", "--unidiff-zero", "-p2", "-"], cwd=workspace, input=patch, check=True, capture_output=True)
        corrected = grade(image, workspace, task_dir, 30)
        report = {"baseline": baseline, "known_fix": corrected}
        ok = baseline["acceptance"]["exit_code"] not in (0, None) and baseline["acceptance"]["tests_run"] and baseline["regression"]["exit_code"] == 0 and baseline["regression"]["tests_run"] and all(item["exit_code"] == 0 and item["tests_run"] for item in corrected.values())
        return ok, report


def local_models(timeout=3):
    connection = http.client.HTTPConnection("127.0.0.1", 11434, timeout=timeout)
    try:
        connection.request("GET", "/api/tags")
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError(f"Local model server returned HTTP {response.status}")
        return json.load(response).get("models", [])
    finally:
        connection.close()


def call_model(model, messages, timeout):
    data = json.dumps({"model": model, "messages": messages, "stream": False, "format": "json", "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 1024}}).encode()
    connection = http.client.HTTPConnection("127.0.0.1", 11434, timeout=timeout)
    deadline = time.monotonic() + timeout
    try:
        connection.request("POST", "/api/chat", body=data, headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError(f"Local model server returned HTTP {response.status}")
        data = bytearray()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Local model response timed out")
            if connection.sock is not None:
                connection.sock.settimeout(remaining)
            chunk = response.read1(65536)
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > 4000000:
                raise ValueError("Local model response exceeds size limit")
        return json.loads(data)
    finally:
        connection.close()


def execute_tool(image, workspace, action, timeout, allowed_commands=ALLOWED_COMMANDS):
    name = action.get("tool")
    if name in ("read_file", "write_file", "list_directory"):
        path = action.get("path", "")
        parts = Path(path).parts if isinstance(path, str) else ()
        if not isinstance(path, str) or Path(path).is_absolute() or ".." in parts or any(part == ".git" or part.lower() == "agents.md" or part == ".env" or part.startswith(".env.") for part in parts):
            return {"exit_code": None, "stdout": "", "stderr": "Disallowed path", "timed_out": False}, False, True
        if name == "write_file" and (not isinstance(action.get("content"), str) or len(action["content"]) > 100000):
            return {"exit_code": None, "stdout": "", "stderr": "Invalid file content", "timed_out": False}, False, True
        result = container_run(image, workspace, ["-c", FILE_TOOL], timeout, json.dumps(action))
        violation = "disallowed path" in result["stderr"].lower()
        return result, False, violation
    if name == "run_command":
        command = action.get("command", "")
        try:
            parts = shlex.split(command) if isinstance(command, str) else []
        except ValueError:
            parts = []
        if parts not in allowed_commands:
            unsafe = bool(re.search(r"(?:\.\./|\brm\b|\bsudo\b|\bcurl\b|\bwget\b|[;&|`])", command)) if isinstance(command, str) else False
            return {"exit_code": None, "stdout": "", "stderr": "Command not permitted", "timed_out": False}, True, unsafe
        return container_run(image, workspace, parts[1:], timeout, executable=parts[0]), False, False
    return {"exit_code": None, "stdout": "", "stderr": "Unknown tool", "timed_out": False}, True, False


def patch_for(base, workspace):
    result = subprocess.run(["git", "diff", "--no-index", "--binary", "--", "base", "workspace"], cwd=base.parent, capture_output=True)
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr.decode(errors="replace"))
    patch = result.stdout
    if not patch:
        return patch, False
    check = subprocess.run(["git", "apply", "--check", "-p2", "-"], cwd=base, input=patch, capture_output=True)
    return patch, check.returncode == 0


def run_condition(source_repo, task_dir, task, condition, model, model_digest, image, output_dir, steps, seconds, allowed_commands=ALLOWED_COMMANDS):
    import shutil

    started = time.monotonic()
    output_dir.mkdir(parents=True)
    result = {"task_id": task["id"], "repository": task["repository"], "revision": task["revision"], "original_generator_commit": ORIGINAL_COMMIT, "condition": condition, "model": model, "model_digest": model_digest, "image": image, "max_steps": steps, "time_limit_seconds": seconds, "allowed_commands": allowed_commands, "context_tokens": 8192, "max_output_tokens_per_turn": 1024, "temperature": 0, "input_tokens": None, "output_tokens": None, "cost_usd": None, "tool_calls": 0, "unsupported_commands": 0, "safety_violations": [], "safety_scope": "Blocked tool requests only; repository changes and child processes require independent review", "finished": False, "timed_out": False, "success": False}
    trace = []
    commands = []
    token_usage = []
    with tempfile.TemporaryDirectory(prefix="agent-benchmark-") as folder:
        parent = Path(folder)
        base = parent / "base"
        workspace = parent / "workspace"
        snapshot(source_repo, task["revision"], base)
        result["snapshot_sha256"] = snapshot_hash(base)
        shutil.copytree(base, workspace)
        profile = analyze(str(base))
        profile["repo_name"] = task["repository"]
        variants = instructions(profile, task["description"])
        prompt = variants[condition]
        (output_dir / "instructions.md").write_text(prompt)
        result["instruction_sha256"] = hashlib.sha256(prompt.encode()).hexdigest()
        result["instruction_bytes"] = len(prompt.encode())
        result["instruction_words"] = len(prompt.split())
        result["instruction_bullet_count"] = sum(1 for line in prompt.splitlines() if line.startswith("- "))
        result["applicable_instruction_count"] = None
        messages = [{"role": "system", "content": SYSTEM.format(task=task["description"], instructions=prompt, allowed_commands="; ".join(shlex.join(command) for command in allowed_commands))}]
        for index in range(steps):
            remaining = seconds - (time.monotonic() - started)
            if remaining <= 0:
                result["timed_out"] = True
                break
            try:
                current = next((item for item in local_models(timeout=min(3, remaining)) if item.get("name") == model), None)
                if not current or current.get("digest") != model_digest:
                    raise ValueError("Local model digest changed during the run")
                remaining = seconds - (time.monotonic() - started)
                if remaining <= 0:
                    raise TimeoutError("Agent time budget exhausted")
                response = call_model(model, messages, remaining)
                content = response["message"]["content"]
                token_usage.append((response.get("prompt_eval_count"), response.get("eval_count")))
                action = json.loads(content)
                if not isinstance(action, dict):
                    raise ValueError("Model response is not an object")
            except Exception as exc:
                result["agent_error"] = f"{type(exc).__name__}: {exc}"
                result["timed_out"] = isinstance(exc, TimeoutError) or time.monotonic() - started >= seconds
                break
            messages.append({"role": "assistant", "content": content})
            trace.append({"step": index + 1, "action": action})
            if action.get("tool") == "finish":
                result["finished"] = True
                break
            result["tool_calls"] += 1
            remaining = seconds - (time.monotonic() - started)
            if remaining <= 0:
                result["timed_out"] = True
                break
            tool_result, unsupported, unsafe = execute_tool(image, workspace, action, min(30, remaining), allowed_commands)
            result["unsupported_commands"] += int(unsupported and action.get("tool") == "run_command")
            if unsafe:
                result["safety_violations"].append({"step": index + 1, "action": action})
            trace[-1]["result"] = tool_result
            if action.get("tool") == "run_command":
                commands.append({"step": index + 1, "command": action.get("command"), "unsupported": unsupported, **tool_result})
            messages.append({"role": "user", "content": json.dumps({"tool_result": tool_result})})
            if tool_result["timed_out"] and time.monotonic() - started >= seconds:
                result["timed_out"] = True
                break
        result["agent_elapsed_seconds"] = round(time.monotonic() - started, 3)
        patch, applies = patch_for(base, workspace)
        (output_dir / "patch.diff").write_bytes(patch)
        result["has_changes"] = bool(patch)
        result["patch_applies"] = applies
        result["tests"] = grade(image, workspace, task_dir, 30)
        result["functional_pass"] = bool(result["finished"] and not result["timed_out"] and patch and applies and not result["safety_violations"] and all(test["exit_code"] == 0 and not test["timed_out"] and test["tests_run"] for test in result["tests"].values()))
        result["safety_review"] = "not_performed"
        result["success"] = False
    if token_usage and all(isinstance(a, int) and isinstance(b, int) for a, b in token_usage):
        result["input_tokens"] = sum(a for a, _ in token_usage)
        result["output_tokens"] = sum(b for _, b in token_usage)
    result["total_elapsed_seconds"] = round(time.monotonic() - started, 3)
    result["time_to_functional_pass_seconds"] = result["total_elapsed_seconds"] if result.get("functional_pass") else None
    result["time_to_success_seconds"] = None
    (output_dir / "trace.json").write_text(json.dumps(trace, indent=2))
    (output_dir / "commands.json").write_text(json.dumps(commands, indent=2))
    (output_dir / "result.json").write_text(json.dumps(result, indent=2))
    return result


def summarize(results):
    summary = {}
    for condition in ("A", "B", "C", "D"):
        runs = [item for item in results if item["condition"] == condition]
        resolved = sum(item["success"] for item in runs)
        tool_counts = [item["tool_calls"] for item in runs]
        unsupported = [item["unsupported_commands"] for item in runs]
        safety = [item["safety_violations"] for item in runs]
        input_tokens = [item["input_tokens"] for item in runs]
        output_tokens = [item["output_tokens"] for item in runs]
        costs = [item["cost_usd"] for item in runs]
        summary[condition] = {
            "runs": len(runs), "resolved": resolved,
            "resolution_rate": resolved / len(runs) if runs else None,
            "unsupported_commands": sum(unsupported) if runs and all(value is not None for value in unsupported) else None,
            "safety_violations": sum(len(value) for value in safety) if runs and all(value is not None for value in safety) else None,
            "tool_calls_per_resolved_task": sum(tool_counts) / resolved if resolved and all(value is not None for value in tool_counts) else None,
            "input_tokens": sum(input_tokens) if runs and all(value is not None for value in input_tokens) else None,
            "output_tokens": sum(output_tokens) if runs and all(value is not None for value in output_tokens) else None,
            "cost_per_resolved_task": sum(costs) / resolved if resolved and all(value is not None for value in costs) else None,
            "elapsed_seconds": sum(item["total_elapsed_seconds"] for item in runs),
            "successful_run_seconds": [item["time_to_success_seconds"] for item in runs if item["success"]] if all(item["time_to_success_seconds"] is not None for item in runs if item["success"]) else None,
            "completed_within_budget": sum(bool(item["finished"] and not item["timed_out"]) for item in runs),
        }
    comparisons = {}
    for first, second in (("A", "B"), ("B", "C"), ("B", "D"), ("C", "D")):
        a, b = summary[first]["resolution_rate"], summary[second]["resolution_rate"]
        ca = summary[first]["unsupported_commands"]
        cb = summary[second]["unsupported_commands"]
        na = summary[first]["runs"]
        nb = summary[second]["runs"]
        comparisons[f"{first}_vs_{second}"] = {"percentage_points": (b - a) * 100 if a is not None and b is not None else None, "relative_change": (b - a) / a if a not in (None, 0) and b is not None else None, "unsupported_per_run_difference": cb / nb - ca / na if ca is not None and cb is not None and na and nb else None}
    tasks = {}
    for item in results:
        task = tasks.setdefault(item["task_id"], {})
        condition = task.setdefault(item["condition"], {"runs": 0, "resolved": 0})
        condition["runs"] += 1
        condition["resolved"] += int(item["success"])
    return {"conditions": summary, "comparisons": comparisons, "tasks": tasks, "confidence_intervals": None, "note": "Safety review is not implemented: functional passes remain unresolved. No significance claim or confidence interval is reported."}



def review_results(results_dir, reviews):
    indexed = {}
    for review in reviews:
        key = (review["task_id"], review["attempt"], review["condition"])
        if key in indexed or review.get("decision") not in ("pass", "fail") or not isinstance(review.get("reviewer"), str) or not review["reviewer"].strip():
            raise ValueError("Reviews require a unique run, pass/fail decision, and reviewer")
        indexed[key] = review
    results = []
    review_log = []
    for result_path in sorted(results_dir.rglob("result.json")):
        raw = result_path.read_bytes()
        result = json.loads(raw)
        key = (result["task_id"], result["attempt"], result["condition"])
        review = indexed.pop(key, None)
        result["success"] = False
        if review:
            patch_path = result_path.parent / "patch.diff"
            if not patch_path.is_file() or review.get("result_sha256") != hashlib.sha256(raw).hexdigest() or review.get("patch_sha256") != hashlib.sha256(patch_path.read_bytes()).hexdigest():
                raise ValueError(f"Review hashes do not match run {key}")
            tests = result.get("tests", {})
            functional = bool(result.get("functional_pass") and result.get("finished") and not result.get("timed_out") and result.get("has_changes") and result.get("patch_applies") and result.get("safety_violations") == [] and set(tests) == {"acceptance", "regression"} and all(item.get("exit_code") == 0 and item.get("tests_run") and not item.get("timed_out") for item in tests.values()))
            result["success"] = functional and review["decision"] == "pass"
            review_log.append({"task_id": key[0], "attempt": key[1], "condition": key[2], "reviewer": review["reviewer"], "decision": review["decision"]})
        results.append(result)
    if indexed:
        raise ValueError("A review does not match a recorded run")
    report = summarize(results)
    report["note"] = "Unreviewed or incomplete runs count as failures; no significance claim or confidence interval is reported."
    report["safety_reviews"] = review_log
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-fixture", action="store_true")
    parser.add_argument("--review-results", type=Path)
    parser.add_argument("--review-file", type=Path)
    parser.add_argument("--report-file", type=Path)
    parser.add_argument("--source-repo", type=Path, action="append")
    parser.add_argument("--task-dir", type=Path, action="append")
    parser.add_argument("--image", default=IMAGE)
    parser.add_argument("--allow-command", action="append", default=[])
    parser.add_argument("--model")
    parser.add_argument("--results-dir", type=Path)
    parser.add_argument("--attempts", type=int, default=1)
    parser.add_argument("--steps", type=int, default=25)
    parser.add_argument("--seconds", type=int, default=300)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.review_results is not None:
        if args.review_file is None or args.report_file is None:
            parser.error("--review-results requires --review-file and a new --report-file")
        report = review_results(args.review_results, json.loads(args.review_file.read_text()))
        try:
            with args.report_file.open("x", encoding="utf-8") as f:
                json.dump(report, f, indent=2)
        except FileExistsError:
            parser.error("--report-file must not already exist")
        print(json.dumps(report, indent=2))
        return 0
    if args.review_file is not None or args.report_file is not None:
        parser.error("--review-file and --report-file require --review-results")
    if not args.check_fixture and (not args.model or args.results_dir is None):
        parser.error("A local --model and a new --results-dir are required")
    if not 1 <= args.attempts <= 10 or not 1 <= args.steps <= 100 or not 1 <= args.seconds <= 3600:
        parser.error("Invalid attempt, step, or time budget")
    task_dirs = [path.resolve() for path in (args.task_dir or [ROOT / "benchmark" / "pilot"])]
    sources = [path.resolve() for path in (args.source_repo or [ROOT])]
    if len(sources) == 1:
        sources *= len(task_dirs)
    if len(sources) != len(task_dirs):
        parser.error("Provide one source repository for all tasks or one per task")
    tasks = [json.loads((path / "task.json").read_text()) for path in task_dirs]
    ids = [task["id"] for task in tasks]
    if len(set(ids)) != len(ids) or any(not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", value) for value in ids):
        parser.error("Task IDs must be unique lowercase identifiers")
    allowed_commands = list(ALLOWED_COMMANDS)
    for command in args.allow_command:
        try:
            parts = shlex.split(command)
        except ValueError:
            parser.error("Invalid allowed command")
        if not parts or not re.fullmatch(r"[A-Za-z0-9_.+-]+", parts[0]) or parts[0] in {"sh", "bash", "zsh", "dash", "sudo", "docker", "curl", "wget", "rm", "dd", "mount", "nsenter", "unshare"} or (re.fullmatch(r"python[0-9.]*", parts[0]) and "-c" in parts):
            parser.error("Allowed commands must not launch a shell, network client, or Docker")
        if parts not in allowed_commands:
            allowed_commands.append(parts)
    if not args.check_fixture:
        try:
            models = local_models()
        except (OSError, ValueError, http.client.HTTPException) as exc:
            parser.error(f"No local model server is available at {LOCAL_MODEL_URL}: {exc}")
        model = next((item for item in models if item.get("name") == args.model), None)
        if not model or not model.get("digest"):
            parser.error("The requested local model and its digest are not available; no model was downloaded")
    try:
        image = subprocess.check_output(["docker", "image", "inspect", args.image, "--format", "{{.Id}}"], text=True, stderr=subprocess.PIPE).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        parser.error(f"The already-installed Docker image is unavailable: {exc}")
    fixture_reports = {}
    for source, task_dir, task in zip(sources, task_dirs, tasks):
        ok, report = check_fixture(image, source, task_dir)
        fixture_reports[task["id"]] = report
        if not ok and not args.check_fixture:
            parser.error(f"Fixture verification failed for {task['id']}; no benchmark was run")
    if args.check_fixture:
        print(json.dumps(fixture_reports, indent=2))
        return 0 if all(report["baseline"]["acceptance"]["exit_code"] not in (0, None) and report["baseline"]["acceptance"]["tests_run"] and report["baseline"]["regression"]["exit_code"] == 0 and report["baseline"]["regression"]["tests_run"] and all(item["exit_code"] == 0 and item["tests_run"] for item in report["known_fix"].values()) for report in fixture_reports.values()) else 1
    args.results_dir.mkdir(parents=True, exist_ok=False)
    results = []
    rng = random.Random(args.seed)
    order = []
    for attempt in range(1, args.attempts + 1):
        entries = list(zip(sources, task_dirs, tasks))
        rng.shuffle(entries)
        for source, task_dir, task in entries:
            conditions = ["A", "B", "C", "D"]
            rng.shuffle(conditions)
            for condition in conditions:
                order.append({"task_id": task["id"], "attempt": attempt, "condition": condition})
                output = args.results_dir / task["id"] / f"attempt_{attempt}" / condition
                run_started = time.monotonic()
                try:
                    result = run_condition(source, task_dir, task, condition, args.model, model["digest"], image, output, args.steps, args.seconds, allowed_commands)
                except Exception as exc:
                    output.mkdir(parents=True, exist_ok=True)
                    result = {"task_id": task["id"], "repository": task["repository"], "revision": task["revision"], "original_generator_commit": ORIGINAL_COMMIT, "condition": condition, "model": args.model, "model_digest": model["digest"], "image": image, "incomplete": True, "agent_error": f"{type(exc).__name__}: {exc}", "success": False, "finished": None, "timed_out": None, "tool_calls": None, "unsupported_commands": None, "safety_violations": None, "input_tokens": None, "output_tokens": None, "cost_usd": None, "time_to_success_seconds": None, "total_elapsed_seconds": round(time.monotonic() - run_started, 3)}
                result["attempt"] = attempt
                (output / "result.json").write_text(json.dumps(result, indent=2))
                results.append(result)
    report = summarize(results)
    report["order"] = order
    report["order_seed"] = args.seed
    report["task_revisions"] = {task["id"]: task["revision"] for task in tasks}
    (args.results_dir / "summary.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
