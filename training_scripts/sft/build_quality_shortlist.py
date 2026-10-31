"""Build a reproducible, task-disjoint heuristic shortlist; not an outcome verifier."""
import argparse
import collections
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

import pyarrow as pa
import pyarrow.parquet as pq

from audit_full_trajectories import DATASETS, ROOT, normalize_question, sha_messages

URL = re.compile(r"https?://[^\s<>\[\]{}\"']+", re.I)
ANSWER = re.compile(r"<answer>(.*?)</answer>", re.S | re.I)
ERROR = re.compile(r"\[(?:visit|search)\]\s*error|network error|proxy circuit open", re.I)
UNCERTAIN = re.compile(r"\b(?:cannot (?:be )?(?:determine|verified|determine[d]?|verify)|unable to (?:determine|verify)|insufficient (?:evidence|information)|unknown)\b", re.I)


def url_key(url):
    value = url.rstrip(".,;:!?)]}")
    try:
        p = urlsplit(value)
        return (p.hostname or "").lower() + p.path.rstrip("/") + ("?" + p.query if p.query else "")
    except ValueError:
        return ""


def features(messages, repeated_actions, verifier_available):
    assistants = [m.get("content", "") for m in messages if m.get("role") == "assistant" and isinstance(m.get("content"), str)]
    last = assistants[-1] if assistants else ""
    outputs = [m.get("content", "") for m in messages if m.get("role") in ("user", "tool") and isinstance(m.get("content"), str) and (m.get("role") == "tool" or m.get("content", "").lstrip().startswith("<tool_response>"))]
    answers = ANSWER.findall(last)
    answer = answers[-1].strip() if answers else ""
    final = bool(answer) and bool(re.search(r"[\w\u4e00-\u9fff]", answer))
    partial_tool = not final and "<tool_call>" in last
    source_urls = {url_key(u) for content in outputs for u in URL.findall(content)}
    answer_urls = {url_key(u) for u in URL.findall(answer)}
    cited_matching_source = bool((source_urls & answer_urls) - {""})
    uncertain = bool(final and UNCERTAIN.search(answer[-800:]))
    valid_outputs = sum(bool(x.strip()) and not ERROR.search(x[:1500]) for x in outputs)
    errors = len(outputs) - valid_outputs
    # Heuristic ranking only: it does not establish truth, citation entailment, or quality.
    score = 30 + 12 * bool(valid_outputs) + 8 * final + 5 * partial_tool + 8 * cited_matching_source
    score += 5 * verifier_available
    score -= min(20, 5 * repeated_actions) + min(10, 2 * errors) + 10 * uncertain
    return {"heuristic_score": score, "final_answer_tag": final, "partial_tool_call": partial_tool,
            "tool_responses": len(outputs), "apparently_nonerror_responses": valid_outputs,
            "tool_error_responses": errors, "repeated_exact_actions": repeated_actions,
            "answer_links_overlap_tool_output": cited_matching_source, "answer_uncertainty_flag": uncertain,
            "exact_question_matched_local_verifier_file": verifier_available}


