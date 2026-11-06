import sys
from pathlib import Path
import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'training_scripts/sft'))
from training_batch_contract import expected_rows, validate_batch


def test_masked_dummy_image_cannot_change_text_or_supervision():
    ids = torch.tensor([[10, 20, 30, 999, 999]])
    labels = torch.tensor([[-100, -100, 30, -100, -100]])
    mask = torch.tensor([[1, 1, 1, 0, 0]])
    positions = torch.arange(5).view(1, 1, 5).expand(3, 1, 5)
    allowed = expected_rows([{'input_ids': [10, 20, 30], 'labels': [-100, -100, 30]}])
    assert validate_batch(ids, labels, mask, allowed, positions)
    with pytest.raises(AssertionError, match='positions'):
        validate_batch(ids, labels, mask, allowed, positions + 1)
    bad = labels.clone(); bad[0, 0] = 10
    with pytest.raises(AssertionError, match='labels'):
        validate_batch(ids, bad, mask, allowed, positions)
    bad = labels.clone(); bad[0, 3] = 999
    with pytest.raises(AssertionError, match='Padding'):
        validate_batch(ids, bad, mask, allowed, positions)
