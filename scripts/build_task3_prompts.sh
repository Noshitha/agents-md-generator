#!/bin/bash

## Baseline Agents.md
python src/build_eval_prompt.py \
  --task eval/runs/task3/prompt.md \
  --agents outputs/baseline_AGENTS.md \
  --out eval/runs/task3/baseline_prompt.md

## Generated Agents.md
python src/build_eval_prompt.py \
  --task eval/runs/task3/prompt.md \
  --agents outputs/generated_AGENTS.md \
  --out eval/runs/task3/generated_prompt.md
