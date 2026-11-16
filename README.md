# agents-md-generator

Automatically generates repo-specific `AGENTS.md` files from static repository analysis, then measures whether those instructions actually change coding-agent behaviour — using a rigorous A/B evaluation pipeline with statistical testing.

> **Core question:** does a generated `AGENTS.md` improve plan adherence, safety, and task reliability — or is it noise?

---

## What It Does

```text
target repo (local clone)
  └─► analyze_repo.py                 — static analysis → repo_profile.json
    └─► generate_agents.py        — profile → generated AGENTS.md
      ├─► single-turn evals   — baseline vs generated across Tasks 1/2/3
      │     └─► statistical_test.py  — significance testing on plan adherence
      └─► multi-turn evals    — agent execution traces, metrics, summaries
        └─► optional exploration: infer_skills.py → inferred_skills.md
```

In practice, the project has two evaluation modes:

- `Single-turn`: the model produces a plan only, and the output is scored for adherence, safety, clarity, context use, cost, and latency.
- `Multi-turn`: the model acts like a coding agent with tools, producing step-by-step traces, file writes, command choices, and per-run execution metrics.

The main submitted comparison is `baseline AGENTS.md` vs `generated AGENTS.md`. The `inferred_skills.md` path is an exploratory extension that was tested separately as an additional condition, not as the primary submitted result.

---

## Project Structure

The repository has three main layers: generation code in `src/`, generated context artifacts in `outputs/`, and evaluation runs in `eval/runs/`.

```
src/
  analyze_repo.py                # Static repo scan → repo_profile.json
  generate_agents.py             # repo_profile.json → generated_AGENTS.md
  build_eval_prompt.py           # Builds prompt = AGENTS.md + task text
  run_task1_ab_eval.py           # Task 1 single-turn A/B runner
  run_task2_ab_eval.py           # Task 2 single-turn A/B runner
  run_task3_ab_eval.py           # Task 3 single-turn A/B runner
  statistical_test.py            # Mann-Whitney U significance test
  multiturn_agent.py             # Shared multi-turn agent loop + tool simulator
  run_task1_abc_multiturn_eval.py# Multi-turn runner (can run A/B/C or A/B only)
  infer_skills.py                # Experimental auto-inferred skills generator
  generate_charts.py             # Chart generation for presentation assets
  recompute_clarity_context_metrics.py  # Post-process eval outputs

outputs/
  repo_profile.json              # Deterministic repo signal extraction
  baseline_AGENTS.md             # Generic baseline instructions
  generated_AGENTS.md            # Repo-specific AGENTS.md
  inferred_skills.md             # Experimental skills artifact for C condition
  *.png                          # Generated charts used in analysis / presentation

eval/runs/
  task1/                         # Original prompt inputs for Task 1
  task2/                         # Original prompt inputs for Task 2
  task3/                         # Original prompt inputs for Task 3
  task1_single_turn_AB_n20/      # Final Task 1 single-turn A/B run set
  task2_single_turn_AB_n20/      # Final Task 2 single-turn A/B run set
  task3_single_turn_AB_n20/      # Final Task 3 single-turn A/B run set
  task1_multiturn_AB_rerun_n20/  # Main submitted multi-turn A/B rerun logs
  task1_multiturn_ABC_smoke/     # Early exploratory smoke run (A/B/C)
  task1_multiturn_ABC_smoke2/    # Early exploratory smoke run (A/B/C)

scripts/
  build_task1_prompts.sh         # Helper to build Task 1 prompts
```

### Directory Guide

- `src/` contains the pipeline implementation: repo analysis, AGENTS generation, eval runners, stats, and multi-turn agent logic.
- `outputs/` contains generated context files and presentation assets. These are the intermediate artifacts produced by the pipeline.
- `eval/runs/` contains per-experiment outputs. Each experiment folder stores raw per-run outputs plus an aggregate `summary.json`.

### Eval Directory Conventions

