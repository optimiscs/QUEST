"""Export without a running database. Run with the backend environment."""

import json
from pathlib import Path

from quest_viewer.app import create_app

path = Path(__file__).resolve().parents[1] / "backend/openapi.json"
path.write_text(json.dumps(create_app().openapi(), ensure_ascii=False, indent=2) + "\n")
