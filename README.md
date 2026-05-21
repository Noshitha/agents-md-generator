# Faros AGENTS.md Generator

This project explores how to automatically infer repo-aware coding-agent instructions from a GitHub repository.

The pipeline is:

```text
GitHub repo
  -> repo analyzer
  -> repo_profile.json
  -> generated AGENTS.md
  -> baseline vs generated evaluation
