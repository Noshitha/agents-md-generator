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


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--repo", type=Path)
    args = parser.parse_args()
    if args.validate and args.repo is None:
        parser.error("--validate requires --repo")

    profile_path = Path("outputs/repo_profile.json")
    profile = json.loads(profile_path.read_text())

    md = generate_agents_md(profile)

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