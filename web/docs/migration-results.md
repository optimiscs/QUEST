# Local migration validation

Validated against the active workspace sources during this migration. This record describes a local migration, not a production deployment benchmark.

- Imported all 34 source packages (32 listed runs plus the two default language variants), with no import errors.
- Reconciled 892 stored trajectories without body mismatches. The active BrowseComp publisher had advanced beyond the imported source checkpoint during reconciliation; for that run, each stored body was checked against its imported content hash. Other unchanged source packages were compared directly with the database bodies.
- Verified escaped U+0000 tool output round-trips without loss.
- PostgreSQL integration tests cover summary/detail separation, ETags, export equality, idempotency, rollback, reordering, deletion, stopped/unscored counters and source path containment.
- Browser tests cover selective detail fetching, bounded-cache reuse, search, expansion, back navigation, language links, request failure, non-current task refresh and direct links above trace 99.
- Desktop/mobile trajectory/overview screenshots match synthetic pre-migration baselines within the configured 0.1% pixel tolerance. An additional local comparison against the original viewer using its default real data also passed before retiring its sources.

## One local browser performance sample

Measured in headless Chromium on the same machine as the API, without network throttling. These are single samples, not percentile or Internet latency claims.

| Scenario | Time from navigation to visible events | Compressed detail response |
|---|---:|---:|
| Default run, first trajectory | 347 ms | 15,903 bytes |
| BrowseComp trace-245 | 1,603 ms | 3,926,589 bytes |

The selected large trajectory decoded to 12,865,471 bytes. The browser fetched two summary pages and that one detail, rather than the roughly 403 MiB run package observed during initial analysis. It initially hydrated zero event bodies into DOM. The workspace-status request took approximately 10 ms in the same sample.

Reproduce using `frontend/tests/performance/benchmark.mjs`; machine-readable local results are in `workspace/viewer/performance.json`. Raw verification and source-import reports are in `workspace/viewer/verification.json` and `workspace/viewer/import-result.json`.

## Runtime

The unified FastAPI launcher serves the existing localhost port 6080. A separate importer watches source snapshots and updates PostgreSQL. Historical source files and pre-refactor presentation/test sources are preserved under `workspace/viewer/legacy-source/` for local recovery. The original HTTP implementation is preserved as `workspace/viewer/legacy-serve.py`; it is not part of the supported runtime.

Container configuration and CI workflow were added. Docker is not installed on this host, so the container image and Compose lifecycle have not been executed here. PostgreSQL integration, frontend build, API serving and browser tests were executed directly on the host.
