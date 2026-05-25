You are a coding agent working inside the repository `fastapi/full-stack-fastapi-template`.

Use the following AGENTS.md instructions:

# AGENTS.md
> Auto-generated from repository signals. Do not edit manually.

## Project Summary
Repository: `full-stack-fastapi-template`
Detected languages: docker, python, typescript
Detected frameworks/tools: fastapi, react, sqlmodel, vite

This appears to be a full-stack application with repo-specific boundaries between backend, frontend, Docker/local services, and environment configuration.

## Repository Map
Top-level directories detected:
- `.copier`
- `.vscode`
- `backend`
- `frontend`
- `hooks`
- `img`
- `scripts`

Important files detected:
- `README.md`
- `compose.yml`
- `compose.override.yml`
- `pyproject.toml`
- `package.json`
- `.env`
- `.github/workflows`

## Setup and Validation Commands
Before making changes, use only these commands. Do not invent alternatives.

Backend-related commands:
- `python -c "import secrets; print(secrets.token_urlsafe(32))"`
- `pip install copier`

Frontend-related commands:
- `npm run lint`
- `npm run preview`
- `npm run test:ui`
- `npm run generate-client`
- `npm run test`
- `npm run dev`
- `npm run build`

Docker/local-service commands:
- `docker compose logs`
- `docker compose up -d`
- `docker compose down`

Lint/check commands (from pyproject.toml):
- `ruff check .`

## Change Guidance for Coding Agents
- Before editing, identify whether the task affects backend, frontend, database/schema, Docker/local services, or environment configuration.
- Prefer targeted validation first, then broader checks.
- If unsure which validation command is authoritative, inspect CI workflow files before inventing commands.

Inferred risk-specific guidance:
- For backend API changes, check whether frontend API clients, schemas, or user-facing behavior also need updates. Run `npm run generate-client` after any route or model change.
- For database/model changes, verify schema compatibility and whether migrations or fixture updates are needed.
- For environment/config changes, update example configuration files and documentation. Never hardcode credentials.
- Local development requires Docker services running. Use `docker compose up -d` before starting backend or frontend.
- Auth, JWT, and password flows are security-sensitive. Avoid refactoring these unless explicitly instructed.

## Inferred Risk Areas
- `backend_frontend_api_contract_drift`
- `database_model_or_schema_change`
- `secrets_or_environment_config`
- `local_service_dependency_docker`
- `auth_or_backend_security_sensitive_change`

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

Task:

# Task 3: Database Model Change

Add an `updated_at` timestamp field to the `Item` SQLModel so that it is automatically
set to the current UTC time whenever a record is updated. The field should also be exposed
in the `ItemPublic` response schema.

Before editing, identify which files and subsystems are affected. Then produce a minimal
implementation plan.

Please:
1. Identify the files/subsystems likely affected.
2. Produce a minimal implementation plan.
3. List validation commands/checks you would run.
4. Mention any risks or assumptions.
Do not make changes yet.

Please:
1. Identify the files/subsystems likely affected.
2. Produce a minimal implementation plan.
3. List validation commands/checks you would run.
4. Mention any risks or assumptions.
Do not make changes yet.
