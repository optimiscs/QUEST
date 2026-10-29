import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'inference'))
from retrieval_experiment import bm25_rank, count_tokens, pack, reciprocal_rank_fusion, select, split_chunks


def test_chunks_preserve_unicode_and_respect_budget():
    text = ('猫和狗 live together. ' * 180) + '\n\n' + ('A unique telescope observation. ' * 150)
    chunks = split_chunks(text, target=100, overlap=10)
    assert len(chunks) > 2
    assert all(count_tokens(c.text) <= 100 for c in chunks)
    assert all('\ufffd' not in c.text for c in chunks)
    result, chosen = pack(chunks, list(reversed(range(len(chunks)))), top_k=8, budget=200)
    assert count_tokens(result) <= 200
    assert chosen == sorted(chosen)


def test_bm25_does_not_select_nonmatches():
    chunks = split_chunks('red fox\n\nblue whale\n\ngreen frog')
    assert bm25_rank(chunks, 'whale') == [1]
    assert bm25_rank(chunks, 'telescope') == []


def test_rrf_rewards_consensus():
    assert reciprocal_rank_fusion([[0, 1], [2, 1]])[0] == 1


def test_table_chunks_keep_column_names():
    rows = ''.join(f'| album {i} | {2000+i} |\n' for i in range(40))
    table = '| album | year |\n| --- | --- |\n' + rows
    chunks = split_chunks(table, target=60, overlap=10)
    assert len(chunks) > 1
    assert all('| album | year |' in c.text and '| --- | --- |' in c.text for c in chunks)
    assert all(f'| album {i} |' in ''.join(c.text for c in chunks) for i in range(40))


def test_no_match_fallback_remains_within_budget():
    text = ('red fox jumps over logs. ' * 2000)
    result, audit = select(text, 'spectroscopy', 'bm25')
    assert audit['reason'] == 'no_retrieval_matches_prefix_fallback'
    assert count_tokens(result) <= 8000
    assert all(piece in text for piece in result.split('\n\n'))
