# Operations

## Deployment

Run PostgreSQL and the API on private interfaces. The API remains bound to localhost by the local launcher and Compose port mapping. `ssh-viewer.sh` starts the unified launcher and forwards the viewer port. It checks `/api/v1/health/ready`; `/api/v1/health/live` checks the process independently of the database.

For containers, set `POSTGRES_PASSWORD` and `VIEWER_SOURCE_ROOT` (absolute path of the legacy `web` input directory), then run:

```bash
docker compose -f web/deploy/compose.yaml up --build -d
```

The deployment uses one application image containing the built frontend, API and importer. Migrations run as a one-shot service before the API/importer start. PostgreSQL has a persistent volume. Gzip is handled by the API, including local runs, so an additional proxy service is unnecessary for the current private deployment. Use a URL-safe database password in Compose's interpolated URL; custom deployments can provide an explicitly encoded connection URL.

Configuration: `VIEWER_DATABASE_URL`, `VIEWER_FRONTEND_DIR`, `VIEWER_POOL_SIZE`. Credentials belong in the deployment environment, never in source. Each process has its own bounded connection pool; account for API and importer pools when configuring database connections. SQL parameters are omitted from database exception logging.

## Updating

1. Back up PostgreSQL and retain the previous application image/build.
2. Install locked dependencies, build the frontend and run checks.
3. Run `alembic upgrade head` once before starting the new API/importer.
4. Check readiness, a summary page, a complete trace, export and report pages.

The importer is an independent foreground process (`make -C web watch`); use Compose or the host's service manager to supervise it. Import failures retain committed snapshots and are reported in logs. A local `nohup` process is convenient for this workspace, not a substitute for a deployment supervisor.

## Backup and restore

Use PostgreSQL custom-format dumps, for example `pg_dump -Fc -d "$PGDATABASE" -f viewer.dump`, with connection settings supplied using PostgreSQL's standard environment variables or a protected service file. Do not pass the SQLAlchemy `postgresql+psycopg://` URL directly to PostgreSQL CLI tools.

Restore into a separate empty database with `pg_restore --exit-on-error --no-owner -d "$PGDATABASE" viewer.dump`. Check the Alembic revision, API readiness and a source/body reconciliation before switching the application connection. Run restore drills when changing the backup or deployment procedure. Raw evaluation sources remain independent archival inputs.

## Rollback

Switch the connection/build back to a validated previous version. Schema downgrades require an explicit compatibility review; the JSON-to-JSONB downgrade deliberately fails on U+0000-containing bodies instead of discarding data. Migration 0003 is backward compatible with the initial API. Keep raw source packages; they allow rebuilding a fresh database through the importer.

The legacy HTTP server is retired. For an emergency pre-migration rollback, restore the prior Web implementation from the task's preserved source snapshot or repository revision as a whole; do not run a second permanently supported frontend in parallel.

## Local migration record

The workspace PostgreSQL cluster was created for this migration. Its data directory is `workspace/viewer/postgres` on the data volume; the Ubuntu cluster configuration remains under `/etc/postgresql/14/main`. The system disk lacked room for database and browser artifacts, so those artifacts were placed on the data volume. The postgres OS user has traversal permission on `/root` to reach its dedicated data directory.

Browser binaries, temporary browser files, logs and migration verification results are in `workspace/viewer/`. These host-specific settings are not requirements for a fresh container deployment.
