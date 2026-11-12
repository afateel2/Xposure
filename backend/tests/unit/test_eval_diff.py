import pytest

from tests.eval_diff import _load_labels, load_sample_pairs


def test_labels_csv_loads_and_keys_correctly():
    labels = _load_labels()
    # 2-2-3-2 was revised from 'clarification' to 'tightened' after
    # finding four more structurally identical annex rows (see that row's
    # note in ecc_v1_v2_labels.csv) — pinned here so a future edit to the
    # CSV has to consciously touch this test too, not drift silently.
    assert labels[("2-2-3-2", "2-2-3-2")] == "tightened"
    assert labels[("5-1", None)] == "withdrawn"
    assert labels[(None, "2-5-3-9")] == "new_obligation"
    assert labels[("1-1-1", "1-1-1")] == "editorial"
    assert labels[("1-9-3-2", "1.9.3.2")] == "relaxed"


def test_sample_prioritizes_labeled_pairs_within_a_small_limit():
    # A --limit at or above the labeled set's size must still surface
    # every labeled pair so a run produces real accuracy signal on all of
    # them, not just whatever happens to sort first (mostly unlabeled
    # domain-1 exact matches). Must be >= len(_load_labels()) — this test
    # uses the harness's own default (tests.eval_diff's --limit default)
    # rather than a hardcoded number, so growing the CSV further can't
    # silently make this assertion span more labels than the limit covers.
    labels = _load_labels()
    limit = max(20, len(labels))
    try:
        pairs = load_sample_pairs(limit=limit)
    except AttributeError:
        # load_sample_pairs reads the LIVE database. The demo BASELINE (see
        # app/demo/) holds only ECC-1:2018, so there is no 2-2024 to sample.
        pytest.skip("needs both ECC versions ingested in the live database (demo baseline has only 1-2018)")
    keys = {(p["old_clause_id"], p["new_clause_id"]) for p in pairs}
    for labeled_key in labels:
        assert labeled_key in keys
    assert len(pairs) == limit
