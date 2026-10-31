"""Flag exact repeated tool arguments; do not delete recovery attempts."""
import argparse
import collections
import json
from pathlib import Path

import pyarrow.parquet as pq

from audit_full_trajectories import BLOCK, DATASETS, ROOT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-dir", type=Path, required=True)
    args = parser.parse_args()
    directory = args.audit_dir.resolve(strict=True)
    out = directory / "redundancy-flags.jsonl"
    report = directory / "checks-redundancy.json"
    if out.exists() or report.exists():
        raise SystemExit("Refusing to overwrite an existing audit")
    counts = collections.defaultdict(collections.Counter)
    with (directory / "row-manifest.jsonl").open() as manifest, out.open("x") as dest:
        for dataset in DATASETS:
            for path in sorted((ROOT / "workspace/datasets" / dataset / "data").glob("*.parquet")):
                index = 0
                for batch in pq.ParquetFile(path).iter_batches(batch_size=32, columns=["messages"]):
                    for row in batch.to_pylist():
                        meta = json.loads(next(manifest))
                        if (meta["dataset"], meta["file"], meta["row"]) != (dataset, path.name, index):
                            raise RuntimeError("Manifest/source ordering mismatch")
                        index += 1
                        if meta["decision"] != "kept":
                            continue
                        actions, urls, queries = [], [], []
                        for message in row.get("messages") or []:
                            if message.get("role") != "assistant" or not isinstance(message.get("content"), str):
                                continue
                            for match in BLOCK.finditer(message["content"]):
                                raw = match.group(1).strip()
                                if not raw.startswith("{"):
                                    continue
                                try:
                                    obj = json.loads(raw)
                                except ValueError:
                                    continue
                                if not isinstance(obj, dict) or not isinstance(obj.get("arguments"), dict):
                                    continue
                                name = str(obj.get("name", "")).lower()
                                arguments = obj["arguments"]
                                actions.append(name + ":" + json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
                                for key, target in (("url", urls), ("query", queries)):
                                    vals = arguments.get(key, [])
                                    vals = [vals] if isinstance(vals, str) else vals if isinstance(vals, list) else []
                                    target.extend(" ".join(value.split()).casefold() if key == "query" else value.strip() for value in vals if isinstance(value, str))
                        extra_actions = len(actions) - len(set(actions))
                        extra_urls = len(urls) - len(set(urls))
                        extra_queries = len(queries) - len(set(queries))
                        c = counts[dataset]
                        c["rows"] += 1
                        c["rows_with_repeated_action"] += extra_actions > 0
                        c["rows_with_repeated_url"] += extra_urls > 0
                        c["rows_with_repeated_query"] += extra_queries > 0
                        c["rows_with_three_plus_same_url"] += any(v >= 3 for v in collections.Counter(urls).values())
                        if extra_actions or extra_urls or extra_queries:
                            dest.write(json.dumps({"dataset": dataset, "file": path.name, "row": meta["row"], "extra_actions": extra_actions, "extra_urls": extra_urls, "extra_queries": extra_queries}) + "\n")
        if next(manifest, None) is not None:
            raise RuntimeError("Unconsumed manifest rows")
    result = {"counts": {k: dict(v) for k, v in counts.items()}, "note": "Diagnostics only: repeated calls may be valid retries or different goals; no rows were rejected. Only parsed JSON blocks were counted."}
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
