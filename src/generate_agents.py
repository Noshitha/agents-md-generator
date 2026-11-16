import copy
import json
import re
from pathlib import Path


def bullet_list(items):
    if not items:
        return "- None detected"
    return "\n".join(f"- `{item}`" for item in items)


def generate_agents_md(profile):
    repo_name = profile["repo_name"]
    dirs = profile["top_level_dirs"]
    files = profile["important_files"]
    languages = profile["languages"]
    frameworks = profile["frameworks"]
    risks = profile["inferred_risks"]
    commands = profile["commands"]

    # --- Change Guidance (risk-driven, only show relevant ones) ---
    risk_guidance = {
        "backend_frontend_api_contract_drift": "For backend API changes, check whether frontend API clients, schemas, or user-facing behavior also need updates.",
        "database_model_or_schema_change": "For database/model changes, verify schema compatibility and whether migrations or fixture updates are needed.",
        "secrets_or_environment_config": "For environment/config changes, update example configuration files and documentation. Never hardcode credentials.",
        "local_service_dependency_docker": "Check the repository's Docker configuration for local service dependencies.",
        "auth_or_backend_security_sensitive_change": "Auth, JWT, and password flows are security-sensitive. Avoid refactoring these unless explicitly instructed.",
    }

    guidance_lines = [
        f"- {risk_guidance[r]}"
        for r in risks
        if r in risk_guidance
    ]
    change_guidance = "\n".join(guidance_lines) if guidance_lines else "- No specific risk guidance inferred."

    evidence = profile.get("evidence")
    if isinstance(evidence, dict):
        command_items = evidence.get("commands", [])
        command_lines = []
        for classification, label in (("verified", "Verified configuration"), ("documented", "Documented, unverified")):
            entries = []
            for item in command_items:
                if item.get("classification") != classification:
                    continue
                command = item.get("value", "")
                if item.get("type") != "package.json" and re.search(r"\b(?:npm|pnpm|yarn|bun)\b", command):
                    continue
                directory = item.get("working_directory")
                source = item.get("source", "")
                suffix = f"working directory: `{directory}`" if directory else "working directory not established"
                key = item.get("key", "") if classification == "verified" else ""
                reference = f"`{source}`: `{key}`" if key else f"`{source}`"
                line = f"- `{command}` (source: {reference}; {suffix})"
                if line not in entries:
                    entries.append(line)
            if entries:
                command_lines.append(f"{label}:\n" + "\n".join(entries))
        command_text = "\n\n".join(command_lines) if command_lines else "- None detected"
        framework_items = evidence.get("frameworks", [])
        verified = sorted({item["value"] for item in framework_items if item.get("classification") == "verified"})
        inferred = sorted(set(frameworks) - set(verified))
        framework_text = f"Configuration: {', '.join(verified) if verified else 'none detected'}; inferred: {', '.join(inferred) if inferred else 'none detected'}"
    else:
        legacy = sorted({command for values in commands.values() for command in values if not re.search(r"\b(?:npm|pnpm|yarn|bun)\b", command)})
        command_text = "Unverified legacy commands (working directory not established):\n" + bullet_list(legacy)
        framework_text = "Unverified legacy detection: " + (", ".join(frameworks) if frameworks else "none detected")

    md = f"""# AGENTS.md
> Auto-generated from repository signals. Do not edit manually.

## Project Summary
Repository: `{repo_name}`
Detected languages: {", ".join(languages) if languages else "unknown"}
Detected frameworks/tools — {framework_text}

Inspect the repository before applying its project-specific guidance.

## Repository Map
Top-level directories detected:
{bullet_list(dirs)}

Important files detected:
{bullet_list(files)}

## Setup and Validation Commands
Configuration confirms definitions, not successful execution. Check unverified commands and their working directory before use.

{command_text}

## Change Guidance for Coding Agents
- Before editing, identify whether the task affects backend, frontend, database/schema, Docker/local services, or environment configuration.
- Prefer targeted validation first, then broader checks.
- If unsure which validation command is authoritative, inspect CI workflow files before inventing commands.

Inferred risk-specific guidance:
{change_guidance}

## Inferred Risk Areas
{bullet_list(risks)}

## Safety Boundaries
- Do not commit real secrets, passwords, API keys, database credentials, or production environment values.
- Be careful with authentication, authorization, password reset, JWT, and user-management behavior.
- Avoid broad backend/frontend refactors unless explicitly requested.
- When API contracts change, call out downstream impact clearly.
- Do not run database migrations automatically.
- If unsure which validation command is authoritative, inspect CI workflow files before inventing commands.

## PR Checklist for Agents
Before finalizing a change, include:
- Summary of what changed.
- Backend/frontend/database/config impact.
- Files or subsystems touched.
- Tests or checks run.
- Any API/schema compatibility concerns.
- Any security or environment variable implications.
"""
    return md


