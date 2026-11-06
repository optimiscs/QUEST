"""Finish CPU-only preparation: temporal source IDs and BM25 candidates.

Never fetches pages or calls embedding/judge services. Summary-bearing legacy
tool results are used only to audit historical source visibility; no transformed
conversation is exported as training data.
"""
import argparse
import collections
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "training_scripts/sft"))
from clean_harness_trajectories import dump, file_sha, parse_trajectory, sha
from replay_cleaning_pilot import compact_known, recover_page, search_format
from inference.source_ids import SourceRegistry


def main():
    import pyarrow.parquet as pq
    from inference.retrieval_experiment import bm25_rank, count_tokens, split_chunks
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepared = args.prepared.resolve()
    contract = json.loads((prepared / "harness_contract.json").read_text())
    for name, digest in contract["source_sha256"].items():
        if file_sha(ROOT / name) != digest:
            raise RuntimeError("Frozen source changed: " + name)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    rows = [row for row in map(json.loads, (prepared / "row-manifest.jsonl").read_text().splitlines())
            if row["decision"] == "structural_candidate"]
    locations = json.loads((prepared / "page-locations.json").read_text())
    raw_dir = out / "raw-pages"
    raw_dir.mkdir()
    wanted_urls = {u for row in rows for u in row["visit_urls"]}
    cached_urls = sorted(wanted_urls & locations.keys())
    pages, chunks = {}, {}
    print(json.dumps({"candidate_rows": len(rows), "candidate_tasks": len({r['question_sha256'] for r in rows}), "cached_urls": len(cached_urls)}), flush=True)
    with (out / "page-manifest.jsonl").open("x") as stream:
        for url in cached_urls:
            record = recover_page(url, locations[url], False, raw_dir)
            pages[url] = record
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            if record["status"] == "raw_page_frozen":
                text = Path(record["path"]).read_text()
                size = count_tokens(text)
                chunk_list = split_chunks(text) if size > 2000 else []
                chunks[url] = (size, chunk_list)
                dump(raw_dir / (record["sha256"] + ".chunks.json"),
                     {"page_sha256": record["sha256"], "input_tokens": size,
                      "short_page": size <= 2000,
                      "chunks": [{"index": c.index, "text": c.text, "sha256": sha(c.text.encode())} for c in chunk_list]})
    retrieval_keys = set()
    with (out / "bm25-candidates.jsonl").open("x") as stream:
        for row in rows:
            for visit in row["visits"]:
                for url in visit["urls"]:
                    if url not in chunks:
                        continue
                    key = (url, visit["goal"])
                    if key in retrieval_keys:
                        continue
                    retrieval_keys.add(key)
                    size, chunk_list = chunks[url]
                    ranking = bm25_rank(chunk_list, visit["goal"]) if size > 2000 else []
                    stream.write(json.dumps({"url": url, "goal": visit["goal"], "page_sha256": pages[url]["sha256"],
                                             "input_tokens": size, "short_page": size <= 2000,
                                             "bm25_indices": ranking[:contract["retrieval"]["candidates"]],
                                             "status": "direct_short_page_pending_review" if size <= 2000 else "awaiting_embedding",
                                             "training_eligible": False}, ensure_ascii=False) + "\n")
    print(json.dumps({"pages": len(chunks), "retrieval_requests_prepared": len(retrieval_keys)}), flush=True)
    wanted = {(row["file"], row["row"]): row for row in rows}
    stats = collections.defaultdict(collections.Counter)
    decisions = []
    os.environ["QUEST_SOURCE_IDS"] = "true"
    with (out / "source-id-audit.jsonl").open("x") as stream:
        for filename in sorted({row["file"] for row in rows}):
            index = 0
            for batch in pq.ParquetFile(filename).iter_batches(batch_size=32, columns=["messages"]):
                for source in batch.to_pylist():
                    meta = wanted.get((filename, index)); index += 1
                    if meta is None:
                        continue
                    if sha(source["messages"]) != meta["messages_sha256"]:
                        raise RuntimeError("Source row changed")
                    native, _ = parse_trajectory(source["messages"], contract["tool_schemas"])
                    folder = out / "source-maps" / meta["messages_sha256"]
                    registry = SourceRegistry(folder)
                    registry.compact(native[1])
                    status, failure = "passed_legacy_visibility_check", None
                    pending = None
                    for i, message in enumerate(native[2:], 2):
                        try:
                            if message["role"] == "assistant":
                                calls = message.get("tool_calls", [])
                                if calls and calls[0]["function"]["name"] == "PythonInterpreter":
                                    # Code semantics can change when URL strings
                                    # become IDs; do not silently migrate it.
                                    from inference.source_ids import URL_PATTERN
                                    if URL_PATTERN.search(json.loads(calls[0]["function"]["arguments"])["code"]):
                                        raise ValueError("python_url_requires_code_aware_migration")
                                compact_known(registry, message)
                                pending = calls[0]["function"]["name"] if calls else None
                            elif pending == "search":
                                registry.render(search_format(message["content"]))
                            else:
                                registry.compact(message["content"])
                        except ValueError as exc:
                            status = "held_source_visibility"
                            failure = {"message": i, "reason": str(exc)}
                            break
                    available = [u for u in meta["visit_urls"] if u in chunks]
                    missing = sorted(set(meta["visit_urls"]) - set(available))
                    if failure and registry.path.exists():
                        registry.path.rename(folder / "rejected-sources.json")
                    decision = {"question_sha256": meta["question_sha256"], "kind": meta["kind"],
                                "file": meta["file"], "row": meta["row"],
                                "repeated_actions": meta["repeated_actions"], "original_chars": meta["original_chars"],
                                "messages_sha256": meta["messages_sha256"], "source_id_status": status, "failure": failure,
                                "source_map": str(folder / "sources.json") if registry.path.exists() else None,
                                "raw_pages_available": len(available), "missing_urls": missing,
                                "visit_calls": len(meta["visits"]), "training_eligible": False,
                                "next_step": "resolve_source_visibility" if failure else "recover_raw_pages" if missing else "retrieve_and_review"}
                    decisions.append(decision)
                    stream.write(json.dumps(decision, ensure_ascii=False) + "\n")
                    stats[meta["kind"]][status] += 1
                    if failure:
                        stats[meta["kind"]][failure["reason"]] += 1
                    if not failure:
                        stats[meta["kind"]]["missing_raw_pages" if missing else "all_pages_available_or_no_visit"] += 1
            print(json.dumps({"source_file": Path(filename).name, "source_id_counts": {k: dict(v) for k, v in stats.items()}}), flush=True)
    # This is an acquisition queue, not a final selection or quality ranking.
    eligible_rows = [r for r in decisions if not r["failure"]]
    best = {}
    for row in sorted(eligible_rows, key=lambda r: (len(r["missing_urls"]), r["repeated_actions"], r["original_chars"], r["messages_sha256"])):
        best.setdefault(row["question_sha256"], row)
    eligible = list(best.values())
    with (out / "offline-candidate-manifest.jsonl").open("x") as stream:
        for row in sorted(eligible, key=lambda x: (len(x["missing_urls"]), x["question_sha256"])):
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    missing_urls = collections.Counter(url for row in eligible for url in row["missing_urls"])
    with (out / "missing-pages.jsonl").open("x") as stream:
        for url, count in missing_urls.most_common():
            stream.write(json.dumps({"url": url, "candidate_tasks": count}, ensure_ascii=False) + "\n")
    report = {"stage": "offline_preparation_complete", "training_eligible": 0,
              "source_id_counts": {k: dict(v) for k, v in stats.items()},
              "structural_rows_checked": len(rows), "source_id_compatible_rows": len(eligible_rows),
              "offline_candidates": len(eligible), "candidate_tasks_by_kind": dict(collections.Counter(r["kind"] for r in eligible)),
              "raw_pages_frozen": len(chunks), "raw_page_failures": len(pages) - len(chunks),
              "bm25_requests_prepared": len(retrieval_keys), "missing_unique_urls": len(missing_urls),
              "network_calls": 0, "embedding_calls": 0, "judge_calls": 0,
              "prepared_contract_sha256": file_sha(prepared / "harness_contract.json"),
              "source_sha256": {name: file_sha(ROOT / "training_scripts/sft" / name) for name in ("prepare_cleaning_evidence.py", "replay_cleaning_pilot.py")},
              "pending": ["recover missing pages and verify page versions", "embedding reranking and replay with replacement observations",
                          "per-turn grounding and answer verification", "semantic task/benchmark deduplication", "final template tokenization and loss-mask checks"],
              "limitations": ["Source maps reflect old observations and must be rebuilt after retrieval replacement.",
                              "Rows held by the source-ID check are not necessarily factually wrong.",
                              "No train.jsonl has been exported; quality remains unverified."]}
    dump(out / "report.json", report)
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
