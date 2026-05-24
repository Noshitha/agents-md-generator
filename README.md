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
