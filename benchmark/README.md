# Real coding-agent benchmark (pilot preparation)

This is an early harness, not a completed benchmark. No model runs or resolution results are included. The only prepared task, `pilot-command-order`, uses this repository at commit `9032cf3982a7b930f70d2ad3b3d157901834145f`. It asks for deterministic command ordering. The separate acceptance and regression checks and `reference.patch` are not mounted into the agent container. The baseline fails acceptance and passes regression; the known fix passes both in the restricted Python container. These are fixture checks, not agent results.

Condition A uses the generic baseline from that historical commit. B loads the generator from the same pinned commit; it does not substitute the committed generated artifact. C and D use the current full generator and task selector. All four receive profiles from the same sanitized starting snapshot. `outputs/`, `eval/`, and files named `*AGENTS.md` are excluded to prevent instruction contamination; snapshots containing `.env` files are rejected. The actual starting tree therefore differs from the full Git archive by those documented exclusions.

To verify the pilot fixture with an already-installed `python:3.11-slim-bookworm` image:

```bash
python src/real_benchmark.py --check-fixture
```

The runner uses only a local Ollama-compatible server at `127.0.0.1:11434`, and never downloads a model or image. Once a suitable local coding model is already available, a pilot can be launched with an unused results directory:

```bash
python src/real_benchmark.py --model LOCAL_MODEL_NAME --results-dir /tmp/agents-pilot
```

Each condition receives a separate snapshot and the same budgets, tools, and prompt apart from instructions. The runner shuffles condition order, records the seed, and saves instructions, trace, command outcomes, actual patch, grading output, usage when returned, and outcome. It checks that the patch applies and that nonempty acceptance and regression suites pass; no shell command from the agent is executed outside the allowlist. Unknown commands are counted as unsupported, not called hallucinations. Missing usage and cost data remain null. Time to a functional pass is recorded; time to reviewed success remains null because review timing is not captured. A run that times out or does not finish is a failure. Results directories must not already exist.

Agent commands run in disposable containers with no network or Docker socket, a read-only root filesystem, a workspace-only writable host mount, dropped capabilities, a non-root user, and CPU, memory, process, file-size, and time limits. Grading uses separate containers with the workspace and test mounts read-only. Extra fixed commands may be explicitly added with `--allow-command`; a locally installed image can be selected with `--image`. Repeated `--task-dir` and `--source-repo` arguments support additional local frozen fixtures. Each fixture needs `task.json`, `reference.patch`, `acceptance/`, and `regression/` and must fail acceptance and pass regression before the reference patch, then pass both afterward. Grading currently requires Python unittest wrappers named `check_*.py` in an image that already has the task dependencies.

The requested 12 independently verified tasks across multiple repositories have not been prepared. No suitable local generative model or local model server was found during this work, so the agent/model protocol has not been exercised end to end. The pilot is not a basis for a resolution-rate comparison or a confidence interval. Hosted evaluation is not implemented or approved; an estimate and explicit approval would be needed before using a paid model.

Safety reporting is limited to blocked tool requests and a few obvious command patterns. The harness records `functional_pass`, but deliberately leaves `success` false and marks safety review as not performed. An independent reviewer must inspect each run and its patch before a separate report can count it as resolved. The review mechanism records the reviewer's assertion; it cannot verify the reviewer's identity or independence. It does not audit the resulting patch or subprocesses launched by an allowed test command. Candidate code runs in the grading process and could inspect the grader files during grading, even though the agent cannot access them during its task. These limitations require independent review and stronger grading isolation before treating outcomes as benchmark-grade safety or adversarially robust results. The writable workspace has no total disk quota, although individual file size and runtime are limited.

For a separate reviewed report, prepare a JSON array with one object per reviewed run. Each object must contain `task_id`, `attempt`, `condition`, `reviewer`, `decision` (`pass` or `fail`), and SHA-256 hashes of that run's exact `result.json` and `patch.diff` as `result_sha256` and `patch_sha256`. Then run:

```bash
python src/real_benchmark.py --review-results /tmp/agents-pilot --review-file /tmp/reviews.json --report-file /tmp/reviewed-report.json
```

The report file must not exist. The raw results remain unchanged; missing reviews and incomplete runs count as failures. A review only counts a run as resolved if its recorded patch, acceptance tests, regression tests, completion status, and observed tool safety checks also pass. Reviewers must inspect the patch and execution records for disqualifying security issues and must not assume that the tool-request checks cover all subprocess or code behavior.
