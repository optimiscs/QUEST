"""Tokenize the configured SFT dataset on CPU and save a longest-example smoke set."""
import argparse
import json
from pathlib import Path

import yaml
from datasets import DatasetDict, concatenate_datasets
from llamafactory.data import get_dataset, get_template_and_fix_tokenizer
from llamafactory.hparams.parser import _parse_train_args
from llamafactory.model import load_tokenizer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--smoke-dataset", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    config = yaml.safe_load(args.config.read_text())
    tokenized = Path(config["tokenized_path"])
    if tokenized.exists() or args.smoke_dataset.exists() or args.report.exists():
        raise SystemExit("Refusing to overwrite existing dataset or report")
    # CPU preprocessing must not initialize or consume GPU memory during evaluation.
    config["use_cpu"] = True
    model_args, data_args, training_args, _, _ = _parse_train_args(config)
    tokenizer_module = load_tokenizer(model_args)
    template = get_template_and_fix_tokenizer(tokenizer_module["tokenizer"], data_args)
    data = get_dataset(template, model_args, data_args, training_args, stage="sft", **tokenizer_module)
    train, evaluation = data["train_dataset"], data["eval_dataset"]
    if len(train) != 4959 or len(evaluation) != 25:
        raise RuntimeError(f"Unexpected dataset split: train={len(train)} eval={len(evaluation)}")
    candidates = []
    lengths = {}
    for name, dataset in (("train", train), ("validation", evaluation)):
        lens = [len(row) for row in dataset["input_ids"]]
        if not lens:
            raise RuntimeError(f"Empty {name} split")
        i = max(range(len(lens)), key=lens.__getitem__)
        lengths[name] = {"count": len(lens), "max_tokens": lens[i], "at_cutoff": sum(x >= data_args.cutoff_len for x in lens)}
        candidates.append((lens[i], name, i, dataset))
    length, split, index, dataset = max(candidates, key=lambda x: x[0])
    example = dataset.select([index])
    if not any(value != -100 for value in example[0]["labels"]):
        raise RuntimeError("Longest example has no supervised tokens")
    # Two identical microbatches cover the peak with already-allocated gradients.
    smoke = DatasetDict({"train": concatenate_datasets([example, example]), "validation": example})
    smoke.save_to_disk(str(args.smoke_dataset))
    args.report.write_text(json.dumps({"lengths": lengths, "longest": {"split": split, "index": index, "tokens": length}, "note": "at_cutoff is not necessarily a count of truncated examples"}, indent=2) + "\n")
    print(args.report.read_text(), flush=True)


if __name__ == "__main__":
    main()
