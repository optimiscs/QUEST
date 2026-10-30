import argparse
import json
import logging
import time
from pathlib import Path

from quest_viewer.config import Settings
from quest_viewer.db.session import create_session_factory
from quest_viewer.ingestion.importer import import_site


def main():
    parser = argparse.ArgumentParser(description="Import normalized QUEST packages into PostgreSQL")
    parser.add_argument("command", choices=["import", "watch"])
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--interval", type=float, default=10)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.interval < 1:
        parser.error("interval must be at least one second")
    engine, factory = create_session_factory(Settings())
    try:
        while True:
            try:
                result = import_site(factory, args.site, args.force)
                print(json.dumps(result, ensure_ascii=False), flush=True)
                if args.command == "import":
                    raise SystemExit(1 if result["errors"] else 0)
            except Exception:
                if args.command == "import":
                    raise
                logging.exception("Import cycle failed; keeping last committed snapshots")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        engine.dispose()
