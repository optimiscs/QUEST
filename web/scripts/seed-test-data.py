"""Small synthetic fixture for browser tests; never imports private run data."""

import json
import tempfile
from pathlib import Path

from quest_viewer.config import Settings
from quest_viewer.db.session import create_session_factory
from quest_viewer.ingestion.importer import import_run
from sqlalchemy.engine import make_url

package = json.loads((Path(__file__).resolve().parents[1] / "tests/fixtures/viewer.json").read_text())
settings = Settings()
if not (make_url(settings.database_url).database or "").endswith("_test"):
    raise SystemExit("Refusing to seed a database whose name does not end in _test")
engine, factory = create_session_factory(settings)
try:
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "traces.json"
        path.write_text(json.dumps(package))
        for run_id in ["default-en", "default-zh"]:
            import_run(factory, run_id, path, {"id": run_id, "hiddenDefault": True}, 0, force=True)
finally:
    engine.dispose()
