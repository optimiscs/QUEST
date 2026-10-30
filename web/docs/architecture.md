# Architecture

## Read path

The application is a modular monolith. FastAPI synchronous routes run in its worker thread pool, using synchronous SQLAlchemy/psycopg connections. Database work is never performed on an async request handler's event loop. Each request owns its session; no mutable session is shared between requests.

Read-only route handlers contain the small query compositions they own. Import transactions live in the ingestion service. Additional generic repository/service wrappers are intentionally omitted until there is reusable business behavior to separate.

`GET /api/v1/runs` returns the navigation manifest. `GET /api/v1/runs/{id}` returns metadata, counters and a content revision. `GET /api/v1/runs/{id}/traces` uses cursor pagination (maximum 200 rows) and selects summaries only. The frontend verifies that every page has the same run revision and retries if a publication crosses page requests.

`GET /api/v1/runs/{id}/traces/{trace_id}` returns the entire selected trajectory, including every original event and unknown source field. Details and exports use repeatable-read snapshots. ETag validation avoids transferring unchanged details. Run and trace identifiers are separate: `trace-01` may exist in many runs.

`GET /api/v1/runs/{id}/export` streams the complete source-format package using a server-side cursor, holding only one trajectory at a time. It is an explicit user export, never used by startup, navigation or polling.

`GET /api/v1/reports/{name}` serves imported dashboard documents. Static HTML report routes retain their existing appearance and URLs. The server exposes only built assets and explicit HTML entries, never the source dataset directories.

## Tables

- `runs`: original run object, manifest metadata, envelope fields, counters, content revision, navigation position and listing flag.
- `traces`: composite key `(run_id, id)`, unique `(run_id, position)`, small summary and content revision.
- `trace_payloads`: separate large body, composite foreign key to `traces` with cascading deletion.
- `ingestion_sources`: canonical source path, file revision and last successful import time; committed with the run.
- `reports`: dashboard documents and content revision.

Summaries and structured metadata use JSONB. Opaque trajectory bodies use PostgreSQL JSON because historical tool output includes escaped U+0000, which JSONB rejects. No database-side JSON operations are required on those opaque bodies. This is a deliberate lossless storage boundary, verified by a control-character round-trip test. There is one aggregate payload per trajectory; separate event tables would add joins and write coordination without benefiting the agreed full-trajectory API.

Execution state, original scoring fields and lifecycle display overrides remain distinct. The importer never rewrites raw scores or treats missing scores as failures.

## Publication

The input boundary is the normalized package format described in `trace-viewer/SCHEMA.md`. Existing evaluation publishers write this format; HTTP handlers never inspect it. A standalone importer streams the source, calculates per-trajectory versions, upserts only changed payloads and publishes one run in a transaction. Readers continue using the previous committed snapshot during import.

Per-run PostgreSQL advisory locks serialize competing importers. Position updates, deletions, counters, source checkpoints and versions commit together. Duplicate IDs, empty packages, malformed data and files changed during import reject the transaction. Producers must atomically replace their output files. `generatedAt` alone does not invalidate content versions. Removal from the manifest hides a run while preserving historical direct links and stored data.

The ingestion checkpoint is one complete source snapshot per run. Import retries are idempotent; partial packages are never made visible. Large files are parsed as streams; memory is bounded by the largest trajectory and its serialized representation, not the entire run.

## Frontend

The original visual structure and CSS are retained. Workspaces, timeline, event rendering and overview are separate ES modules. API access, version-aware bounded LRU and Worker search are TypeScript modules. OpenAPI-generated types define the transport contract. The existing presentation code remains native JavaScript, covered by lint, behavior and screenshot tests rather than a cosmetic rewrite with unchecked TypeScript casts.

Selection uses AbortController and a navigation generation to reject obsolete responses. Cached payloads do not enter the summary list. Search text is indexed once per selected trajectory in a Worker, never duplicated into DOM attributes. Details hydrate on expansion. Expand-all yields between small batches. Hidden trajectory tabs defer event rendering until opened.

The existing localStorage key and layout format are preserved. Browser-only folder organization remains browser-only. Large payload caches are limited by encoded JSON byte estimates; that limit is not a measurement of JS heap usage.

Visual tests pin the browser version, viewports, synthetic input and the DejaVu system fallback through `frontend/tests/fontconfig.conf`. The committed baselines were captured from the preserved pre-migration implementation under that same test font configuration; this does not change application fonts in user browsers.
