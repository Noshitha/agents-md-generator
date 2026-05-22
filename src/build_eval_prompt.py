from pathlib import Path
import argparse


PROMPT_TEMPLATE = """You are a coding agent working inside the repository `fastapi/full-stack-fastapi-template`.

Use the following AGENTS.md instructions:

{agents_md}

Task:

{task_prompt}

Please:
1. Identify the files/subsystems likely affected.
2. Produce a minimal implementation plan.
3. List validation commands/checks you would run.
4. Mention any risks or assumptions.
Do not make changes yet.
"""


def build_prompt(task_path: Path, agents_path: Path, output_path: Path) -> None:
    task_prompt = task_path.read_text(encoding="utf-8").strip()
    agents_md = agents_path.read_text(encoding="utf-8").strip()

    final_prompt = PROMPT_TEMPLATE.format(
        agents_md=agents_md,
        task_prompt=task_prompt,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(final_prompt, encoding="utf-8")

    print(f"Wrote {output_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True, help="Path to task prompt markdown")
    parser.add_argument("--agents", required=True, help="Path to AGENTS.md file")
    parser.add_argument("--out", required=True, help="Output prompt path")
    args = parser.parse_args()

    build_prompt(
        task_path=Path(args.task),
        agents_path=Path(args.agents),
        output_path=Path(args.out),
    )


if __name__ == "__main__":
    main()