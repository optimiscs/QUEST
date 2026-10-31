"""Associate objective rows to verifier files by normalized exact question only."""
import argparse
import collections
import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq

from audit_full_trajectories import ROOT, normalize_question


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    source = ROOT / "workspace/datasets/QUEST-SFT-Data-Objective-Script"
    index = collections.defaultdict(set)
    source_rows = present = 0
    for batch in pq.ParquetFile(source / "data/train.parquet").iter_batches(batch_size=128, columns=["reward_model", "extra_info"]):
        for row in batch.to_pylist():
            source_rows += 1
            question = (row.get("extra_info") or {}).get("question")
            ground = (row.get("reward_model") or {}).get("ground_truth") or {}
            task = ground.get("task_id") if isinstance(ground, dict) else None
            if not isinstance(question, str) or not isinstance(task, str):
                continue
            digest = hashlib.sha256(normalize_question(question).encode()).hexdigest()
            index[digest].add(task)
            if Path(task).name == task and (source / "eval_scripts" / f"{task}.py").is_file():
                present += 1
    stats = collections.Counter()
    matched_questions, matched_tasks, matched_with_file = set(), set(), set()
    with (args.audit_dir / "row-manifest.jsonl").open() as manifest:
        for line in manifest:
            row = json.loads(line)
            if row["dataset"] != "QUEST-SFT-Data-Objective" or row["decision"] != "kept":
                continue
            stats["candidate_rows"] += 1
            choices = index.get(row["question_sha256"], set())
            if not choices:
                continue
            stats["exact_match_rows"] += 1
            matched_questions.add(row["question_sha256"])
            if len(choices) != 1:
                stats["ambiguous_task_id_rows"] += 1
                continue
            task = next(iter(choices))
            matched_tasks.add(task)
            stats["unique_task_id_rows"] += 1
            if Path(task).name == task and (source / "eval_scripts" / f"{task}.py").is_file():
                stats["unique_task_with_script_rows"] += 1
                matched_with_file.add(task)
    result = {"script_dataset_rows": source_rows, "unique_reference_questions": len(index),
              "script_files_present_rows": present, "candidate_matches": dict(stats),
              "matched_unique_questions": len(matched_questions), "matched_unique_task_ids": len(matched_tasks),
              "matched_unique_tasks_with_script": len(matched_with_file),
              "note": "Exact normalized question association only; verifier files were not executed."}
    with args.output.open("x") as out:
        json.dump(result, out, indent=2)
        out.write("\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
