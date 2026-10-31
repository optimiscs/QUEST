"""Select a reproducible subset from existing train and held-out validation splits."""
import argparse
import hashlib
import json
import random
from pathlib import Path

from datasets import DatasetDict, concatenate_datasets, load_from_disk


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--smoke-dataset", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train-count", type=int, default=1019)
    parser.add_argument("--validation-count", type=int, default=5)
    args = parser.parse_args()
    for path in (args.destination, args.smoke_dataset, args.report):
        if path.exists():
            raise SystemExit(f"Refusing to overwrite {path}")
    original = load_from_disk(str(args.source))
    rng = random.Random(args.seed)
    selection = {}
    subsets = {}
    lengths = {}
    candidates = []
    for name, count in (("train", args.train_count), ("validation", args.validation_count)):
        rows = original[name]
        if not 0 < count <= len(rows):
            raise ValueError(f"Invalid count for {name}")
        indices = sorted(rng.sample(range(len(rows)), count))
        subset = rows.select(indices)
        selection[name] = indices
        subsets[name] = subset
        lens = [len(x) for x in subset["input_ids"]]
        index = max(range(count), key=lens.__getitem__)
        lengths[name] = {"count": count, "max_tokens": lens[index], "total_tokens": sum(lens),
                         "supervised_tokens": sum(sum(t != -100 for t in labels) for labels in subset["labels"])}
        candidates.append((lens[index], name, index, subset))
    length, split, index, dataset = max(candidates, key=lambda x: x[0])
    example = dataset.select([index])
    if not any(token != -100 for token in example[0]["labels"]):
        raise RuntimeError("Longest sample has no supervised tokens")
    DatasetDict(subsets).save_to_disk(str(args.destination))
    DatasetDict({"train": concatenate_datasets([example, example]), "validation": example}).save_to_disk(str(args.smoke_dataset))
    ids_digest = hashlib.sha256(json.dumps(example[0]["input_ids"], separators=(",", ":")).encode()).hexdigest()
    result = {"seed": args.seed, "source": str(args.source.resolve()), "selection_method": "uniform without replacement independently within the original train and validation splits",
              "source_indices": selection, "lengths": lengths,
              "longest": {"split": split, "subset_index": index, "source_index": selection[split][index], "tokens": length, "input_ids_sha256": ids_digest}}
    args.report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"lengths": lengths, "longest": result["longest"]}, indent=2), flush=True)


if __name__ == "__main__":
    main()
