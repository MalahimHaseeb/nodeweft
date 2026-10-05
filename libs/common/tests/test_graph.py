import pytest

from common.graph import ancestors_of, build_adjacency, find_duplicates, topological_order

NODES = [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}]


def test_order_respects_dependencies():
    edges = [{"source": "a", "target": "b"}, {"source": "b", "target": "c"}, {"source": "a", "target": "d"}]
    order = topological_order(NODES, edges)
    assert order.index("a") < order.index("b") < order.index("c")
    assert order.index("a") < order.index("d")


def test_cycle_detected():
    edges = [{"source": "a", "target": "b"}, {"source": "b", "target": "a"}]
    with pytest.raises(ValueError):
        topological_order(NODES[:2], edges)


def test_ancestors_and_duplicate_edges():
    edges = [{"source": "a", "target": "b"}, {"source": "a", "target": "b"}, {"source": "b", "target": "c"}]
    parents, _ = build_adjacency(NODES, edges)
    assert parents["b"] == ["a"]
    assert ancestors_of("c", parents) == {"a", "b"}


def test_find_duplicates():
    assert find_duplicates(["a", "b", "a", "a", "c", "b"]) == ["a", "b"]
