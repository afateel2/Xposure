from unittest.mock import MagicMock, patch

from app import retriever


def _point(clause_id: str, vector: list[float]) -> MagicMock:
    p = MagicMock()
    p.payload = {"clause_id": clause_id}
    p.vector = vector
    return p


def test_get_vectors_for_version_paginates_until_offset_is_none():
    # Verified against the real running Qdrant during the optimization
    # pass (25 real pages, 246 real clauses, exact count match) — this is
    # the permanent regression version of that check, since neither
    # ingested version has exceeded a single scroll page (256) on its own
    # to exercise this naturally in normal use.
    mock_client = MagicMock()
    mock_client.scroll.side_effect = [
        ([_point("1-1", [1.0]), _point("1-2", [2.0])], "cursor-1"),
        ([_point("1-3", [3.0])], "cursor-2"),
        ([_point("1-4", [4.0])], None),
    ]
    with patch.object(retriever, "get_client", return_value=mock_client):
        result = retriever.get_vectors_for_version("nca", "ecc", "1-2018")

    assert result == {"1-1": [1.0], "1-2": [2.0], "1-3": [3.0], "1-4": [4.0]}
    assert mock_client.scroll.call_count == 3


def test_get_vectors_for_version_stops_immediately_when_offset_starts_none():
    mock_client = MagicMock()
    mock_client.scroll.return_value = ([_point("1-1", [1.0])], None)
    with patch.object(retriever, "get_client", return_value=mock_client):
        result = retriever.get_vectors_for_version("nca", "ecc", "1-2018")

    assert result == {"1-1": [1.0]}
    assert mock_client.scroll.call_count == 1
