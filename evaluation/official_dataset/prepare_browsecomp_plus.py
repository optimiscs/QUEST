#!/usr/bin/env python3
"""Convert an explicitly supplied QUEST trajectory into BrowseComp-Plus input.

This creates an author-format input record only. It does not execute a scorer.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def jsonl(path):
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if line.strip():
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(f"{path}:{number}: invalid JSON") from error
                if not isinstance(value, dict):
                    raise ValueError(f"{path}:{number}: expected object")
                yield value


def build_record(task, trajectory, events):
    qid = str(task.get("filename", "")).strip()
    if not qid or not re.fullmatch(r"[A-Za-z0-9_-]+", qid):
        raise ValueError("missing or unsafe query id")
    if not isinstance(task.get("question"), str) or not task["question"].strip():
        raise ValueError("missing question")
    if not trajectory or trajectory[-1].get("question") != task["question"]:
        raise ValueError("trajectory question does not match task")
    answer = trajectory[-1].get("prediction")
    if answer is not None and not isinstance(answer, str):
        raise ValueError("prediction must be a string or null")
    searches = 0
    retrieved = set()
    for event in events:
        if event.get("kind") != "fixed_corpus_search":
            continue
        if event.get("event") == "span_start":
            searches += 1
        if event.get("event") == "span_end":
            retrieved.update(re.findall(r"bm25://([^\s/]+)", str(event.get("output", ""))))
    answer = answer or ""
    return {
        "query_id": qid,
        "tool_call_counts": {"search": searches},
        "status": "completed" if answer.strip() else "failed",
        "retrieved_docids": sorted(retrieved),
        "result": [{"type": "output_text", "output": answer}],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", type=Path, required=True, help="One JSON task record")
    parser.add_argument("--trajectory", type=Path, required=True, help="Explicit QUEST JSONL trajectory")
    parser.add_argument("--events", type=Path, required=True, help="Explicit observed search events JSONL")
    parser.add_argument("--out", type=Path, required=True, help="New output directory")
    args = parser.parse_args()
    paths = {key: getattr(args, key).resolve(strict=True) for key in ("task", "trajectory", "events")}
    before = {key: digest(path) for key, path in paths.items()}
    task = json.loads(paths["task"].read_text(encoding="utf-8"))
    if not isinstance(task, dict):
        raise ValueError("task must be a JSON object")
    record = build_record(task, list(jsonl(paths["trajectory"])), jsonl(paths["events"]))
    if before != {key: digest(path) for key, path in paths.items()}:
        raise ValueError("input changed while reading")
    args.out.mkdir(parents=True, exist_ok=False)
    input_dir = args.out / "input"
    input_dir.mkdir()
    output = input_dir / ("run_" + record["query_id"] + ".json")
    output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "benchmark": "BrowseComp-Plus", "status": "prepared_not_scored",
        "source_commit": "046949032b0328319cc9a02663a759ec601d9402",
        "inputs": {key: {"path": str(paths[key]), "sha256": before[key]} for key in paths},
        "record_sha256": digest(output), "prediction_status": record["status"],
        "retrieval_provenance": "fixed_corpus_search events; not an independently verified corpus audit",
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
