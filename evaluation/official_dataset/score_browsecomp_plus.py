#!/usr/bin/env python3
"""Explicitly run the pinned BrowseComp-Plus author evaluator for one case.

The evaluator makes external model requests. Nothing runs on import.
Output logs and scores may contain private questions and answers.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from preflight_browsecomp_plus import sha, validate

PIN = "046949032b0328319cc9a02663a759ec601d9402"


def check_source(source):
    def git(*args):
        return subprocess.run(["git", "-C", str(source), *args], capture_output=True, text=True, check=True).stdout.strip()
    if git("rev-parse", "HEAD") != PIN or git("status", "--porcelain", "--untracked-files=no"):
        raise ValueError("author checkout has wrong revision or modified tracked files")


def find_verdict(scores_dir, qid):
    candidates = []
    for path in scores_dir.rglob("*_eval.json"):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if str(row.get("query_id")) == qid:
            candidates.append((path, row))
    if len(candidates) != 1:
        return None
    path, row = candidates[0]
    result = row.get("judge_result")
    if (row.get("is_completed") is not True or not isinstance(result, dict)
            or result.get("parse_error") is not False or not isinstance(result.get("correct"), bool)):
        return None
    return path, result["correct"]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for option in ("source", "task", "record", "reference", "qrels", "out"):
        p.add_argument("--" + option, type=Path, required=True)
    p.add_argument("--model", required=True, help="Author evaluator judge model; supplied OpenAI-compatible endpoint must support Responses API")
    p.add_argument("--max-output-tokens", type=int, default=1024)
    args = p.parse_args()
    if not args.model.strip() or args.max_output_tokens < 1:
        p.error("nonempty model and positive token limit required")
    source = args.source.resolve(strict=True)
    check_source(source)
    paths = {name: getattr(args, name).resolve(strict=True) for name in ("task", "record", "reference", "qrels")}
    hashes = {name: sha(path) for name, path in paths.items()}
    task = json.loads(paths["task"].read_text(encoding="utf-8"))
    record = json.loads(paths["record"].read_text(encoding="utf-8"))
    with paths["reference"].open(encoding="utf-8") as refs, paths["qrels"].open(encoding="utf-8") as qrels:
        result = validate(task, record, (json.loads(x) for x in refs if x.strip()), qrels)
    if hashes != {name: sha(path) for name, path in paths.items()}:
        raise ValueError("input changed during preflight")
    if record["status"] != "completed":
        raise ValueError("missing prediction: cannot invoke scorer")
    if not os.environ.get("OPENAI_API_KEY"):
        raise ValueError("OPENAI_API_KEY must be supplied in the environment")
    args.out.mkdir(parents=True, exist_ok=False)
    input_dir, score_dir = args.out / "input", args.out / "scores"
    input_dir.mkdir()
    score_dir.mkdir()
    snapshot = input_dir / ("run_" + result["query_id"] + ".json")
    snapshot.write_bytes(paths["record"].read_bytes())
    if sha(snapshot) != hashes["record"]:
        raise ValueError("record changed before snapshot")
    cmd = [sys.executable, str(source / "scripts_evaluation/evaluate_with_openai.py"),
           "--input_dir", str(input_dir.resolve()), "--ground_truth", str(paths["reference"]),
           "--qrel_evidence", str(paths["qrels"]), "--eval_dir", str(score_dir.resolve()),
           "--model", args.model, "--max_output_tokens", str(args.max_output_tokens)]
    start = time.monotonic()
    exit_code, launch_error = None, None
    with (args.out / "author.log").open("w", encoding="utf-8") as log:
        try:
            proc = subprocess.run(cmd, cwd=source, stdout=log, stderr=subprocess.STDOUT, check=False)
            exit_code = proc.returncode
        except OSError as error:
            # Exception details can contain paths or credentials; preserve its type only.
            launch_error = type(error).__name__
            log.write("author process could not be launched: " + launch_error + "\n")
    try:
        stable = hashes == {name: sha(path) for name, path in paths.items()} and sha(snapshot) == hashes["record"]
    except OSError:
        stable = False
    try:
        check_source(source)
        source_unchanged = True
    except (OSError, ValueError, subprocess.CalledProcessError):
        source_unchanged = False
    verdict = find_verdict(score_dir, result["query_id"]) if exit_code == 0 and stable and source_unchanged else None
    receipt = {"benchmark": "BrowseComp-Plus", "status": "scored" if verdict else "unscored",
               "source_commit": PIN, "judge_model": args.model, "exit_code": exit_code, "launch_error": launch_error,
               "input_sha256": hashes, "inputs_unchanged": stable, "source_unchanged": source_unchanged,
               "wall_seconds": time.monotonic() - start, "correct": verdict[1] if verdict else None,
               "judge_result_path": str(verdict[0]) if verdict else None,
               "judge_result_sha256": sha(verdict[0]) if verdict else None}
    (args.out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    if not verdict:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
