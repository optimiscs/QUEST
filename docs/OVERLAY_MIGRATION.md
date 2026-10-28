# SFT data pipeline overlay migration

This audit compares the archived experimental overlay with the consolidated QUEST
checkout. The overlay was an experiment, not an official source release. Its
patch, archive, failed attempts and traces remain in the private workspace.

- Overlay patch SHA-256: `bd7d8ec4034a16d086e48eb6101859e1356396d8d14b133228e062035adbbe56`.
- Archived overlay SHA-256: `246e629f2c95b8cea7f5073ee1a0b8b754a31c19f7b386ead95c4e0b37c0c61e`.
- Comparison checkout: `d7cca1ab6e5eb3778da348d7e913788c0b761f33`.
- All 17 paths named in the patch are present. Presence and a textual comparison
  do not establish end-to-end functionality.

| Experimental path | Consolidated implementation or intentional difference |
|---|---|
| `inference/react_agent.py` | Opt-in DeepSeek teacher; shared DSML parser preserves non-tool text; API retries, single Python tool insertion and think-external answer extraction are separate additions. |
| `task/obj_eval/obj_eval_generation.py` | DeepSeek request parameters are opt-in via `QUEST_DEEPSEEK_COMPAT`; upstream reasoning settings remain the default. |
| `task/obj_task/generate_tasks.py` | Retains configurable sample count; restores upstream defaults of 20 iterations and 20 workers. |
| `task/obj_task/generation_agent.py` | DeepSeek DSML conversion uses the shared parser when compatibility mode is enabled. |
| `task/obj_task/refine_rubric_trees.py` | DeepSeek thinking parameter is opt-in; otherwise uses the upstream reasoning setting. |
| `task/obj_task/tool_visit.py` | Identical to the archived overlay in this comparison. |
| `task/obj_task/verify_rubric_trees.py` | DeepSeek thinking parameter is opt-in; otherwise uses the upstream setting. |
| `task/open_ended_eval/evaluate_criteria_args_parallel_open_ended.py` | DeepSeek parameters are opt-in. Malformed scores and exhausted retries remain errors instead of being coerced to zero; the guarded scoring wrapper checks full criterion coverage. |
| `task/open_ended_task/generate_longform_tasks.py` | Retains configurable sample count; restores the upstream default of 10 iterations. |
| `task/open_ended_task/generation_agent_longform.py` | DeepSeek DSML conversion uses the shared parser in compatibility mode. |
| `task/open_ended_task/longform_rubric/generate_criteria.py` | DeepSeek parameter is opt-in; otherwise retains the upstream reasoning setting. |
| `task/open_ended_task/polish_answer.py` | Identical to the archived overlay in this comparison. |
| `task/open_ended_task/ref_gen/react_agent_ref_gen.py` | Model and token limit are configurable; shared tool-call parsing is opt-in. The default token limit matches the upstream 40,000 rather than the overlay's 12,000. |
| `task/open_ended_task/ref_gen/run_multi_react_ref_gen.py` | Identical to the archived overlay in this comparison. |
| `task/open_ended_task/ref_gen/tool_search.py` | Identical to the archived overlay in this comparison. |
| `task/open_ended_task/ref_gen/tool_visit.py` | Identical to the archived overlay in this comparison. |
| `task/open_ended_task/tool_visit.py` | Identical to the archived overlay in this comparison. |

The shared parser, strict scoring and provisional-reference tools are in
`contrib/deepseek_data/`. The author scorer changes, local generation settings
and optional prompts are adaptations and must be disclosed for each run.

**Unverified:** executing generated objective verifiers in an isolated runtime,
rubric coverage and provenance, feedback-driven retries, citation backfilling,
and a real task-to-export pipeline. The experimental exporter excludes objective
rows until their verifier execution and provenance can be established. Synthetic
tests are not a completed real generation run. Do not start generation, evaluation
or training merely to reproduce this audit.