def reference_index():
    source = ROOT / "workspace/datasets/QUEST-SFT-Data-Objective-Script"
    refs = collections.defaultdict(set)
    for batch in pq.ParquetFile(source / "data/train.parquet").iter_batches(batch_size=128, columns=["reward_model", "extra_info"]):
        for row in batch.to_pylist():
            question = (row.get("extra_info") or {}).get("question")
            ground = (row.get("reward_model") or {}).get("ground_truth") or {}
            task = ground.get("task_id") if isinstance(ground, dict) else None
            if isinstance(question, str) and isinstance(task, str):
                digest = hashlib.sha256(normalize_question(question).encode()).hexdigest()
                refs[digest].add(task)
    return {h for h, tasks in refs.items() if len(tasks) == 1 and
            Path(next(iter(tasks))).name == next(iter(tasks)) and
            (source / "eval_scripts" / f"{next(iter(tasks))}.py").is_file()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    repeated = {}
    with (args.audit_dir / "redundancy-flags.jsonl").open() as f:
        for line in f:
            row = json.loads(line)
            repeated[(row["dataset"], row["file"], row["row"])] = row["extra_actions"]
    refs = reference_index()
    all_rows = []
    stats = collections.defaultdict(collections.Counter)
    features_path = args.output / "feature-manifest.jsonl"
    with (args.audit_dir / "row-manifest.jsonl").open() as manifest, features_path.open("x") as dest:
        for dataset in DATASETS:
            for path in sorted((ROOT / "workspace/datasets" / dataset / "data").glob("*.parquet")):
                row_index = 0
                for batch in pq.ParquetFile(path).iter_batches(batch_size=32, columns=["messages"]):
                    for row in batch.to_pylist():
                        prior = json.loads(next(manifest))
                        if (prior["dataset"], prior["file"], prior["row"]) != (dataset, path.name, row_index):
                            raise RuntimeError("Manifest/source ordering mismatch")
                        row_index += 1
                        if prior["decision"] != "kept":
                            continue
                        diag = prior["tool"]
                        if diag.get("non_json_form", 0) or diag.get("tag_open", 0) != diag.get("tag_close", 0):
                            stats[dataset]["held_unrecognized_syntax"] += 1
                            continue
                        messages = row.get("messages") or []
                        if sha_messages(messages) != prior["messages_sha256"]:
                            raise RuntimeError("Source row changed after audit")
                        count = repeated.get((dataset, path.name, prior["row"]), 0)
                        values = features(messages, count, prior.get("question_sha256") in refs)
                        record = {key: prior[key] for key in ("dataset", "file", "row", "messages_sha256", "question_sha256")}
                        record.update(values)
                        dest.write(json.dumps(record, ensure_ascii=False) + "\n")
                        all_rows.append(record)
                        c = stats[dataset]
                        c["rule_candidates"] += 1
                        for key in ("final_answer_tag", "partial_tool_call", "answer_links_overlap_tool_output", "answer_uncertainty_flag", "exact_question_matched_local_verifier_file"):
                            c[key] += bool(values[key])
                        c["with_repeat_actions"] += count > 0
    # One row per normalized question and endpoint type, without rewriting conversations.
    # Unknown outcomes remain unverified; quality scores are ordering heuristics only.
    best = {}
    for x in all_rows:
        if not x["question_sha256"]:
            continue
        endpoint_type = "final" if x["final_answer_tag"] else "tool" if x["partial_tool_call"] else "other"
        key = (x["dataset"], x["question_sha256"], endpoint_type)
        tie = (x["heuristic_score"], x["messages_sha256"])
        if key not in best or tie > (best[key]["heuristic_score"], best[key]["messages_sha256"]):
            best[key] = x
    selected = []
    selected_questions = set()
    for dataset, desired in ((DATASETS[0], 817), (DATASETS[1], 207)):
        picked = []
        final_quota = round(desired * 0.7)
        for kind, quota in (("final", final_quota), ("tool", desired - final_quota)):
            pool = [x for (ds, _, ep), x in best.items() if ds == dataset and ep == kind and not x["answer_uncertainty_flag"]]
            pool.sort(key=lambda x: (-x["heuristic_score"], x["question_sha256"], x["messages_sha256"]))
            for x in pool:
                if x["question_sha256"] in selected_questions:
                    continue
                picked.append(x)
                selected_questions.add(x["question_sha256"])
                if len([v for v in picked if ("final" if v["final_answer_tag"] else "tool") == kind]) == quota:
                    break
            if len([v for v in picked if ("final" if v["final_answer_tag"] else "tool") == kind]) != quota:
                raise RuntimeError(f"Insufficient {kind} candidates for {dataset}")
        # Hash ordering yields a deterministic, task-disjoint held-out set, not a random split.
        picked.sort(key=lambda x: hashlib.sha256(("quest-holdout-v1:" + x["question_sha256"]).encode()).hexdigest())
        for i, x in enumerate(picked):
            item = dict(x, split="validation" if i < (40 if dataset == DATASETS[0] else 10) else "train", outcome_status="unverified")
            selected.append(item)
    questions = {x["question_sha256"] for x in selected if x["split"] == "train"}
    if questions & {x["question_sha256"] for x in selected if x["split"] == "validation"}:
        raise RuntimeError("Question leakage across train and validation")
    with (args.output / "shortlist.jsonl").open("x") as f:
        for x in selected:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    counts = collections.Counter((x["dataset"], x["split"]) for x in selected)
    result = {"features": {k: dict(v) for k, v in stats.items()}, "selected": {f"{a}:{b}": n for (a,b),n in counts.items()},
              "total": len(selected), "question_groups": len({x["question_sha256"] for x in selected}),
              "note": "Deterministic heuristic shortlist with 70% final and 30% tool-ending records; not verified high quality; requires outcome and evidence validation before training."}
    (args.output / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