def classify_task(task, profile):
    text = task.lower()
    if re.search(r"\b(?:maybe|perhaps|unknown|unsure|unclear|general|investigate)\b", text):
        return ["general"]
    keywords = {
        "backend": r"\b(?:backend|server|api|endpoint|route|handler|fastapi)\b",
        "frontend": r"\b(?:frontend|ui|browser|component|styling|css|react|typescript)\b",
        "database": r"\b(?:database|migration|migrations|alembic|sql|schema|model)\b",
        "security": r"\b(?:auth|authentication|authorization|security|login|password|jwt|permissions)\b",
        "docker": r"\b(?:docker|compose|container|deployment|deploy|hosting)\b",
        "testing": r"\b(?:test|tests|testing|pytest|coverage)\b",
    }
    areas = [area for area, pattern in keywords.items() if re.search(pattern, text)]
    if "backend" in areas and re.search(r"\b(?:api|endpoint|route)\b", text) and re.search(r"\b(?:schema|model|contract|response|endpoint|route)\b", text):
        if "frontend" in profile.get("top_level_dirs", []) or "backend_frontend_api_contract_drift" in profile.get("inferred_risks", []):
            if "frontend" not in areas:
                areas.append("frontend")
    return sorted(areas) if areas else ["general"]


def select_task_instructions(profile, task):
    areas = classify_task(task, profile)
    evidence = profile.get("evidence")
    if "general" in areas or not isinstance(evidence, dict) or any(area in areas for area in ("database", "security", "docker", "testing")):
        return generate_agents_md(profile)

    selected = copy.deepcopy(profile)
    command_items = selected["evidence"].get("commands", [])
    kept = []
    for item in command_items:
        directory = item.get("working_directory")
        parts = Path(directory).parts if isinstance(directory, str) else ()
        component = parts[0] if parts and parts[0] in ("backend", "frontend") else None
        key = item.get("key", "")
        local_command = re.fullmatch(r"(?:scripts|tool\.taskipy(?:\.tasks)?)\.(?:dev|preview)", key)
        if item.get("classification") == "verified" and local_command and component and component not in areas:
            continue
        kept.append(item)
    selected["evidence"]["commands"] = kept
    return generate_agents_md(selected)


def instruction_metrics(original, selected):
    original_bytes = len(original.encode("utf-8"))
    selected_bytes = len(selected.encode("utf-8"))
    return {
        "original_bytes": original_bytes,
        "selected_bytes": selected_bytes,
        "original_words": len(original.split()),
        "selected_words": len(selected.split()),
        "reduction_percent": round((original_bytes - selected_bytes) / original_bytes * 100, 2) if original_bytes else 0.0,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--task")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.validate and args.repo is None:
        parser.error("--validate requires --repo")
    if args.output is not None and args.task is None:
        parser.error("--output requires --task")

    profile_path = Path("outputs/repo_profile.json")
    profile = json.loads(profile_path.read_text())

    md = generate_agents_md(profile)

    if args.task is not None:
        import sys

        selected = select_task_instructions(profile, args.task)
        if args.validate:
            if __package__:
                from .validate_instructions import validate_instructions
            else:
                from validate_instructions import validate_instructions
            findings = {"full": validate_instructions(md, args.repo, profile), "selected": validate_instructions(selected, args.repo, profile)}
        if args.output is not None:
            if args.output.resolve() == Path("outputs/generated_AGENTS.md").resolve():
                parser.error("--output must not be the full generated AGENTS.md")
            try:
                with args.output.open("x", encoding="utf-8") as f:
                    f.write(selected)
            except FileExistsError:
                parser.error("--output must not already exist")
        print(selected, end="")
        print(json.dumps(instruction_metrics(md, selected), indent=2), file=sys.stderr)
        if args.validate:
            print("Validation findings (full and selected):", file=sys.stderr)
            print(json.dumps(findings, indent=2), file=sys.stderr)
        else:
            print("Validation not run; use --validate --repo to review findings.", file=sys.stderr)
    else:
        output_path = Path("outputs/generated_AGENTS.md")
        output_path.write_text(md)

        print(md)
        print(f"\nWrote {output_path}")
        if args.validate:
            if __package__:
                from .validate_instructions import validate_instructions
            else:
                from validate_instructions import validate_instructions
            print("\nValidation findings:")
            print(json.dumps(validate_instructions(md, args.repo, profile), indent=2))
