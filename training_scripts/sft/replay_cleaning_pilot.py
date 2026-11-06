"""Freeze pilot page bodies and replay current retrieval/source-ID code.

Outputs are review candidates only. No quality judgment or training export is
implied by successful retrieval. Cached pages are not assumed to be historical
snapshots belonging to the released SFT trajectories.
"""
import argparse
import collections
import concurrent.futures
import datetime
import json
import os
from pathlib import Path
import re
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "training_scripts/sft"))
from clean_harness_trajectories import dump, file_sha, parse_trajectory, sha
from inference import native_tools, source_ids


def readable_body(text):
    if not isinstance(text, str) or len(text.strip()) < 100:
        return False
    beginning = text[:1200].lower()
    failures = ("[visit] error", "[visit] failed", "[document_parser]", "[visit] empty",
                "warning: target url returned error", "just a moment...", "verify you are human")
    return not any(x in beginning for x in failures)


def recover_page(url, locations, allow_fetch, directory):
    import requests
    from urllib.parse import urlsplit
    record = {"url": url, "historical_identity_verified": False}
    # Prefer a deterministic latest cache version; never overwrite source caches.
    choices = sorted(locations, key=lambda x: (-x["timestamp"], x["cache"]))
    for locator in choices:
        try:
            with sqlite3.connect(Path(locator["cache"]).as_uri() + "?mode=ro", uri=True, timeout=2) as db:
                row = db.execute("SELECT content,timestamp FROM url_content WHERE url=?", (url,)).fetchone()
            if row and readable_body(row[0]):
                record.update(origin="local_cache_unlinked", cache=locator["cache"], cache_timestamp=row[1])
                body = row[0]
                break
        except sqlite3.Error:
            pass
    else:
        if not allow_fetch:
            return dict(record, status="missing_raw_page")
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return dict(record, status="unsupported_url")
        try:
            response = requests.get("https://r.jina.ai/" + url, timeout=(10, 45))
            if response.status_code != 200:
                return dict(record, status="fetch_http_error", http_status=response.status_code)
            body = response.text
            if "Markdown Content:" not in body or not readable_body(body):
                return dict(record, status="fetch_invalid_page")
            record.update(origin="fresh_fetch", fetched_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
        except requests.RequestException as exc:
            return dict(record, status="fetch_error", error_type=type(exc).__name__)
    digest = sha(body.encode())
    path = directory / (digest + ".txt")
    if not path.exists():
        path.write_text(body)
    if file_sha(path) != digest:
        raise RuntimeError("Snapshot hash mismatch")
    return dict(record, status="raw_page_frozen", path=str(path), sha256=digest, chars=len(body))


def search_format(text):
    # Preserve every snippet byte outside result headings. No query regeneration.
    pattern = re.compile(r"(?m)^\d+\. \[([^\n]*)\]\((https?://[^\n]+)\)\s*$")
    return pattern.sub(lambda m: f"Title: {m[1]}\nLink: {m[2]}\nSnipptes:", text)


def compact_known(registry, value):
    """A policy target may reference existing sources, never create new IDs."""
    return registry.assistant(value)


def replay(original, schemas, pages, folder, embedding_url, system_prompt):
    from inference.retrieval_experiment import select
    messages, _ = parse_trajectory(original, schemas)
    registry = source_ids.SourceRegistry(folder)
    # Use the current system template, retaining the original historical date.
    date_match = re.search(r"Current date:\s*([^\n]*)", original[0]["content"])
    prompt = native_tools.system_prompt(system_prompt)
    if date_match:
        prompt += date_match[1]
    converted = [registry.context({"role": "system", "content": prompt}, "system"),
                 registry.context(messages[1], "user")]
    retrieval = []
    pending = None
    for message in messages[2:]:
        if message["role"] == "assistant":
            compacted = compact_known(registry, message)
            converted.append(compacted)
            pending = message.get("tool_calls", [None])[0]
        else:
            if pending is None:
                raise ValueError("unpaired_tool_result")
            name = pending["function"]["name"]
            args = json.loads(pending["function"]["arguments"])
            content = message["content"]
            if name == "visit":
                sections = []
                for url in args["url"]:
                    record = pages[url]
                    raw = Path(record["path"]).read_text()
                    if sha(raw.encode()) != record["sha256"]:
                        raise ValueError("changed_page_snapshot")
                    selected, audit = select(raw, args["goal"], "bm25_embedding", embedding_url=embedding_url)
                    if audit.get("reason") == "no_retrieval_matches_prefix_fallback":
                        raise ValueError("retrieval_prefix_fallback")
                    retrieval.append(dict(audit, url=url, goal=args["goal"], page_sha256=record["sha256"], selected_sha256=sha(selected.encode())))
                    sections.append(f'The useful information in {url} for user goal {args["goal"]} as follows: \n\nEvidence in page: \n{selected}\n\n')
                content = "\n".join(sections)
                content = registry.compact(content)
            elif name == "search":
                content = registry.render(search_format(content))
            else:
                # Python URLs are not rewritten inside executable code: those
                # trajectories require a separate code-aware migration.
                if name == "PythonInterpreter" and source_ids.URL_PATTERN.search(args["code"]):
                    raise ValueError("python_url_requires_code_aware_migration")
                content = registry.compact(content)
            converted.append(dict(message, content=content))
            pending = None
    registry.context(converted, "replay_validation")
    dump(folder / "retrieval.json", retrieval)
    return converted


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fetch-missing", action="store_true")
    parser.add_argument("--embedding-url")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.workers <= 8:
        parser.error("workers must be between 1 and 8")
    prepared = args.prepared.resolve()
    contract = json.loads((prepared / "harness_contract.json").read_text())
    for name, expected in contract["source_sha256"].items():
        if file_sha(ROOT / name) != expected:
            raise RuntimeError("Harness changed since preparation: " + name)
    rows = [json.loads(line) for line in (prepared / "pilot-original.jsonl").read_text().splitlines()]
    for row in rows:
        if sha(row["messages"]) != row["provenance"]["messages_sha256"]:
            raise RuntimeError("Pilot source hash mismatch")
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    raw_dir = out / "raw-pages"
    raw_dir.mkdir()
    locations = json.loads((prepared / "page-locations.json").read_text())
    urls = sorted({u for row in rows for u in row["provenance"]["visit_urls"]})
    pages = {}
    print(json.dumps({"pilot_tasks": len(rows), "unique_page_urls": len(urls)}), flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool, (out / "page-manifest.jsonl").open("x") as stream:
        futures = {pool.submit(recover_page, url, locations.get(url, []), args.fetch_missing, raw_dir): url for url in urls}
        for future in concurrent.futures.as_completed(futures):
            record = future.result()
            pages[record["url"]] = record
            stream.write(json.dumps(record, ensure_ascii=False) + "\n"); stream.flush()
            if len(pages) % 10 == 0:
                print(json.dumps({"pages_processed": len(pages), "status": dict(collections.Counter(p["status"] for p in pages.values()))}), flush=True)
    os.environ["QUEST_SOURCE_IDS"] = "true"
    os.environ.pop("VISIT_BM25_POOL_URL", None)
    os.environ["VISIT_RETRIEVAL_CANDIDATES"] = str(contract["retrieval"]["candidates"])
    os.environ["VISIT_RETRIEVAL_TOP_K"] = str(contract["retrieval"]["top_k"])
    import prompt
    stats = collections.Counter()
    with (out / "decisions.jsonl").open("x") as decisions, (out / "review-candidates.jsonl").open("x") as candidates:
        for row in rows:
            meta = row["provenance"]
            absent = [url for url in meta["visit_urls"] if pages[url]["status"] != "raw_page_frozen"]
            decision = {"question_sha256": meta["question_sha256"], "kind": meta["kind"], "training_eligible": False}
            if absent:
                decision.update(status="missing_raw_pages", missing_urls=absent)
            elif not args.embedding_url:
                decision.update(status="awaiting_embedding_service")
            else:
                folder = out / "traces" / meta["question_sha256"]
                try:
                    messages = replay(row["messages"], contract["tool_schemas"], pages, folder, args.embedding_url, prompt.SYSTEM_PROMPT)
                    record = {"messages": messages, "tools": contract["tool_schemas"], "provenance": meta,
                              "training_eligible": False, "status": "awaiting_evidence_and_outcome_review"}
                    candidates.write(json.dumps(record, ensure_ascii=False) + "\n")
                    decision.update(status=record["status"], messages_sha256=sha(messages))
                except (ValueError, OSError, KeyError) as exc:
                    decision.update(status="replay_failed", reason=str(exc)[:300])
            stats[decision["status"]] += 1
            decisions.write(json.dumps(decision, ensure_ascii=False) + "\n"); decisions.flush()
    report = {"training_eligible": 0, "pilot_tasks": len(rows), "pages": dict(collections.Counter(p["status"] for p in pages.values())),
              "origins": dict(collections.Counter(p.get("origin", "unavailable") for p in pages.values())), "decisions": dict(stats),
              "prepared_contract_sha256": file_sha(prepared / "harness_contract.json"),
              "implementation_sha256": file_sha(__file__),
              "note": "Fresh/cache page versions need review; successful replay does not certify answer correctness."}
    dump(out / "report.json", report)
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
