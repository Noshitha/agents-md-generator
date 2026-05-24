# faros-agents-md-generator

Automatically generates repo-specific `AGENTS.md` files from static repository analysis, then measures whether those instructions actually change coding-agent behaviour — using a rigorous A/B evaluation pipeline with statistical testing.

> **Core question:** does a generated `AGENTS.md` improve plan adherence, safety, and task reliability — or is it noise?

---

## What It Does

```text
target repo (local clone)
  └─► analyze_repo.py       — static analysis → repo_profile.json
        └─► generate_agents.py  — profile → generated AGENTS.md
              └─► run_task1_ab_eval.py  — A/B eval: baseline vs generated
                    └─► statistical_test.py  — Mann-Whitney U significance test
```

---

## Project Structure

```
src/
  analyze_repo.py          # Static repo analysis → repo_profile.json
  generate_agents.py       # Profile → AGENTS.md template
  build_eval_prompt.py     # Assembles eval prompts from task + agents file
  run_task1_ab_eval.py     # A/B eval runner: calls OpenAI, scores output
  statistical_test.py      # Mann-Whitney U test on plan adherence scores
  utils.py

outputs/
  repo_profile.json        # Inferred repo signals
  baseline_AGENTS.md       # Generic baseline instructions
  generated_AGENTS.md      # Repo-specific generated instructions

eval/runs/
  task1_single_turn_AB/
    baseline/run_N/metrics.json    # Per-run scores (baseline condition)
    generated/run_N/metrics.json   # Per-run scores (generated condition)
    summary.json                   # Aggregated means + delta
    statistical_test_results.json  # MWU test output

scripts/
  build_task1_prompts.sh   # Helper to build baseline/generated prompt files
```

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

## Task 1 Results — Backend API Contract Change

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

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # add OPENAI_API_KEY
```

**Run the A/B eval:**
```bash
python src/run_task1_ab_eval.py \
  --model gpt-4o \
  --n 3 \
  --out-dir eval/runs/task1_single_turn_AB \
  --input-price-per-1m 2.50 \
  --output-price-per-1m 10.00
```

**Run the statistical test:**
```bash
python src/statistical_test.py
```

---

## Roadmap

### Phase 1 — Single-turn baseline (current)
- [x] Static repo analysis + AGENTS.md generation
- [x] A/B eval pipeline (plan adherence, task success, safety, cost/latency)
- [x] Statistical significance testing (Mann-Whitney U, exact)

### Phase 2 — Multi-task single-turn coverage (next)
- [ ] Task 2: Database schema migration — does the agent flag migration risk?
- [ ] Task 3: Auth/security change — does the agent surface the right caution signals?
- [ ] Cross-task plan adherence comparison: which task types benefit most from repo-specific instructions?

### Phase 3 — Multi-subsystem tradeoff analysis
- [ ] Move beyond single-turn prompts to multi-step agent interactions
- [ ] Isolate which AGENTS.md sections drive improvement vs. introduce regression
- [ ] Measure true cost/quality tradeoffs of generating and consuming AGENTS.md at scale
- [ ] Answer: what exactly makes and breaks an AGENTS.md?

---

## Dependencies

| Package | Purpose |
|---|---|
| `openai` | GPT-4o API calls |
| `python-dotenv` | `.env` key loading |
| `scipy` | Mann-Whitney U exact test |
| `numpy` | Numerical support |

