#!/usr/bin/env python3
"""Stable launch entrypoint for the FastAPI viewer. Never reads trajectory JSON."""

import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=6080)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    python = Path(os.environ.get("VIEWER_PYTHON", repo / "workspace/viewer/venv/bin/python"))
    if not python.is_file():
        parser.error("Backend environment missing. Run `make -C web setup migrate build import` first.")
    os.execv(
        str(python),
        [
            str(python),
            "-m",
            "uvicorn",
            "quest_viewer.app:create_app",
            "--factory",
            "--host",
            args.host,
            "--port",
            str(args.port),
        ],
    )


if __name__ == "__main__":
    main()
