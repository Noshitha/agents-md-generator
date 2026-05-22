import json
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
        "backend_frontend_api_contract_drift": "For backend API changes, check whether frontend API clients, schemas, or user-facing behavior also need updates. Run `npm run generate-client` after any route or model change.",
        "database_model_or_schema_change": "For database/model changes, verify schema compatibility and whether migrations or fixture updates are needed.",
        "secrets_or_environment_config": "For environment/config changes, update example configuration files and documentation. Never hardcode credentials.",
        "local_service_dependency_docker": "Local development requires Docker services running. Use `docker compose up -d` before starting backend or frontend.",
        "auth_or_backend_security_sensitive_change": "Auth, JWT, and password flows are security-sensitive. Avoid refactoring these unless explicitly instructed.",
    }

    guidance_lines = [
        f"- {risk_guidance[r]}"
        for r in risks
        if r in risk_guidance
    ]
    change_guidance = "\n".join(guidance_lines) if guidance_lines else "- No specific risk guidance inferred."

    md = f"""# AGENTS.md
> Auto-generated from repository signals. Do not edit manually.

## Project Summary
Repository: `{repo_name}`
Detected languages: {", ".join(languages) if languages else "unknown"}
Detected frameworks/tools: {", ".join(frameworks) if frameworks else "unknown"}

This appears to be a full-stack application with repo-specific boundaries between backend, frontend, Docker/local services, and environment configuration.

## Repository Map
Top-level directories detected:
{bullet_list(dirs)}

Important files detected:
{bullet_list(files)}

## Setup and Validation Commands
Before making changes, use only these commands. Do not invent alternatives.

Backend-related commands:
{bullet_list(commands.get("backend", []))}

Frontend-related commands:
{bullet_list(commands.get("frontend", []))}

Docker/local-service commands:
{bullet_list(commands.get("docker", []))}

Lint/check commands (from pyproject.toml):
{bullet_list(commands.get("pyproject", []))}

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
    profile_path = Path("outputs/repo_profile.json")
    profile = json.loads(profile_path.read_text())

    md = generate_agents_md(profile)

    output_path = Path("outputs/generated_AGENTS.md")
    output_path.write_text(md)

    print(md)
    print(f"\nWrote {output_path}")