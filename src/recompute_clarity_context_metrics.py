"""
Retroactively compute task_clarity and context_utilization metrics for existing
single-turn eval runs, without making any new API calls.

Reads each run's output.md, patches its metrics.json, then rewrites summary.json.
"""
import json
import re
from pathlib import Path
from statistics import mean

# ---------------------------------------------------------------------------
# Metric functions (identical to those added to the eval scripts)
# ---------------------------------------------------------------------------

def calculate_clarity_metrics(output_text: str) -> dict:
    """
    Task Clarity: measures how concrete and executable the plan is.
    - command_count: distinct shell commands named in backticks
    - file_count: distinct source files named (by extension)
    - clarity_score: command_count + file_count
    """
    backtick_items = re.findall(r'`([^`\n]{3,60})`', output_text)
    commands_in_plan = {
        item.strip() for item in backtick_items
        if re.search(r'[\s/]|^(?:npm|ruff|pytest|docker|alembic|uvicorn|python|pip|git)\b',
                     item.strip(), re.IGNORECASE)
    }
    command_count = len(commands_in_plan)

    files_in_plan = set(re.findall(
        r'\b[\w./\-]+\.(?:py|ts|tsx|sql|env|yml|yaml|toml|json)\b',
        output_text,
    ))
    file_count = len(files_in_plan)

    return {
        "command_count": command_count,
        "file_count": file_count,
        "clarity_score": command_count + file_count,
        "commands_found": sorted(commands_in_plan),
        "files_found": sorted(files_in_plan),
    }


def calculate_context_utilization(output_text: str, repo_commands: list[str]) -> dict:
    """
    Context Utilization: fraction of repo-specific commands (from repo_profile.json)
    that appear in the plan output.
    """
    text_lower = output_text.lower()
    matched = [cmd for cmd in repo_commands if cmd.lower() in text_lower]
    score = len(matched) / len(repo_commands) if repo_commands else 0.0
    return {
        "matched_commands": matched,
        "total_repo_commands": len(repo_commands),
        "matched_count": len(matched),
        "context_utilization_score": round(score, 4),
    }


# ---------------------------------------------------------------------------
# Summary rebuilder (mirrors the summarize() logic in the eval scripts)
# ---------------------------------------------------------------------------

def rebuild_summary(all_metrics: list[dict]) -> dict:
    summary = {}
    for condition in sorted({m["condition"] for m in all_metrics}):
        rows = [m for m in all_metrics if m["condition"] == condition]
        rel_rows = [m["reliability_metrics"] for m in rows]
        n = len(rows)

        cost_fields = ["input_tokens", "output_tokens", "total_tokens",
                       "latency_seconds", "estimated_cost_usd"]
        entry = {field: mean(m[field] for m in rows) for field in cost_fields}
        entry["plan_adherence_score"]         = mean(r["plan_adherence_score"]         for r in rel_rows)
        entry["plan_adherence_items_matched"]  = mean(r["plan_adherence_items_matched"]  for r in rel_rows)
        entry["task_success_rate"]   = sum(r["task_success"] for r in rel_rows) / n
        entry["broken_output_count"] = sum(r["is_broken"]    for r in rel_rows)

        saf_rows = [m["safety_metrics"] for m in rows]
        entry["safety_violation_count_mean"] = mean(s["safety_violation_count"] for s in saf_rows)
        entry["safe_run_count"]   = sum(1 for s in saf_rows if s["is_safe"])
        entry["unsafe_run_count"] = sum(1 for s in saf_rows if not s["is_safe"])
        entry["total_runs"] = n

        cla_rows = [m["clarity_metrics"] for m in rows if "clarity_metrics" in m]
        ctx_rows = [m["context_utilization"] for m in rows if "context_utilization" in m]
        if cla_rows:
            entry["clarity_score_mean"] = mean(c["clarity_score"] for c in cla_rows)
            entry["command_count_mean"] = mean(c["command_count"] for c in cla_rows)
            entry["file_count_mean"]    = mean(c["file_count"]    for c in cla_rows)
        if ctx_rows:
            entry["context_utilization_score_mean"] = mean(
                c["context_utilization_score"] for c in ctx_rows
            )

        summary[condition] = entry

    if "baseline" in summary and "generated" in summary:
        b, g = summary["baseline"], summary["generated"]
        delta_fields = ["input_tokens", "output_tokens", "total_tokens", "latency_seconds",
                        "estimated_cost_usd", "plan_adherence_score", "plan_adherence_items_matched"]
        delta = {f: g[f] - b[f] for f in delta_fields}
        extra = g["input_tokens"] - b["input_tokens"]
        delta["context_overhead_percent"] = (extra / b["input_tokens"] * 100) if b["input_tokens"] else 0
        delta["task_success_rate"]             = g["task_success_rate"]             - b["task_success_rate"]
        delta["broken_output_count"]           = g["broken_output_count"]           - b["broken_output_count"]
        delta["safety_violation_count_mean"]   = g["safety_violation_count_mean"]   - b["safety_violation_count_mean"]
        delta["unsafe_run_count"]              = g["unsafe_run_count"]              - b["unsafe_run_count"]
        if "clarity_score_mean" in g and "clarity_score_mean" in b:
            delta["clarity_score"] = g["clarity_score_mean"] - b["clarity_score_mean"]
        if "context_utilization_score_mean" in g and "context_utilization_score_mean" in b:
            delta["context_utilization_score"] = (
                g["context_utilization_score_mean"] - b["context_utilization_score_mean"]
            )
        summary["delta_generated_minus_baseline"] = delta

    return summary


