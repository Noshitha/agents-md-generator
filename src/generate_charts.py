"""
Comprehensive multi-metric comparison chart for all 3 task slides.
2×4 grid — one panel per metric — with tier labels and improvement indicators.
Output: outputs/chart_task1_hard.png, chart_task2_easy.png, chart_task3_medium.png
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.gridspec as gridspec
import numpy as np
from pathlib import Path

BG       = "#0d1b4b"
PANEL_BG = "#162050"
BLUE     = "#4a90d9"
ORANGE   = "#f0a500"
WHITE    = "#ffffff"
GREEN    = "#2ecc71"
AMBER    = "#f39c12"
RED      = "#e74c3c"
GREY     = "#5d6d8a"
SUBTEXT  = "#8aa0c4"

# (display name, unit label, higher_is_better, format string, tier label)
METRIC_DEFS = [
    ("Plan Adherence",      "(0–1)",       True,  "{:.2f}",  "Tier 1A"),
    ("Safety Violations",   "(avg/run)",   False, "{:.2f}",  "Tier 1B"),
    ("Safe Runs",           "(/20)",       True,  "{:.0f}",  "Tier 1B"),
    ("Task Clarity",        "(score)",     True,  "{:.1f}",  "Tier 2"),
    ("Context Utilization", "(0–1)",       True,  "{:.3f}",  "Tier 2"),
    ("Cost / Run",          "(USD)",       False, "${:.4f}", "Tier 3"),
    ("Latency",             "(seconds)",   False, "{:.2f}",  "Tier 3"),
    ("Output Tokens",       "(count)",     None,  "{:.0f}",  "info"),
]

TIER_COLORS = {
    "Tier 1A": "#4a90d9",
    "Tier 1B": "#e74c3c",
    "Tier 2":  "#f0a500",
    "Tier 3":  "#5d6d8a",
    "info":    "#5d6d8a",
}

TASKS = [
    dict(
        title="Task 2 — Easy: Environment Variable Addition",
        difficulty="Easy", diff_color="#2ecc71",
        subtitle="SMTP_PORT env var  ·  1 subsystem  ·  N = 20 runs per condition",
        baseline  = [0.80, 1.95,  0,  4.50, 0.000, 0.0064, 5.17, 589],
        generated = [1.00, 0.65,  7,  7.15, 0.200, 0.0081, 6.26, 603],
        deltas    = ["+0.20", "−1.30", "+7", "+2.65", "+0.20",
                     "+$0.0017\n(+27%)", "+1.09s", "+14"],
        hero = ("Safety only partially improved (0→7/20). "
                "The word 'hardcoding' triggers a false positive in 13/20 generated runs — "
                "agents saying the right thing get flagged."),
        out = "outputs/chart_task2_easy.png",
    ),
    dict(
        title="Task 3 — Medium: Database Model Change",
        difficulty="Medium", diff_color="#f0a500",
        subtitle="updated_at to Item SQLModel + ItemPublic  ·  2 subsystems  ·  N = 20 runs per condition",
        baseline  = [0.80, 1.00,  0,  0.80, 0.000, 0.0068, 4.84, 624],
        generated = [1.00, 0.00, 20, 13.50, 0.362, 0.0096, 6.38, 756],
        deltas    = ["+0.20", "Eliminated", "+20 ✓", "+12.70", "+0.36",
                     "+$0.0029\n(+43%)", "+1.55s", "+132"],
        hero = ("Perfect safety flip 0/20 → 20/20. Largest clarity jump in the experiment (16×). "
                "One guardrail — 'run generate-client after any model change' — eliminated all violations."),
        out = "outputs/chart_task3_medium.png",
    ),
    dict(
        title="Task 1 — Hard: API Contract Change",
        difficulty="Hard", diff_color="#e74c3c",
        subtitle="category field to Item response  ·  3 subsystems  ·  N = 20 runs per condition",
        baseline  = [0.55, 0.60,  8, 3.80, 0.000, 0.0082, 6.20, 775],
        generated = [1.00, 0.00, 20,  5.60, 0.408, 0.0089, 7.04, 687],
        deltas    = ["+0.45", "Eliminated", "+12 ✓", "+1.80", "+0.41",
                     "+$0.0007\n(+8%)", "+0.84s", "−87"],
        hero = ("Best ROI: largest adherence gap (+45pp) at only +8% cost. "
                "Generated agents wrote shorter but complete plans (−87 output tokens). "
                "Context utilization 0 → 0.41 — highest across all tasks."),
        out = "outputs/chart_task1_hard.png",
    ),
]


def improvement_color(idx, bv, gv):
    higher_is_better = METRIC_DEFS[idx][2]
    if higher_is_better is None:
        return GREY
    if higher_is_better:
        return GREEN if gv > bv else (AMBER if gv < bv else GREY)
    else:
        return GREEN if gv < bv else (AMBER if gv > bv else GREY)


def draw_task_chart(task: dict):
    fig = plt.figure(figsize=(15, 8.5), facecolor=BG)
    fig.patch.set_facecolor(BG)

    # ── header ────────────────────────────────────────────────────────────────
    fig.text(0.025, 0.975, task["title"],
             fontsize=16, fontweight="bold", color=WHITE, va="top")
    fig.text(0.025, 0.942,
             f"[{task['difficulty']}]  {task['subtitle']}",
             fontsize=9, color=task["diff_color"], va="top")
    fig.text(0.025, 0.916,
             "GPT-4o  ·  Temperature 0.0  ·  Only the AGENTS.md context changed between conditions",
             fontsize=8, color=SUBTEXT, va="top")

    # ── 2×4 grid ──────────────────────────────────────────────────────────────
    gs = gridspec.GridSpec(2, 4, figure=fig,
                           left=0.03, right=0.98,
                           top=0.88, bottom=0.16,
                           hspace=0.60, wspace=0.35)

    for idx, (name, unit, hib, fmt, tier) in enumerate(METRIC_DEFS):
        row, col = divmod(idx, 4)
        ax = fig.add_subplot(gs[row, col])
        ax.set_facecolor(PANEL_BG)
        for spine in ax.spines.values():
            spine.set_color("#2a3f7a")
        ax.tick_params(colors=WHITE, labelsize=7.5)

        bv = task["baseline"][idx]
        gv = task["generated"][idx]
        delta_str = task["deltas"][idx]
        imp_col = improvement_color(idx, bv, gv)

        # Bars
        bar_objs = ax.bar([0, 1], [bv, gv],
                          color=[BLUE, ORANGE], width=0.5, zorder=3,
                          edgecolor="none")

        # Value labels above bars
        scale = max(bv, gv, 0.001)
        for bar, val in zip(bar_objs, [bv, gv]):
            ax.text(bar.get_x() + bar.get_width() / 2,
                    val + scale * 0.06,
                    fmt.format(val),
                    ha="center", va="bottom",
                    fontsize=8, color=WHITE, fontweight="bold")

        ax.set_xlim(-0.55, 1.55)
        ax.set_ylim(0, scale * 1.55 + 0.0001)
        ax.set_xticks([0, 1])
        ax.set_xticklabels(["Baseline", "Generated"], fontsize=7.5, color=WHITE)
        ax.set_yticks([])
        ax.grid(axis="y", color="#2a3f7a", linestyle="--", linewidth=0.5, zorder=0)

        # Subplot title + unit
        ax.set_title(f"{name}\n{unit}", fontsize=8.5, color=WHITE,
                     pad=5, fontweight="bold", linespacing=1.3)

        # Tier badge (top-left)
        ax.text(0.03, 0.985, tier, transform=ax.transAxes,
                fontsize=6.5, color=TIER_COLORS[tier],
                fontweight="bold", va="top")

        # Delta annotation (bottom-right, coloured by direction)
        ax.text(0.97, 0.03, delta_str, transform=ax.transAxes,
                fontsize=7.5, color=imp_col, fontweight="bold",
                ha="right", va="bottom", linespacing=1.3)

        # Coloured top-border strip = improvement indicator
        ax.axhspan(scale * 1.48, scale * 1.55 + 0.0001,
                   facecolor=imp_col, alpha=0.85, zorder=10)

    # ── legend ────────────────────────────────────────────────────────────────
    legend_handles = [
        mpatches.Patch(facecolor=BLUE,   label="Baseline"),
        mpatches.Patch(facecolor=ORANGE, label="Generated"),
        mpatches.Patch(facecolor=GREEN,  label="■ Improvement"),
        mpatches.Patch(facecolor=AMBER,  label="■ Tradeoff"),
        mpatches.Patch(facecolor=GREY,   label="■ Neutral"),
    ]
    fig.legend(handles=legend_handles, loc="lower center", ncol=5,
               facecolor=PANEL_BG, edgecolor="#2a3f7a",
               labelcolor=WHITE, fontsize=8.5,
               bbox_to_anchor=(0.5, 0.005))

    # ── key finding ───────────────────────────────────────────────────────────
    fig.text(0.025, 0.10, f"Key finding:  {task['hero']}",
             fontsize=8, color=SUBTEXT, style="italic", va="bottom",
             wrap=True)

    plt.savefig(task["out"], dpi=160, bbox_inches="tight",
                facecolor=BG, edgecolor="none")
    plt.close(fig)
    print(f"Saved: {task['out']}")


if __name__ == "__main__":
    Path("outputs").mkdir(exist_ok=True)
    for t in TASKS:
        draw_task_chart(t)
    print("\nAll 3 charts generated.")