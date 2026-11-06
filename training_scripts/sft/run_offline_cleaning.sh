#!/usr/bin/env bash
# Usage: bash training_scripts/sft/run_offline_cleaning.sh /absolute/new-output
# CPU only: no page fetching, embedding service, judge, or training launch.
set -euo pipefail
quest_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
quest_python=${QUEST_CLEANING_PYTHON:-"$quest_root/workspace/env/bin/python"}
quest_arrow_site=${QUEST_CLEANING_ARROW_SITE:-"$quest_root/workspace/envs/llamafactory-v095-qlora/lib/python3.12/site-packages"}
quest_output=${1:?Provide a NEW output directory}
"$quest_python" -u - "$quest_root" "$quest_output" "$quest_arrow_site" <<'PY'
import importlib.metadata
import json
from pathlib import Path
import runpy
import sys

root, output, arrow_site = sys.argv[1:]
output = Path(output).resolve()
if output.exists():
    raise SystemExit("Refusing to overwrite prior cleaning artifacts")
try:
    import pyarrow
except ModuleNotFoundError:
    # Append, rather than override the active environment's dependency versions.
    sys.path.append(arrow_site)
    import pyarrow
runtime = {"python": sys.executable, "python_version": sys.version,
           "pyarrow_path": pyarrow.__file__,
           "packages": {name: importlib.metadata.version(name)
                        for name in ("pyarrow", "jsonschema", "requests", "tiktoken", "rank-bm25")}}
scripts = Path(root) / "training_scripts/sft"
sys.argv = ["clean_harness_trajectories.py", "--output", str(output)]
runpy.run_path(str(scripts / sys.argv[0]), run_name="__main__")
(output / "runtime.json").write_text(json.dumps(runtime, indent=2) + "\n")
sys.argv = ["prepare_cleaning_evidence.py", "--prepared", str(output), "--output", str(output / "offline")]
runpy.run_path(str(scripts / sys.argv[0]), run_name="__main__")
PY
