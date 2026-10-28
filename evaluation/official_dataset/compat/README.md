# Dataset-author compatibility copies

These are the five patches used in the earlier individual smoke evaluations. They are **adaptations**, not untouched author implementations. The original, pinned source must be a clean Git checkout. To create a fresh standalone copy:

```bash
workspace/env/bin/python evaluation/official_dataset/compat/materialize.py simple-evals \
  --source workspace/strict-reproduction/official-dataset-eval-20261028/sources/simple-evals \
  --output workspace/compat/simple-evals-new
```

The command checks the commit and tracked-file status, exports only tracked source, checks and applies the corresponding patch, and writes a patch hash manifest. It never edits the upstream checkout or overwrites an existing output. No dataset, credentials, Git metadata, evaluation, or inference is created. An archive is not an initialized upstream checkout and does not include Git submodule content or external datasets.

| Name | Pinned commit | Change and limitations |
|---|---|---|
| `simple-evals` | `652c89d0ca9df547706735883097e9537d40dc47` | BrowseComp extracts the captured yes/no group rather than the full regex match. This is a code correction to the author grader. |
| `hle` | `22ed3074b1e7b134bcbc09028d0ba320839b0655` | DeepSeek JSON mode with local Pydantic validation replaces the unsupported JSON Schema response mode; judge model differs. |
| `widesearch` | `9825ba7b140b71d81b364793f86dabe4cfed6749` | Adds a DeepSeek-compatible client path and treats the unrelated Ark dependency as optional. |
| `mind2web2` | `1fcbfda98bf5c669daa2ed0a27f1d2f2499475ee` | Allows model selection and local schema validation; tall screenshots are split and re-encoded, so inputs can differ. Page evidence, captcha and cache provenance need separate audit. |
| `liveresearchbench` | `ffb27c9d7a091a0b0f10cbcebc061fc3ba025b63` | Uses the authorized Full data and fixed local input, plus DeepSeek JSON/local schema validation. Data access and download are separate requirements. |

The earlier runs were small integration checks, not aggregate benchmark results. Model substitutions, screenshot transformations, author metrics and unscored/failure states must remain explicit when reporting a new run. Historic outputs and requests are preserved under `workspace/strict-reproduction/`; they are not loaded by this materializer.

To verify a copy before use without executing it:

```bash
workspace/env/bin/python evaluation/official_dataset/compat/materialize.py simple-evals \
  --verify-only --output workspace/compat/simple-evals-new
```

The manifest records source file hashes and symlink targets, and verification rejects changed, missing or extra files. Old manifests lack an inventory and must be recreated for this check. This detects accidental drift relative to the local manifest; it does not authenticate a manifest that was itself replaced. Save the manifest hash separately when independent provenance is needed. Runtime caches or datasets should live outside the verified copy.

For an independent comparison with the pinned checkout and repository patch:

```bash
workspace/env/bin/python evaluation/official_dataset/compat/materialize.py simple-evals \
  --verify-against-source \
  --source workspace/strict-reproduction/official-dataset-eval-20261028/sources/simple-evals \
  --output workspace/compat/simple-evals-new
```

This rebuilds a temporary copy and compares its file hashes and symlink targets to the existing copy, detecting even changes accompanied by a rewritten local manifest. It checks the local pinned Git revision and local patch, not their external authenticity, runtime dependencies, or evaluation results. The temporary copy is removed after the check.
