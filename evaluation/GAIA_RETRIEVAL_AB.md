# GAIA32 retrieval experiment

The first phase runs the current Flash webpage-summary baseline and five
retrievers that deliver evidence directly to 4B: BM25, Qwen3-Embedding-8B,
BM25 + Qwen3-Reranker-8B, hybrid BM25 + embedding, and hybrid + reranker.
The optional Flash-summary phase is conditional on the direct-input results.

The comparison page is `/gaia-retrieval-comparison.html`. Its per-case table
shows missing or invalid evaluations separately. Evidence returned to the
agent, as well as the original reader output, is available in the trace data.
`gaia-retrieval-ab-metrics.json` stores latency, usage, and paired comparisons.
Summary and memory API usage are distinct; missing usage is not zero usage.

## Important comparability limits

* Complete agent trajectories can issue different searches and see changing
  external pages. Current experimental runs deliberately bypass the existing
  summary cache to prevent cross-group contamination. They do **not** yet
  share a frozen search/reader snapshot, so answer comparisons measure the
  whole live system, not an isolated retrieval-method effect.
* BM25 splits Markdown tables with repeated headers. Large individual rows
  are never cut by the packer. Short pages bypass filtering. A no-match BM25
  query uses a budgeted source-order fallback, recorded in the audit.
* Each group uses its own search and visit cache. The audit log holds sensitive
  webpage contents; do not publish it to external services without review.
* The baseline uses its existing Flash settings. If triggered, experimental
  Flash summaries request thinking disabled. This is an intentional latency
  optimization but also changes a variable in the baseline comparison.
* The official scorer requires an explicit answer; errors, incomplete runs,
  and samples marked for retry are excluded from score and paired statistics.
  A small or non-significant difference does not establish equivalence.

## Runtime and recovery

The control process and 4B services are independent. The 8B model servers
start only when all shards in their local snapshot exist, one GPU each.
Investigate server health and logs before restarting a job. Retry status is
recorded in `checks/retry-required.json`; completed retries replace the
affected case in the viewer while preserving the original trajectory.

The controller currently keeps its in-memory initial score for a case that
was rerun separately. Consequently, its automatic optional-summary decision
must be **rechecked using the completed retry manifest and paired results**;
do not regard `decision.json` alone as authoritative when retries exist.
The running original controller is followed by
`inference/scripts/resume_gaia_retrieval_after_controller.py`, which waits
for its lock, schedules retries for recorded retrieval-service read timeouts
and samples with no official score,
and resumes the updated decision logic once those retries are scored. The
comparison metrics exclude detected timeouts immediately. A failed retry
leaves the decision pending for investigation. New agents allow for a long
queue at the shared 8B service; agents that were already running retain the
old timeout and are the ones that may need to be rerun.

During the run the user requested moving both Qwen3 8B retrieval models to
vLLM with 16 maximum concurrent sequences. GPU 3 serves the embedding model
and GPU 4 serves the reranker; the scoring adapter retains the experiment's
existing API. The 4B phase is limited to 8 tasks per GPU. Cases in flight
during the backend cutover are marked for retry. Earlier retrieval timing
includes the Transformers backend, so aggregate latency across the cutover
is not a clean benchmark of either backend. The preflight file records scores
from both backends for the same real-page sample, not answer-quality proof.

When the experiment is suspended because the Jina pool is unavailable,
replenish or add credentials in the local pool first. With the current
controller PID verified separately, run
`workspace/env/bin/python inference/scripts/restore_gaia_retrieval.py --controller-pid PID`.
The command probes the keys without printing them, reactivates only those
that return HTTP 200, and resumes the suspended children and controller. If
none works it leaves the experiment paused. Reader-failure cases remain
marked for rerun; the original results are not treated as valid comparisons.
