"""Validate attended training tokens against the frozen native-policy export."""
import hashlib
import numpy as np


def digest(values):
    return hashlib.sha256(np.asarray(values, dtype=np.int64).tobytes()).hexdigest()


def expected_rows(dataset):
    return {(digest(row['input_ids']), digest(row['labels'])) for row in dataset}


def validate_batch(input_ids, labels, attention_mask, allowed, position_ids=None):
    import torch
    assert attention_mask.ndim == 2 and input_ids.shape == labels.shape == attention_mask.shape
    for i in range(input_ids.shape[0]):
        valid = attention_mask[i].bool()
        # This run uses right padding and no sequence packing. The multimodal
        # collator may append masked dummy-image tokens; they cannot add loss
        # or move any attended text positions.
        n = int(valid.sum())
        assert bool(valid[:n].all()) and not bool(valid[n:].any()), 'Unexpected left/interior padding'
        assert bool((labels[i, ~valid] == -100).all()), 'Padding has supervised labels'
        key = (digest(input_ids[i, valid].cpu().numpy()), digest(labels[i, valid].cpu().numpy()))
        assert key in allowed, 'Trainer changed audited input tokens or loss labels'
        if position_ids is not None:
            positions = position_ids[..., i, :n] if position_ids.ndim == 3 else position_ids[i, :n]
            assert bool((positions == torch.arange(n, device=positions.device)).all()), 'Text positions differ from serving'
    return True
