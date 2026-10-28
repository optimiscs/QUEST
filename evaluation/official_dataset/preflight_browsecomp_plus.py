#!/usr/bin/env python3
"""Offline input and author-reference checks for a prepared BrowseComp-Plus case."""
import argparse
import hashlib
import json
from pathlib import Path


def sha(path):
    with path.open("rb") as stream:
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate(task, record, references, qrels):
    qid = str(task.get("filename", ""))
    if not qid or record.get("query_id") != qid:
        raise ValueError("query ID mismatch")
    matches = [row for row in references if str(row.get("query_id", "")) == qid]
    if len(matches) != 1:
        raise ValueError("expected exactly one reference for query ID")
    if matches[0].get("query") != task.get("question"):
        raise ValueError("reference question mismatch")
    if not isinstance(matches[0].get("answer"), str) or not matches[0]["answer"].strip():
        raise ValueError("missing reference answer")
    positives = []
    for number, line in enumerate(qrels, 1):
        parts = line.split()
        if not parts:
            continue
        if len(parts) != 4:
            raise ValueError(f"invalid qrel line {number}")
        if parts[0] == qid:
            positives.append(parts[2])
    if not positives:
        raise ValueError("no qrel evidence for query; author evaluator would divide by zero")
    if record.get("status") not in ("completed", "failed"):
        raise ValueError("invalid prediction status")
    return {"query_id": qid, "reference_matches": 1, "qrel_entries": len(positives),
            "prediction_status": record["status"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--qrels", type=Path, required=True)
    args = parser.parse_args()
    paths = {name: getattr(args, name).resolve(strict=True)
             for name in ("task", "record", "reference", "qrels")}
    hashes = {name: sha(path) for name, path in paths.items()}
    task = json.loads(paths["task"].read_text(encoding="utf-8"))
    record = json.loads(paths["record"].read_text(encoding="utf-8"))
    with paths["reference"].open(encoding="utf-8") as reference, paths["qrels"].open(encoding="utf-8") as qrels:
        rows = (json.loads(line) for line in reference if line.strip())
        result = validate(task, record, rows, qrels)
    if hashes != {name: sha(path) for name, path in paths.items()}:
        raise ValueError("input changed during validation")
    result.update({"status": "preflight_passed_not_scored", "input_sha256": hashes})
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
