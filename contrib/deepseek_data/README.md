# DeepSeek data-pipeline adapters (experimental)

Opt in with `QUEST_DEEPSEEK_COMPAT=1` for DeepSeek request parameters and DSML normalization in supported generation/evaluation entry points. `QUEST_DEEPSEEK_TEACHER=1` separately selects the DeepSeek teacher in inference. Credentials are supplied through environment variables and are never included in this directory.

`score_openended.py` requires an independently prepared candidate, reference and criteria, and refuses empty or failed reference outputs. `build_openended_ledger.py` checks provenance; `export_sft.py` requires scored examples and applies objective/open-ended thresholds. `deepseek_judge.py` translates structured Pydantic output into validated JSON. These components are not a complete data-generation controller: objective verifier execution, feedback-based retries, citation backfilling and end-to-end export have not been validated. Do not execute generated Python outside an actually isolated sandbox.

The experiment that informed these adapters rejected two objective tasks and retained zero SFT sessions. A reference-agent failure previously yielded a misleading score; failed or missing reference results must never be used as training acceptance.
