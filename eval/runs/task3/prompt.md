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