- Single-turn runs store `output.md` and `metrics.json` per run, plus a folder-level `summary.json`.
- Multi-turn runs store `trace.json` and `metrics.json` per run, plus a folder-level `summary.json`.
- `task1_multiturn_AB_rerun_n20/` is the clean A/B-only rerun used as the main multi-turn comparison: `A_baseline` vs `B_generated`.
- `task1_multiturn_ABC_smoke/` and `task1_multiturn_ABC_smoke2/` are exploratory experiments. In these folders, `C_generated_skills` means generated `AGENTS.md` plus an auto-inferred skills file. These were retained for internal exploration and are not the primary submitted comparison.

---

## Metrics Tracked Per Run

| Metric | What it measures |
|---|---|
| `plan_adherence_score` | Fraction of repo-specific workflow steps the agent mentioned (0–1) |
| `task_success` | Did the agent address all 4 required task items? (binary) |
| `is_broken` | Output too short or missing critical requirements |
| `safety_violation_count` | Number of safety anti-patterns fired (hardcoded secrets, skipped checks, etc.) |
| `latency_seconds` | Wall-clock response time |
| `estimated_cost_usd` | Token-based cost estimate |

---

## Task 1 Single-Turn Results — Backend API Contract Change

**Task:** Add an optional `category` field to an existing item response model. Produce a plan only — no edits.

**Conditions:**
- **Baseline** — generic AGENTS.md with no repo-specific context
- **Generated** — AGENTS.md auto-generated from static analysis of `full-stack-fastapi-template`

| Metric | Baseline | Generated | Δ |
|---|---|---|---|
| Plan adherence score (mean) | 0.60 | 0.93 | **+0.33** |
| Task success rate | 100% | 100% | 0 |
| Safe runs | 2/3 | 3/3 | +1 |

**Statistical test — Mann-Whitney U (exact, one-tailed):**

| N | p-value | Decision |
|---|---|---|
| 3 (real runs) | 0.05 | Reject H₀ |
| 20 (bootstrap simulation) | 7.25 × 10⁻¹² | Reject H₀ |

Effect size: rank-biserial r = 1.0 — every generated score outranked every baseline score.

The generated `AGENTS.md` teaches the agent two repo-specific steps the baseline consistently skips: `npm run generate-client` after any route/model change, and Docker service awareness.

---

## Task 1 Multi-Turn Results — A/B Rerun

**Task:** Add an optional `category` field to the item model, regenerate the frontend client where needed, and act through a multi-step tool loop rather than writing a plan only.

**Conditions:**
- **A_baseline** — generic baseline AGENTS.md
- **B_generated** — repo-specific generated AGENTS.md

| Metric | A_baseline | B_generated | Readout |
|---|---|---|---|
| Plan adherence (mean) | 0.36 | **0.76** | Generated followed the repo-specific workflow more closely |
| Task completed | **17/20** | 14/20 | Baseline completed more often under the step budget |
| Task success score | 0.67 | **0.97** | Generated produced more complete end-to-end task behavior |
| Safe runs | 20/20 | 20/20 | No safety violations in either condition |
| Hallucinated commands (mean) | 0.85 | **0.00** | Generated eliminated command hallucinations |
| Client regenerated | 0/20 | **18/20** | Generated consistently performed the repo-specific client update |
| Cost / run (avg) | **$0.1620** | $0.2366 | Generated was better but more expensive |
| Latency (avg) | **25.3s** | 26.3s | Similar runtime, slight overhead for generated |

Multi-turn commands are simulated; their output does not show that a command ran or succeeded. The `hallucinated_commands` metrics count commands the simulator does not recognize, including unsupported arguments and npm scripts missing from the targeted `package.json`. When that file is absent, only the simulator's built-in npm scripts are recognized. This stricter classification and the removal of simulated migration writes for rejected commands apply to new runs; saved results are unchanged and affected metrics are not directly comparable. The multi-turn `migration_created`, `client_regenerated`, and `task_success_score` fields are historical proxies based on simulated writes and command text, not proof of completed operations or passing tests. Plan adherence and safety checks also inspect command text, including unsupported commands. The single-turn metrics are unaffected.

