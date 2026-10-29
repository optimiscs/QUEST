# Legacy normalized input packages

This directory is the ingestion boundary for existing evaluation publishers. `data/traces.json` contains the default English run, and `datasets/index.json` lists additional runs. Packages are imported by the standalone PostgreSQL importer; the HTTP service never serves or reads them.

Frontend source now lives in `../frontend/`. Run the application as described in [../README.md](../README.md). The package format remains documented in [SCHEMA.md](SCHEMA.md).
