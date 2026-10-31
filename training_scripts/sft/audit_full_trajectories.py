"""Read-only, reproducible staged audit of the complete QUEST SFT records.

Outputs only row identifiers, hashes, diagnostics and a kept-row manifest.
This never executes dataset-provided code, calls a grader, or changes sources.
"""
import argparse
import collections
import csv
import hashlib
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATASETS = ("QUEST-SFT-Data-Objective", "QUEST-SFT-Data-Open-ended")
BLOCK = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL)


def sha_messages(messages):
    body = json.dumps(messages, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


def normalize_question(text):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip().casefold()


def tool_diagnostics(messages):
    stats = collections.Counter()
    names = collections.Counter()
    for message in messages:
        if message.get("role") != "assistant" or not isinstance(message.get("content"), str):
            continue
        text = message["content"]
        stats["tag_open"] += text.count("<tool_call>")
        stats["tag_close"] += text.count("</tool_call>")
        for match in BLOCK.finditer(text):
            raw = match.group(1).strip()
            if not raw.startswith("{"):
                stats["non_json_form"] += 1
                continue
            stats["json_blocks"] += 1
            try:
                obj = json.loads(raw)
            except (ValueError, RecursionError):
                stats["invalid_json"] += 1
                continue
            if not isinstance(obj, dict) or not isinstance(obj.get("name"), str) or not isinstance(obj.get("arguments"), dict):
                stats["invalid_json_shape"] += 1
            else:
                names[obj["name"]] += 1
    return stats, names


def main():
    import pyarrow.parquet as pq

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--length-audit", type=Path, default=ROOT / "workspace/strict-reproduction/sft-preflight-20261027-r1/row-lengths.csv")
    parser.add_argument("--eval-references", type=Path, default=ROOT / "workspace/strict-reproduction/browsecomp-pro6000-nvfp4-embedding-128-20261031-r1/judge/ground-truth/references.json")
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    manifest_path, report_path = out / "row-manifest.jsonl", out / "report.json"
    if manifest_path.exists() or report_path.exists():
        raise SystemExit("Refusing to overwrite a prior audit")
    with args.length_audit.open(newline="") as f:
        audit = {(r["dataset"], r["file"], int(r["row"])): r for r in csv.DictReader(f)}
    if len(audit) != 51764:
        raise RuntimeError("Historical audit has an unexpected row count")
    refs = json.loads(args.eval_references.read_text())
    eval_hashes = {hashlib.sha256(normalize_question(x["question"]).encode()).hexdigest() for x in refs}
    counts = collections.defaultdict(collections.Counter)
    tool_names = collections.Counter()
    reasons = collections.defaultdict(collections.Counter)
    question_counts = collections.defaultdict(collections.Counter)
    seen_full = {}
    seen_rows = set()
    with manifest_path.open("x", encoding="utf-8") as manifest:
        for dataset in DATASETS:
            directory = ROOT / "workspace/datasets" / dataset / "data"
            for file in sorted(directory.glob("*.parquet")):
                reader = pq.ParquetFile(file)
                index = 0
                for batch in reader.iter_batches(batch_size=32, columns=["messages"]):
                    for row in batch.to_pylist():
                        key = (dataset, file.name, index)
                        prior = audit.get(key)
                        if prior is None or key in seen_rows:
                            raise RuntimeError(f"Missing or duplicate audit row: {key}")
                        seen_rows.add(key)
                        messages = row.get("messages") or []
                        digest = sha_messages(messages)
                        match = digest == prior["row_sha256"]
                        valid = prior["native_valid"] == "True"
                        c = counts[dataset]
                        c["raw"] += 1
                        c["hash_mismatch"] += not match
                        c["native_rejected"] += not valid
                        if valid and match:
                            c["stage1_native_and_hash"] += 1
                        duplicate = digest in seen_full
                        prior_id = seen_full.get(digest)
                        if valid and match and not duplicate:
                            seen_full[digest] = key
                            c["stage2_exact_unique"] += 1
                        elif valid and match:
                            c["exact_duplicate_removed"] += 1
                        diag, names = tool_diagnostics(messages)
                        has_bad_json = bool(diag["invalid_json"] or diag["invalid_json_shape"])
                        if valid and match and not duplicate and not has_bad_json:
                            c["stage3_valid_json_or_other_syntax"] += 1
                        if valid and match and not duplicate and has_bad_json:
                            c["invalid_json_quarantined"] += 1
                        positive_loss = int(prior["native_loss_tokens"] or 0) > 0 if valid else False
                        keep = valid and match and not duplicate and not has_bad_json and positive_loss
                        if keep:
                            c["stage4_positive_loss"] += 1
                        elif valid and match and not duplicate and not has_bad_json:
                            c["no_loss_quarantined"] += 1
                        q = next((x.get("content", "") for x in messages if x.get("role") == "user" and isinstance(x.get("content"), str) and not x.get("content", "").lstrip().startswith("<tool_response>")), "")
                        qhash = hashlib.sha256(normalize_question(q).encode()).hexdigest() if q else None
                        if keep and qhash:
                            question_counts[dataset][qhash] += 1
                        match_eval = bool(qhash and qhash in eval_hashes)
                        if keep and not match_eval:
                            c["stage5_exact_eval_question_excluded"] += 1
                        if keep and match_eval:
                            c["exact_eval_question_quarantined"] += 1
                        if valid and match:
                            c["assistant_last_tool_call"] += bool(messages and messages[-1].get("role") == "assistant" and "<tool_call>" in str(messages[-1].get("content", "")))
                            c["assistant_last_answer_tag"] += bool(messages and messages[-1].get("role") == "assistant" and "<answer>" in str(messages[-1].get("content", "")))
                            c["rows_unbalanced_tool_tags"] += diag["tag_open"] != diag["tag_close"]
                            c["rows_non_json_tool_form"] += bool(diag["non_json_form"])
                            c["rows_over_32k_old_tokenizer"] += int(prior["native_untruncated_tokens"] or 0) > 32768
                            c["tool_json_blocks"] += diag["json_blocks"]
                            tool_names.update(names)
                        reason = "native_rejected" if not valid else "source_hash_mismatch" if not match else "exact_duplicate" if duplicate else "invalid_json" if has_bad_json else "no_loss" if not positive_loss else "exact_eval_question" if match_eval else "kept"
                        reasons[dataset][reason] += 1
                        manifest.write(json.dumps({"dataset": dataset, "file": file.name, "row": index, "messages_sha256": digest, "question_sha256": qhash, "decision": reason, "duplicate_of": prior_id, "tool": dict(diag), "historical_tokens": prior["native_untruncated_tokens"]}, ensure_ascii=False) + "\n")
                        index += 1
    if len(seen_rows) != len(audit):
        raise RuntimeError(f"Observed {len(seen_rows)} rows, expected {len(audit)}")
    duplicate_questions = {}
    for dataset, qs in question_counts.items():
        duplicate_questions[dataset] = {"distinct_question_hashes": len(qs), "groups_with_multiple_rows": sum(x > 1 for x in qs.values()), "rows_in_duplicate_groups": sum(x for x in qs.values() if x > 1)}
    report = {"mode": "deterministic_cpu_audit", "rows": len(seen_rows), "dataset_counts": {k: dict(v) for k, v in counts.items()}, "decisions": {k: dict(v) for k, v in reasons.items()}, "question_duplicate_diagnostics": duplicate_questions, "tool_names_in_native_valid_rows": dict(tool_names), "exact_eval_questions_compared": len(eval_hashes), "limitations": ["Historical native format and token counts use the 4B tokenizer; hashes checked against current rows.", "Only JSON-shaped tool calls are validated; other syntaxes and unbalanced tags are flagged, not rejected.", "Exact benchmark question matching does not detect paraphrased contamination.", "No ground truth, process correctness, source quality or semantic quality was verified.", "The manifest is an audit candidate list, not a released training dataset."]}
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
