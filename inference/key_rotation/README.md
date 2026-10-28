# Jina and Serper key rotation

The key pool is stored only on the server in `workspace/strict-reproduction/.secrets/api_key_pool.json`, mode `600`. The key index and exhausted flags are shared between processes using a locked state file in the same directory. No secret is included in the state file or the append-only event log at `workspace/logs/key-rotation/events.jsonl`.

New `inference/run_multi_react.py` processes enable the adapter when the pool exists. The independent official DeepResearch Bench evaluator enables the same adapter for each official stage. Previously running processes keep their original environment and code; restart them only when convenient. Other entry points that bypass `run_multi_react.py` must explicitly set `QUEST_KEY_ROTATION=1` and put `inference/key_rotation` from the repository root on `PYTHONPATH` before starting Python. Set `QUEST_KEY_ROTATION=0` to disable automatic installation in the QUEST inference entry point.

The adapter changes only requests to `r.jina.ai` and `google.serper.dev`. It retries the same request using the next key on HTTP 401 or 402, or on 403/429 when the response explicitly describes exhausted quota, credits or balance. A normal rate-limit response, network failure, website error or 5xx is not treated as permanent key exhaustion. If all keys fail, the final error is returned rather than inventing a successful result. No benchmark prompt, official source file, query, or response is rewritten.

The pool's exhausted flags persist. If a previously exhausted key is replenished, review the state under the lock before making it eligible again; do not delete historical results or logs.

### Configurable paths

Set `QUEST_KEY_ROTATION=0` to disable the adapter. `QUEST_KEY_POOL_DIR` changes the secrets directory; `QUEST_KEY_POOL_FILE`, `QUEST_KEY_STATE_FILE`, `QUEST_KEY_LOCK_FILE`, and `QUEST_KEY_AUDIT_DIR` override individual locations. Default pool, state, and lock filenames are `api_key_pool.json`, `key_rotation_state.json`, and `key_rotation.lock`; set the environment variables explicitly for a different pool. Historic audit logs are retained in their original experiment directory. Keep pool and state files private, never commit credentials or state, and use separate state/lock files when pools differ.

The adapter checks the HTTP call signatures before patching and its offline
behavior can be checked with `python inference/key_rotation/test_rotation.py`.
Python may report and ignore exceptions raised while importing `sitecustomize`,
so a startup warning is not a fail-closed guarantee; verify the audit events for
the actual process. The patch remains process-wide and only covers the explicitly
matched hosts and HTTP clients.