# ---------------------------------------------------------------------------
# Main: iterate all 3 task run dirs
# ---------------------------------------------------------------------------

TASK_DIRS = [
    "eval/runs/task1_single_turn_AB_n20",
    "eval/runs/task2_single_turn_AB_n20",
    "eval/runs/task3_single_turn_AB_n20",
]

BASE = Path(__file__).parent.parent  # project root


def main():
    # Load repo commands
    profile_path = BASE / "outputs" / "repo_profile.json"
    repo_profile = json.loads(profile_path.read_text(encoding="utf-8"))
    cmds = repo_profile.get("commands", {})
    repo_commands = (
        cmds.get("backend", []) + cmds.get("frontend", []) +
        cmds.get("docker", []) + cmds.get("pyproject", [])
    )
    print(f"Repo commands loaded ({len(repo_commands)}): {repo_commands}\n")

    for task_dir_rel in TASK_DIRS:
        task_dir = BASE / task_dir_rel
        if not task_dir.exists():
            print(f"[SKIP] {task_dir_rel} — directory not found")
            continue

        print(f"{'='*60}")
        print(f"Processing: {task_dir_rel}")

        # Find all metrics.json files
        metrics_files = sorted(task_dir.glob("*/run_*/metrics.json"))
        if not metrics_files:
            print(f"  [SKIP] No run dirs found.")
            continue

        all_metrics = []
        for mf in metrics_files:
            existing = json.loads(mf.read_text(encoding="utf-8"))

            # Read corresponding output.md
            output_path = mf.parent / "output.md"
            if not output_path.exists():
                # Fall back to stored path
                alt = Path(existing.get("output_path", ""))
                if alt.exists():
                    output_path = alt
                else:
                    print(f"  [WARN] output.md not found for {mf}, skipping")
                    continue

            output_text = output_path.read_text(encoding="utf-8")

            # Compute new metrics
            clarity     = calculate_clarity_metrics(output_text)
            context_util = calculate_context_utilization(output_text, repo_commands)

            # Patch metrics.json in-place
            existing["clarity_metrics"]    = clarity
            existing["context_utilization"] = context_util
            mf.write_text(json.dumps(existing, indent=2), encoding="utf-8")

            all_metrics.append(existing)

        print(f"  Patched {len(all_metrics)} run files.")

        # Rebuild and write summary.json
        summary = rebuild_summary(all_metrics)
        summary_path = task_dir / "summary.json"
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"  Wrote summary.json\n")

        # Print the key new metrics
        for cond in ("baseline", "generated"):
            if cond not in summary:
                continue
            s = summary[cond]
            print(f"  [{cond}]")
            print(f"    plan_adherence_score          : {s.get('plan_adherence_score', 'N/A'):.2f}")
            print(f"    safe_run_count                : {s.get('safe_run_count', 'N/A')}/{s.get('total_runs', '?')}")
            print(f"    clarity_score_mean            : {s.get('clarity_score_mean', 'N/A'):.2f}")
            print(f"      command_count_mean          : {s.get('command_count_mean', 'N/A'):.2f}")
            print(f"      file_count_mean             : {s.get('file_count_mean', 'N/A'):.2f}")
            print(f"    context_utilization_score_mean: {s.get('context_utilization_score_mean', 'N/A'):.4f}")
            print()

        if "delta_generated_minus_baseline" in summary:
            d = summary["delta_generated_minus_baseline"]
            print(f"  [delta generated - baseline]")
            print(f"    plan_adherence_score   : {d.get('plan_adherence_score', 0):+.2f}")
            print(f"    clarity_score          : {d.get('clarity_score', 0):+.2f}")
            print(f"    context_utilization    : {d.get('context_utilization_score', 0):+.4f}")
            print()


if __name__ == "__main__":
    main()
