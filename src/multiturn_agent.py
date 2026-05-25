"""
Multi-turn coding agent using GPT-4o function calling.

Simulates a realistic coding agent that:
  - reads real files from the target repo
  - captures file writes (not applied — sandbox mode)
  - simulates command execution (valid cmds succeed, hallucinated ones fail)
  - records a full step-by-step trace for metric extraction
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import time
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI

REPO_ROOT = (
    pathlib.Path(__file__).parent.parent
    / "target_repos"
    / "full-stack-fastapi-template"
)

# ─────────────────────────────────────────────────────────────────
# Command simulator
# ─────────────────────────────────────────────────────────────────

# (regex, simulated stdout)
# Ordered from most-specific to least-specific.
_KNOWN_CMD_PATTERNS: list[tuple[str, str]] = [
    (
        r"docker\s+compose\s+exec\s+backend\s+pytest",
        "===== 23 passed in 2.31s =====",
    ),
    (
        r"docker\s+compose\s+exec\s+backend\s+alembic\s+revision.*--autogenerate",
        "Generating /app/alembic/versions/a1b2c3_add_category.py ... done\nNew revision: a1b2c3",
    ),
    (
        r"docker\s+compose\s+exec\s+backend\s+alembic\s+upgrade\s+head",
        "INFO  [alembic.runtime.migration] Running upgrade -> a1b2c3, add category to item\nINFO  [alembic.runtime.migration] Database is now at head (a1b2c3).",
    ),
    (
        r"docker\s+compose\s+exec\s+backend\s+alembic",
        "Alembic command executed.",
    ),
    (
        r"docker\s+compose\s+exec\s+backend\s+ruff",
        "All checks passed.",
    ),
    (
        r"docker\s+compose\s+exec\s+backend\s+mypy",
        "Success: no issues found in 15 source files",
    ),
    (
        r"docker\s+compose\s+exec\s+backend",
        "Command executed in backend container.",
    ),
    (
        r"docker\s+compose\s+exec\s+frontend",
        "Command executed in frontend container.",
    ),
    (
        r"docker\s+compose\s+up",
        (
            "[+] Running 4/4\n"
            " ✔ Container db       Started\n"
            " ✔ Container backend  Started\n"
            " ✔ Container frontend Started"
        ),
    ),
    (r"docker\s+compose", "Docker compose command executed."),
    (
        r"(cd\s+frontend\s*&&\s*)?npm\s+run\s+generate-client",
        "> generate-client\n> openapi-ts\nDone! Client updated in src/client/",
    ),
    (r"npm\s+run\s+(dev|build|lint|preview)", "Script executed successfully."),
    (r"npm\s+run\s+\w+", "npm script executed."),
    (r"npm\s+(install|ci|i)\b", "added 847 packages in 12s"),
    (r"npm\s+", "npm command executed."),
    (r"pytest(\s|$)", "===== 23 passed in 2.31s ====="),
    (r"ruff\s+(check|format)", "All checks passed."),
    (r"mypy\s+", "Success: no issues found."),
    (r"alembic\s+revision", "Generating /app/alembic/versions/a1b2c3_add_category.py ... done\nNew revision: a1b2c3"),
    (r"alembic\s+upgrade", "INFO  [alembic.runtime.migration] Running upgrade -> a1b2c3, add category\nINFO  Database is now at head (a1b2c3)."),
    (r"alembic\s+", "Alembic command executed."),
    (r"python(\s|$)", "Python command executed."),
    (r"pip\s+(install|show|list)", "Package operation completed."),
    (r"git\s+", "Git command executed."),
    # shell builtins — just succeed silently
    (r"^(cd|ls|cat|echo|mkdir|cp|mv|rm|find|grep|head|tail|pwd|export|source)\b", ""),
]


def simulate_command(command: str) -> tuple[str, bool]:
    """Return (stdout, is_valid). is_valid=False → hallucinated command."""
    cmd = command.strip()
    for pattern, output in _KNOWN_CMD_PATTERNS:
        if re.search(pattern, cmd, re.IGNORECASE):
            return output or "(no output)", True
    first = cmd.split()[0] if cmd.split() else cmd
    return f"bash: {first}: command not found", False


# ─────────────────────────────────────────────────────────────────
# OpenAI tool schemas
# ─────────────────────────────────────────────────────────────────

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read the contents of a file in the repository. "
                "Always read files before modifying them."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path relative to repo root, e.g. 'backend/app/models.py'",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file (creates or overwrites). Use for code changes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path relative to repo root",
                    },
                    "content": {
                        "type": "string",
                        "description": "Complete file content to write",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Execute a shell command (tests, alembic migrations, npm scripts, etc.)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute",
                    }
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List the contents of a directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path relative to repo root",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "complete_task",
            "description": (
                "Call this when the task is fully implemented, validated, and ready. "
                "Provide a summary of all changes made and verification steps taken."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Summary of changes and validation steps",
                    }
                },
                "required": ["summary"],
            },
        },
    },
]


# ─────────────────────────────────────────────────────────────────
# Trace data structure
# ─────────────────────────────────────────────────────────────────


@dataclass
class AgentTrace:
    steps: list[dict] = field(default_factory=list)
    written_files: dict[str, str] = field(default_factory=dict)
    commands_run: list[str] = field(default_factory=list)
    hallucinated_commands: list[str] = field(default_factory=list)
    task_completed: bool = False
    completion_summary: str = ""
    terminated_by: str = "max_steps"  # complete_task | max_steps | loop | error | no_tool_call
    loop_detected: bool = False
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    latency_seconds: float = 0.0
    estimated_cost_usd: float = 0.0


# ─────────────────────────────────────────────────────────────────
# Agent
# ─────────────────────────────────────────────────────────────────


class MultiTurnAgent:
    def __init__(
        self,
        client: OpenAI,
        model: str,
        task: str,
        agents_md: str | None = None,
        skills_md: str | None = None,
        repo_root: pathlib.Path = REPO_ROOT,
        max_steps: int = 25,
        input_price_per_1m: float = 2.50,
        output_price_per_1m: float = 10.00,
        verbose: bool = False,
    ):
        self.client = client
        self.model = model
        self.task = task
        self.agents_md = agents_md
        self.skills_md = skills_md
        self.repo_root = repo_root
        self.max_steps = max_steps
        self.input_price = input_price_per_1m
        self.output_price = output_price_per_1m
        self.verbose = verbose

    # ── System message ─────────────────────────────────────────

    def _system(self) -> str:
        parts = [
            "You are an expert full-stack developer working on the "
            "full-stack-fastapi-template repository "
            "(FastAPI + PostgreSQL + SQLModel + Alembic backend; "
            "React + TypeScript + Vite frontend).",
            "",
            "Use the available tools to implement the requested task step by step:",
            "  1. Read relevant files before changing them",
            "  2. Write all necessary code changes (write_file)",
            "  3. Run: alembic revision --autogenerate, then alembic upgrade head",
            "  4. Regenerate the frontend TypeScript client",
            "  5. Run tests to verify",
            "  6. Call complete_task — you MUST call this when done. Do not loop.",
            "",
            "IMPORTANT: Once you have written the files, run migrations, regenerated "
            "the client, and run tests — call complete_task immediately. "
            "Do not repeat commands you have already run successfully.",
            "",
            "Use paths relative to the repository root "
            "(e.g. 'backend/app/models.py', not '/app/models.py').",
        ]
        if self.agents_md:
            parts += ["", "---", "## AGENTS.md", "", self.agents_md]
        if self.skills_md:
            parts += ["", "---", "## SKILLS.md", "", self.skills_md]
        return "\n".join(parts)

    # ── Tool execution ─────────────────────────────────────────

    def _execute(self, name: str, args: dict, trace: AgentTrace) -> str:
        if name == "read_file":
            path = args.get("path", "").lstrip("/")
            full = self.repo_root / path
            if full.exists() and full.is_file():
                return full.read_text(errors="replace")[:8000]
            return f"Error: file not found: {path}"

        elif name == "write_file":
            path = args.get("path", "").lstrip("/")
            content = args.get("content", "")
            trace.written_files[path] = content
            return f"Written: {path} ({len(content)} chars)"

        elif name == "run_command":
            cmd = args.get("command", "")
            trace.commands_run.append(cmd)
            output, valid = simulate_command(cmd)
            if not valid:
                trace.hallucinated_commands.append(cmd)
            # Side-effect: alembic revision creates a migration file
            if re.search(r"alembic\s+revision.*--autogenerate", cmd, re.IGNORECASE):
                migration_path = "backend/alembic/versions/a1b2c3_add_category.py"
                if migration_path not in trace.written_files:
                    trace.written_files[migration_path] = (
                        '"""Add category to item\n\nRevision ID: a1b2c3\n"""\n'
                        "from alembic import op\nimport sqlalchemy as sa\n\n"
                        "def upgrade():\n    op.add_column('item', sa.Column('category', sa.String(), nullable=True))\n"
                        "def downgrade():\n    op.drop_column('item', 'category')\n"
                    )
            return output

        elif name == "list_directory":
            path = args.get("path", "").lstrip("/")
            full = self.repo_root / path
            if full.exists() and full.is_dir():
                entries = sorted(full.iterdir())[:60]
                lines = [f"  {'/' if e.is_dir() else ' '} {e.name}" for e in entries]
                return "\n".join(lines)
            return f"Error: directory not found: {path}"

        elif name == "complete_task":
            trace.task_completed = True
            trace.completion_summary = args.get("summary", "")
            trace.terminated_by = "complete_task"
            return "Task marked complete."

        return f"Unknown tool: {name}"

    # ── Loop detection ─────────────────────────────────────────

    def _is_loop(self, trace: AgentTrace) -> bool:
        """Four consecutive identical non-read_file calls → loop."""
        non_reads = [s for s in trace.steps if s["tool"] != "read_file"]
        if len(non_reads) < 4:
            return False
        last4 = non_reads[-4:]
        keys = [
            (s["tool"], json.dumps(s["args"], sort_keys=True)) for s in last4
        ]
        return len(set(keys)) == 1

    # ── Main run ───────────────────────────────────────────────

    def run(self) -> AgentTrace:
        trace = AgentTrace()
        t0 = time.time()

        messages: list[dict] = [
            {"role": "system", "content": self._system()},
            {"role": "user", "content": self.task},
        ]

        for step_num in range(self.max_steps):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=TOOLS,
                    tool_choice="auto",
                    temperature=0.0,
                    max_tokens=1500,
                )
            except Exception as exc:
                trace.terminated_by = "error"
                if self.verbose:
                    print(f"  [step {step_num+1}] API error: {exc}")
                break

            usage = resp.usage
            trace.total_input_tokens += usage.prompt_tokens
            trace.total_output_tokens += usage.completion_tokens

            msg = resp.choices[0].message
            messages.append(msg)

            if not msg.tool_calls:
                trace.terminated_by = "no_tool_call"
                if self.verbose:
                    print(f"  [step {step_num+1}] No tool call — agent finished")
                break

            tool_results: list[dict] = []
            done = False
            for tc in msg.tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}

                result = self._execute(name, args, trace)
                trace.steps.append(
                    {
                        "step": step_num + 1,
                        "tool": name,
                        "args": args,
                        "result_preview": result[:300],
                    }
                )

                if self.verbose:
                    preview = result[:80].replace("\n", "↵")
                    print(f"  [step {step_num+1}] {name}({list(args.keys())}) → {preview!r}")

                tool_results.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": result}
                )

                if name == "complete_task":
                    done = True
                    break

            messages.extend(tool_results)

            if self._is_loop(trace):
                trace.loop_detected = True
                trace.terminated_by = "loop"
                if self.verbose:
                    print(f"  [step {step_num+1}] Loop detected — stopping")
                break

            if done:
                break

        trace.latency_seconds = time.time() - t0
        trace.estimated_cost_usd = (
            trace.total_input_tokens / 1_000_000 * self.input_price
            + trace.total_output_tokens / 1_000_000 * self.output_price
        )
        return trace
