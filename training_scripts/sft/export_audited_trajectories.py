"""Export only rule-audited records, preserving source schema and row content."""
import argparse
import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from audit_full_trajectories import DATASETS, ROOT, sha_messages


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-dir", type=Path, required=True)
    args = parser.parse_args()
    directory = args.audit_dir.resolve(strict=True)
    report = json.loads((directory / "report.json").read_text())
    output = directory / "rule_filtered"
    output.mkdir(exist_ok=False)
    counts = {}
    total = 0
    with (directory / "row-manifest.jsonl").open() as manifest:
        for dataset in DATASETS:
            counts[dataset] = 0
            dest = output / dataset
            dest.mkdir()
            for path in sorted((ROOT / "workspace/datasets" / dataset / "data").glob("*.parquet")):
                parquet = pq.ParquetFile(path)
                index = 0
                writer = None
                try:
                    for batch in parquet.iter_batches(batch_size=32):
                        kept = []
                        for row in batch.to_pylist():
                            record = json.loads(next(manifest))
                            if (record["dataset"], record["file"], record["row"]) != (dataset, path.name, index):
                                raise RuntimeError("Manifest/source ordering mismatch")
                            if sha_messages(row.get("messages") or []) != record["messages_sha256"]:
                                raise RuntimeError("Source row changed after audit")
                            if record["decision"] == "kept":
                                kept.append(row)
                            index += 1
                        if kept:
                            if writer is None:
                                writer = pq.ParquetWriter(dest / path.name, parquet.schema_arrow, compression="zstd")
                            writer.write_table(pa.Table.from_pylist(kept, schema=parquet.schema_arrow))
                            counts[dataset] += len(kept)
                            total += len(kept)
                finally:
                    if writer is not None:
                        writer.close()
            expected = report["decisions"][dataset].get("kept", 0)
            if counts[dataset] != expected:
                raise RuntimeError("Exported row count differs from audit")
        if next(manifest, None) is not None:
            raise RuntimeError("Unconsumed manifest rows")
    digest = hashlib.sha256((directory / "row-manifest.jsonl").read_bytes()).hexdigest()
    summary = {"counts": counts, "total": total, "manifest_sha256": digest,
               "note": "Rule-filtered candidates; correctness and semantic quality were not verified."}
    (directory / "export-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
