# Objective Verifier Generation

This directory generates executable Python verifier scripts from formatted
objective tasks. It is the bridge between accepted objective tasks and
task-specific verification code.

## Overview

Input files should be formatted objective-task JSON files containing:

```text
proposed_question
rubric_tree_analysis_refined.formatted_tree
```

Typical input comes from the objective task pipeline:

```text
task/obj_task/outputs/objective_trajectories/formatted/refined/
```

If the refined directory does not exist, use the original `formatted/` directory.

## Run Generation

From the repository root:

```bash
python task/obj_eval/obj_eval_generation.py \
  --input /path/to/formatted_tasks \
  --template task/obj_eval/generation_prompt.md \
  --output /path/to/objective_verifiers \
  --model openai/gpt-5 \
  --concurrency 20
```

`--input` can be either a single formatted JSON file or a directory containing
many formatted JSON files.

The generation model can also be configured with:

```text
OBJ_EVAL_MODEL_NAME
```

## Outputs

The output directory contains one verifier script per input task:

```text
tree2py_<input_json_stem>.py
```

If the model response does not contain usable Python code, the raw response is
saved as:

```text
tree2script_formatted_<input_json_stem>_raw.md
```

The generator prints total, success, failed, and token-usage counts at the end
of the run.

## Main Files

| File | Purpose |
| --- | --- |
| `obj_eval_generation.py` | Batch generator for objective verifier scripts |
| `generation_prompt.md` | Prompt template for verifier generation |
| `utils/` | Shared verifier runtime and examples used in the prompt |

## Offline summary structure audit

`summary_audit.py --summary /path/to/summary.json --output /new/audit.json` checks a previously produced verifier summary without running Python from the verifier or contacting a model. A full-credit summary must have a nonempty tree, unique node IDs and consistently passing nodes. The audit records a SHA-256 and never overwrites an existing report.

This is a structural check only: it does not verify that the tree covers the required rubric, that the score was produced by the claimed code, that the execution environment was isolated, or that cited evidence is correct. Its `training_eligible` field is always false. There is currently no validated end-to-end objective verifier execution and SFT acceptance path in this repository; do not treat this audit as one.