This rerun shows the main multi-turn tradeoff more clearly than the earlier exploratory runs: the generated `AGENTS.md` substantially improves repo-aware execution quality, but it also uses more steps and budget, which can reduce clean completion under a fixed turn limit.

---

## Setup

Python 3.11 or newer is required. To fetch the pinned target repository:

```bash
git submodule update --init target_repos/full-stack-fastapi-template
python -m pip install -r requirements.txt pytest
python -m pytest -q --ignore=target_repos
```

The target Gitlink is pinned to `d92bb189230bb8d27554d6cd947ef3ae543bae31`; initialization needs network access to the configured upstream. The pinned commit was not verified against that upstream in this checkout. The offline tests use temporary repositories and do not require the target checkout or an API key. For API evaluations, set `OPENAI_API_KEY` in the environment or in a local `.env` file. API evaluations incur costs.

The committed `outputs/repo_profile.json` contains the original machine's absolute repository path. The committed `outputs/generated_AGENTS.md` also differs from the current generator: its setup section requires only the listed commands, while the generator recommends verifying inferred commands. These historical artifacts are retained for the recorded experiments. Running `src/analyze_repo.py` or `src/generate_agents.py` directly overwrites them; compare generated results in a separate location before replacing them. Analysis now sorts commands, so their order can also differ from the historical profile. For an unchanged repository at the same path, analysis and generation are deterministic. Missing or malformed package and pyproject configuration is skipped during command detection.

**Run the Task 1 single-turn A/B eval:**
```bash
python src/run_task1_ab_eval.py \
  --model gpt-4o \
  --n 3 \
  --out-dir eval/runs/task1_single_turn_new \
  --input-price-per-1m 2.50 \
  --output-price-per-1m 10.00
```

**Run the Task 1 multi-turn A/B eval:**
```bash
python src/run_task1_abc_multiturn_eval.py \
  --model gpt-4o \
  --n 20 \
  --conditions A,B \
  --out-dir eval/runs/task1_multiturn_new \
  --input-price-per-1m 2.50 \
  --output-price-per-1m 10.00
```

**Run the statistical test on a new single-turn run:**
```bash
python src/statistical_test.py --eval-dir eval/runs/task1_single_turn_new
```
The statistical test writes its results into the selected run directory.

---

## Roadmap

### Phase 1 — Automated Context Generation
- [x] Static repo analysis → `repo_profile.json`
- [x] Deterministic `generated_AGENTS.md` creation from repo signals
- [x] Risk-aware guardrails and repo-specific command extraction

### Phase 2 — Single-Turn Evaluation
- [x] Task 1 single-turn A/B evaluation
- [x] Task 2 single-turn A/B evaluation
- [x] Task 3 single-turn A/B evaluation
- [x] Statistical significance testing for plan adherence
- [x] Cross-task comparison for adherence, safety, clarity, context use, cost, and latency

### Phase 3 — Multi-Turn Evaluation
- [x] Multi-turn coding-agent framework with tool-based execution traces
- [x] Task 1 multi-turn A/B rerun (`A_baseline` vs `B_generated`)
- [x] Per-run trace capture via `trace.json` and per-run scoring via `metrics.json`
- [x] Exploratory A/B/C skills-based extension retained separately for internal comparison

### Future Directions
- [ ] Extend multi-turn evaluation to Tasks 2 and 3
- [ ] Replace simulated command outcomes with more realistic isolated validation
- [ ] Make generated instructions more action-first and budget-aware for execution settings
- [ ] Isolate which AGENTS.md sections help planning versus hurt execution

---

## Dependencies

| Package | Purpose |
|---|---|
| `openai` | GPT-4o API calls |
| `python-dotenv` | `.env` key loading |
| `scipy` | Mann-Whitney U exact test |
| `numpy` | Numerical support |

