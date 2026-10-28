# Dataset-author evaluation integration

The upstream repositories live outside QUEST in `strict-reproduction/official-dataset-eval-20261028/sources`. `run.py` pins their exact Git revisions and refuses modified tracked files. Legacy QUEST evaluators and historical results remain intact and are not read automatically.

* BrowseComp (`652c89d0ca9df547706735883097e9537d40dc47`): blocked. The official grader returns `correct: yes` but the official aggregate compares that to `yes`. The launcher refuses to report misleading accuracy without an approved upstream correction.
* HLE (`22ed3074b1e7b134bcbc09028d0ba320839b0655`): blocked. The official Pydantic structured-output call returns HTTP 400 from the current DeepSeek endpoint. The launcher does not downgrade JSON Schema or alter official code.
* DeepResearch Bench (`f2735b5c3636759c22f9e936c0232de8bf545b67`): `run.py` invokes the unmodified upstream RACE and all FACT modules, using DeepSeek for clean/RACE/FACT and Jina for citation reads. Each run requires a nonexistent output directory under the isolated `runs` root and checks query rows against the pinned official dataset. The source path, input hashes, stage status, and API observation logs are retained. A failed first pilot is preserved under `runs/drbench-case51-smoke`: RACE completed, but FACT Jina requests returned 402 (insufficient account balance) and upstream statistics divided by zero. It was launched before the API observer was installed; it retains stage logs and results, but not complete API request/response traces.

Invoke the DeepResearch Bench path with the project environment:

```
env/bin/python QUEST/evaluation/official_dataset/run.py drbench \
  --raw /absolute/path/to/quest-converted.jsonl \
  --query /absolute/path/to/matching-official-queries.jsonl \
  --out /root/autodl-tmp/Quest/quest4b-gaia-20261027/strict-reproduction/official-dataset-eval-20261028/runs/NEW_RUN \
  --workers 1
```

The raw rows must contain `id`, `prompt`, and `article`; query rows must be byte-content-equivalent JSON records from the pinned official `data/prompt_data/query.jsonl`. The private API configuration must be present on the server. No historical result or cache is reused automatically. RACE output is incomplete as an official DRBench evaluation without FACT; each run must be audited before using its score.

* GAIA: `gaia.py` imports `question_scorer` directly from the unmodified upstream leaderboard checkout at `strict-reproduction/official-sources/gaia-leaderboard`, pinned to `9f133d71362e77b3539f1514f31b9c101a545fec`. The official scorer is deterministic and uses no judge model. DeepSeek judging, if performed, is a separate auxiliary result and must not be called the official GAIA score. Supply explicit, freshly prepared task-id/model-answer JSONL and an explicit reference JSON array; the wrapper never automatically discovers historical results. It rejects empty answers and duplicate or unknown IDs, records source and input hashes, and requires a new output directory. Input answer extraction, reference provenance, completeness, and contamination must be audited independently.

* Optional GAIA generation formatting: `run_gaia_prompt.py --gaia-format -- <run_multi_react.py arguments>` adds the GAIA concise-answer instruction before QUEST's date marker, retaining `<answer>` tags. The wrapper creates a temporary prompt variable and uses QUEST's existing `SYSTEM_PROMPT_NAME` selection; it does not modify upstream inference source. Omit `--gaia-format` to run with the existing prompt. `--check` checks wiring without inference. This is GAIA-adapted QUEST prompting, not the exact official GAIA system prompt, and changes comparability with earlier runs. Use the same setting for both models. It applies only to new processes started through this wrapper; resumed saved messages or other wrappers that clear `SYSTEM_PROMPT_NAME` will not acquire it. Use separate run directories and record prompt hashes.

> The BrowseComp and HLE notes above describe this launcher and its original unmodified-source configuration. Later smoke experiments used separately stored, explicitly patched upstream copies and must not be interpreted as results from this launcher or as aggregate benchmark scores. No historical outputs are modified by this integration.
