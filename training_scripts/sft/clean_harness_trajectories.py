"""Fail-closed preparation for source-ID/direct-evidence SFT curation.

This stage audits every source row, inventories raw page caches read-only, and
freezes a pilot plus a ranked acquisition queue. It never calls a model, executes
dataset code, labels heuristic scores as correctness, or exports train.jsonl.
"""
import argparse
import ast
import collections
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import unicodedata

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "inference"))
from inference import native_tools

DATASETS = {"objective": "QUEST-SFT-Data-Objective", "openended": "QUEST-SFT-Data-Open-ended"}
CALL = re.compile(r"<tool_call>(.*?)</tool_call>", re.S)
THINK = re.compile(r"<think>.*?</think>", re.S)
ANSWER = re.compile(r"<answer>(.*?)</answer>", re.S)
MEMORY = re.compile(r"RESEARCH STATE SUMMARY|<prev_state>|\"prev_state\"\s*:", re.I)
ALIASES = {"Visit": "visit", "Search": "search", "functions.visit": "visit", "functions.search": "search"}


def sha(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(value).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def question_key(text):
    return sha(re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip().casefold())


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def strict_json(text):
    return json.loads(text, object_pairs_hook=native_tools._object,
                      parse_constant=native_tools._invalid_constant)


def schemas_from_source():
    """Read literal schemas without importing tools or opening their caches."""
    tools = {}
    for name, filename in (("search", "tool_search.py"), ("visit", "tool_visit.py"),
                           ("PythonInterpreter", "tool_python.py")):
        tree = ast.parse((ROOT / "inference" / filename).read_text())
        for cls in [node for node in tree.body if isinstance(node, ast.ClassDef)]:
            attrs = {}
            for node in cls.body:
                if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                    try:
                        attrs[node.targets[0].id] = ast.literal_eval(node.value)
                    except (ValueError, TypeError):
                        pass
            if "parameters" in attrs and attrs.get("name") == name:
                tools[name] = type("ToolSchema", (), attrs)()
        if name not in tools:
            raise ValueError("Could not extract current schema: " + name)
    return native_tools.tool_schemas(tools)


class Rejected(ValueError):
    pass


def parse_trajectory(messages, schemas, *, allow_memory=False):
    """Conservative conversion: one complete call/result per research turn."""
    from jsonschema import Draft202012Validator
    validators = {s["function"]["name"]: Draft202012Validator(s["function"]["parameters"]) for s in schemas}
    if not isinstance(messages, list) or len(messages) < 4:
        raise Rejected("missing_messages")
    if any(not isinstance(m, dict) or not isinstance(m.get("content"), str) for m in messages):
        raise Rejected("invalid_message")
    if messages[0].get("role") != "system" or messages[1].get("role") != "user":
        raise Rejected("missing_initial_context")
    if not allow_memory and MEMORY.search(messages[1]["content"]):
        raise Rejected("compressed_history")
    last = THINK.sub("", messages[-1]["content"]).strip()
    final = ANSWER.fullmatch(last)
    if messages[-1].get("role") != "assistant" or not final or not final[1].strip():
        raise Rejected("no_complete_final_answer")
    if not allow_memory and any(MEMORY.search(m["content"]) for m in messages[2:]):
        raise Rejected("compressed_history")
    result = [dict(messages[0]), dict(messages[1])]
    pending = None
    visits, actions, repairs = [], [], []
    for i, m in enumerate(messages[2:], 2):
        content = m["content"]
        if m.get("role") == "assistant":
            if pending is not None:
                raise Rejected("missing_tool_result")
            if i == len(messages) - 1:
                # Final request in current native harness uses strict JSON;
                # <answer> is a program-side storage wrapper.
                result.append({"role": "assistant", "content": json.dumps({"answer": final[1].strip()}, ensure_ascii=False)})
                continue
            calls = list(CALL.finditer(content))
            if len(calls) != 1 or content.count("<tool_call>") != 1 or content.count("</tool_call>") != 1:
                raise Rejected("unsupported_call_layout")
            try:
                obj = strict_json(calls[0][1].strip())
            except (ValueError, TypeError):
                raise Rejected("invalid_tool_json")
            if not isinstance(obj, dict) or set(obj) != {"name", "arguments"}:
                raise Rejected("invalid_tool_shape")
            name, args = obj["name"], obj["arguments"]
            if not isinstance(name, str) or not isinstance(args, dict):
                raise Rejected("invalid_tool_shape")
            if name in ALIASES:
                repairs.append({"message": i, "alias": name, "canonical": ALIASES[name]})
                name = ALIASES[name]
            if name not in validators:
                raise Rejected("unavailable_tool")
            args = dict(args)
            # This is an equivalent scalar-to-array transport conversion.
            for key in ("url", "query"):
                if key in args and isinstance(args[key], str):
                    args[key] = [args[key]]
                    repairs.append({"message": i, "scalar_to_array": key})
            if list(validators[name].iter_errors(args)):
                raise Rejected("tool_schema_mismatch")
            if name == "visit":
                if not all(re.match(r"^https?://\S+$", u) for u in args["url"]):
                    raise Rejected("unsupported_original_visit_url")
                visits.append({"message": i, "urls": args["url"], "goal": args["goal"]})
            pending = f"call_{i:04d}"
            actions.append(sha({"name": name, "arguments": args}))
            result.append({"role": "assistant", "content": CALL.sub("", content).strip(), "tool_calls": [
                {"id": pending, "type": "function", "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}]})
        elif m.get("role") in {"user", "tool"}:
            if pending is None:
                raise Rejected("orphan_tool_result")
            if m.get("role") == "user":
                match = re.fullmatch(r"\s*<tool_response>\s*(.*?)\s*</tool_response>\s*", content, re.S)
                if not match:
                    raise Rejected("unsupported_user_turn")
                content = match[1]
            if not content.strip():
                raise Rejected("empty_tool_result")
            result.append({"role": "tool", "tool_call_id": pending, "content": content})
            pending = None
        else:
            raise Rejected("unsupported_role")
    if not actions:
        raise Rejected("no_research_actions")
    return result, {"visits": visits, "tool_calls": len(actions), "repeated_actions": len(actions) - len(set(actions)), "repairs": repairs}


def cache_inventory(roots, output):
    """Record URL locators only; later snapshots must re-read and hash the body."""
    index = collections.defaultdict(list)
    stats = collections.Counter()
    with (output / "cache-manifest.jsonl").open("x") as stream:
        for root in roots:
            for directory, dirs, names in os.walk(root):
                dirs[:] = sorted(d for d in dirs if d not in {"env", "envs", "node_modules", ".git", "models"})
                for name in sorted(names):
                    if not name.endswith(".db"):
                        continue
                    path = Path(directory, name).resolve()
                    stats["sqlite_files"] += 1
                    try:
                        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2) as db:
                            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='url_content'").fetchone():
                                continue
                            count = 0
                            for url, size, timestamp in db.execute("SELECT url,length(content),timestamp FROM url_content"):
                                if size and size > 0:
                                    index[url].append({"cache": str(path), "chars": size, "timestamp": timestamp})
                                    count += 1
                            stats["raw_page_rows"] += count
                            stream.write(json.dumps({"path": str(path), "raw_pages": count}) + "\n")
                    except sqlite3.Error as exc:
                        stats["read_errors"] += 1
                        stream.write(json.dumps({"path": str(path), "error": type(exc).__name__}) + "\n")
    dump(output / "page-locations.json", index)
    stats["unique_urls"] = len(index)
    return index, dict(stats)


def eval_questions(root):
    """Exact matching against local benchmark inputs; semantic check is pending."""
    keys, files = set(), []
    for path in sorted(root.rglob("*.jsonl")):
        if any(x in path.parts for x in {"results", "outputs", "test_data"}):
            continue
        found = 0
        try:
            with path.open() as stream:
                for line in stream:
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        continue
                    question = next((row[k] for k in ("question", "Question", "prompt", "query", "instruction") if isinstance(row.get(k), str)), None)
                    if question:
                        keys.add(question_key(question)); found += 1
            if found:
                files.append({"path": str(path), "sha256": file_sha(path), "questions": found})
        except (ValueError, UnicodeError):
            # Fail visibly; do not silently claim exhaustive contamination checks.
            files.append({"path": str(path), "status": "unparsed"})
    return keys, files


def verifier_index():
    import pyarrow.parquet as pq
    root = ROOT / "workspace/datasets/QUEST-SFT-Data-Objective-Script"
    index = collections.defaultdict(set)
    for batch in pq.ParquetFile(root / "data/train.parquet").iter_batches(batch_size=128):
        for row in batch.to_pylist():
            info = row.get("extra_info") or {}
            task = (row.get("reward_model") or {}).get("ground_truth", {}).get("task_id")
            if isinstance(info.get("question"), str) and isinstance(task, str) and Path(task).name == task:
                path = root / "eval_scripts" / (task + ".py")
                if path.is_file():
                    index[question_key(info["question"])].add(str(path))
    return {key: next(iter(paths)) for key, paths in index.items() if len(paths) == 1}


def main():
    import pyarrow.parquet as pq
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, action="append")
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    os.environ["QUEST_SOURCE_IDS"] = "true"
    schemas = schemas_from_source()
    sources = ["inference/" + name for name in ("source_ids.py", "native_tools.py", "tool_visit.py", "tool_search.py", "tool_python.py", "retrieval_experiment.py", "react_agent.py", "prompt.py", "tool_prompt_plugin.py")]
    sources += [str(Path(__file__).resolve().relative_to(ROOT))]
    contract = {"status": "preparation_only", "train_target": 1024, "quotas": {"objective": 768, "openended": 256},
                "validation_target": 128, "pilot_quotas": {"objective": 48, "openended": 16},
                "retrieval": {"method": "bm25_embedding", "delivery": "direct", "chunk_tokens": 400, "overlap": 64,
                              "candidates": 64, "top_k": 16, "budget": 8000, "short_page_tokens": 2000},
                "retrieval_parameter_source": "inference/scripts/run_browsecomp128_27b.py: explicit 64 candidates and 16 output chunks",
                "memory_summary": False, "tool_schemas": schemas,
                "source_sha256": {name: file_sha(ROOT / name) for name in sources},
                "training_eligible": False}
    dump(out / "harness_contract.json", contract)
    frozen = out / "source-snapshot"
    for name in sources:
        target = frozen / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    print("Indexing raw-page cache locations", flush=True)
    pages, cache_stats = cache_inventory(args.cache_root or [ROOT / "inference/cache", ROOT / "workspace/strict-reproduction"], out)
    print(json.dumps({"cache": cache_stats}), flush=True)
    eval_keys, eval_files = eval_questions(ROOT / "evaluation")
    dump(out / "eval-inputs.json", eval_files)
    refs = verifier_index()
    counts = collections.defaultdict(collections.Counter)
    best = {}
    source_files = []
    with (out / "row-manifest.jsonl").open("x") as manifest:
        for kind, dataset in DATASETS.items():
            for path in sorted((ROOT / "workspace/datasets" / dataset / "data").glob("*.parquet")):
                source_files.append({"path": str(path), "sha256": file_sha(path)})
                rowno = 0
                for batch in pq.ParquetFile(path).iter_batches(batch_size=32, columns=["messages"]):
                    for row in batch.to_pylist():
                        messages = row["messages"]
                        meta = {"kind": kind, "dataset": dataset, "file": str(path), "row": rowno,
                                "messages_sha256": sha(messages), "training_eligible": False}
                        rowno += 1; counts[kind]["raw"] += 1
                        try:
                            native, features = parse_trajectory(messages, schemas)
                            qkey = question_key(messages[1]["content"])
                            meta["question_sha256"] = qkey
                            if qkey in eval_keys:
                                raise Rejected("exact_eval_question")
                            urls = sorted({u for v in features["visits"] for u in v["urls"]})
                            missing = [u for u in urls if u not in pages]
                            meta.update(features)
                            meta.update({"decision": "structural_candidate", "visit_urls": urls, "missing_urls": missing,
                                         "cache_covered_urls": len(urls) - len(missing), "verifier_path": refs.get(qkey) if kind == "objective" else None,
                                         "native_sha256": sha(native), "original_chars": sum(len(m["content"]) for m in messages)})
                            counts[kind]["structural_candidate"] += 1
                            counts[kind]["all_visit_urls_cached"] += bool(urls) and not missing
                            counts[kind]["no_visit_calls"] += not urls
                            # Resource readiness orders work, never quality acceptance.
                            rank = (bool(meta["verifier_path"]) if kind == "objective" else True,
                                    not missing, -len(missing), -features["repeated_actions"], -meta["original_chars"], meta["messages_sha256"])
                            if qkey not in best or rank > best[qkey][0]:
                                best[qkey] = (rank, meta)
                        except Rejected as exc:
                            meta["decision"] = str(exc)
                            counts[kind][str(exc)] += 1
                        manifest.write(json.dumps(meta, ensure_ascii=False) + "\n")
                print(json.dumps({"file": path.name, "kind": kind, "counts": dict(counts[kind])}), flush=True)
    dump(out / "source-files.json", source_files)
    candidates = [item[1] for item in sorted(best.values(), key=lambda x: x[0], reverse=True)]
    pilot = []
    for kind, size in contract["pilot_quotas"].items():
        pilot.extend([row for row in candidates if row["kind"] == kind][:size])
    for filename, rows in (("candidate-manifest.jsonl", candidates), ("pilot-manifest.jsonl", pilot)):
        with (out / filename).open("x") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    needed = collections.Counter(u for row in candidates for u in row["missing_urls"])
    with (out / "missing-pages.jsonl").open("x") as stream:
        for url, count in needed.most_common():
            stream.write(json.dumps({"url": url, "candidate_tasks": count}, ensure_ascii=False) + "\n")
    # Freeze selected source rows, never rewrite originals or call these SFT-ready.
    wanted = {(row["file"], row["row"]): row for row in pilot}
    with (out / "pilot-original.jsonl").open("x") as stream:
        for filename in sorted({row["file"] for row in pilot}):
            index = 0
            for batch in pq.ParquetFile(filename).iter_batches(batch_size=32, columns=["messages"]):
                for row in batch.to_pylist():
                    meta = wanted.get((filename, index)); index += 1
                    if meta:
                        if sha(row["messages"]) != meta["messages_sha256"]:
                            raise RuntimeError("Source changed during scan")
                        stream.write(json.dumps({"provenance": meta, "messages": row["messages"]}, ensure_ascii=False) + "\n")
    report = {"stage": "structural_and_raw_cache_inventory_complete", "training_eligible": 0,
              "target": 1024, "counts": {k: dict(v) for k, v in counts.items()}, "cache": cache_stats,
              "distinct_candidate_tasks": len(candidates), "pilot_tasks": len(pilot), "missing_unique_urls": len(needed),
              "candidate_tasks_by_kind": dict(collections.Counter(row["kind"] for row in candidates)),
              "pilot_missing_unique_urls": len({u for row in pilot for u in row["missing_urls"]}),
              "exact_eval_questions": len(eval_keys),
              "pending": ["raw page recovery and version verification", "embedding retrieval and source-ID chronological replay",
                          "per-turn evidence and outcome verification", "semantic contamination and task clustering", "target tokenizer and loss-mask validation"],
              "limitations": ["Cache URL presence does not prove historical page identity or successful content.",
                              "Only exact benchmark matching has run; unparsed files are listed.",
                              "Candidate ordering measures preparation cost, not answer quality."]}
    dump(out / "report.json", report)
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
