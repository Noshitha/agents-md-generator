"""
Auto-infer SKILLS.md from the target repo.

Reads key repo files → calls GPT-4o → saves outputs/inferred_skills.md.
The generated SKILLS.md provides step-by-step recipes for common change
operations specific to this codebase (exact file paths, commands, safety rules).
"""

import argparse
import pathlib

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI()

REPO_ROOT = (
    pathlib.Path(__file__).parent.parent
    / "target_repos"
    / "full-stack-fastapi-template"
)


def _read(rel_path: str, cap: int = 3500) -> str:
    p = REPO_ROOT / rel_path
    if p.exists() and p.is_file():
        return p.read_text(errors="replace")[:cap]
    return f"[not found: {rel_path}]"


def _latest_migration(cap: int = 800) -> str:
    d = REPO_ROOT / "backend" / "alembic" / "versions"
    if not d.exists():
        return "[no migrations found]"
    files = sorted(d.glob("*.py"))
    if not files:
        return "[no migrations found]"
    sample = files[-1]
    return f"{sample.name}:\n{sample.read_text(errors='replace')[:cap]}"


def build_context() -> str:
    sections = {
        "backend/app/models.py": _read("backend/app/models.py"),
        "backend/app/api/routes/items.py": _read("backend/app/api/routes/items.py"),
        "backend/app/core/config.py": _read("backend/app/core/config.py"),
        "backend/alembic/env.py": _read("backend/alembic/env.py", cap=1500),
        "frontend/package.json": _read("frontend/package.json", cap=1000),
        "compose.yml": _read("compose.yml", cap=2000),
        "pyproject.toml": _read("pyproject.toml", cap=1500),
        "Latest alembic migration (example)": _latest_migration(),
    }
    return "\n\n".join(
        f"### {name}\n```\n{content}\n```" for name, content in sections.items()
    )


PROMPT_TEMPLATE = """You are documenting a full-stack FastAPI + React codebase for coding agents.

Based on the repository code below, generate a concise SKILLS.md with 4 skills:

1. **Add or modify a field in the Item API response model**
2. **Add a new environment variable to the backend config**
3. **Add a new API endpoint to the items router**
4. **Perform a database schema migration**

For each skill include:
- Exact file paths to modify (from this repo)
- Numbered steps with exact shell commands
- Which command regenerates the frontend TypeScript client
- Safety rules specific to this repo (e.g. never auto-migrate without review)

Use real paths and commands from the code. Be concrete, not generic.

## Repository Code

{context}

Generate SKILLS.md now:"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="outputs/inferred_skills.md")
    parser.add_argument("--model", default="gpt-4o")
    args = parser.parse_args()

    print("Reading repo files...")
    context = build_context()

    print(f"Calling {args.model} to generate SKILLS.md...")
    response = client.chat.completions.create(
        model=args.model,
        messages=[{"role": "user", "content": PROMPT_TEMPLATE.format(context=context)}],
        temperature=0.2,
        max_tokens=2200,
    )

    skills_md = response.choices[0].message.content
    usage = response.usage

    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(skills_md)

    print(f"Saved → {out_path}")
    print(
        f"Tokens: {usage.prompt_tokens:,} input / {usage.completion_tokens:,} output  "
        f"| cost ≈ ${usage.prompt_tokens/1e6*2.50 + usage.completion_tokens/1e6*10:.4f}"
    )


if __name__ == "__main__":
    main()
