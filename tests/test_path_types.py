import pytest

from xgap.algebra.types import Path, PathSet, SolutionSpace


def test_zero_length_path() -> None:
    path = Path.zero_length("n1")

    assert len(path) == 0
    assert path.first() == "n1"
    assert path.last() == "n1"
    assert path.node(1) == "n1"
    assert path.node_ids() == ("n1",)
    assert path.edge_ids() == ()


def test_one_length_path() -> None:
    path = Path.one_length("n1", "e1", "n2")

    assert len(path) == 1
    assert path.first() == "n1"
    assert path.last() == "n2"
    assert path.node(1) == "n1"
    assert path.node(2) == "n2"
    assert path.edge(1) == "e1"
    assert path.node_ids() == ("n1", "n2")
    assert path.edge_ids() == ("e1",)


def test_path_rejects_invalid_shape_and_indices() -> None:
    with pytest.raises(ValueError):
        Path(())
    with pytest.raises(ValueError):
        Path(("n1", "e1"))

    path = Path.one_length("n1", "e1", "n2")
    with pytest.raises(IndexError):
        path.node(0)
    with pytest.raises(IndexError):
        path.node(3)
    with pytest.raises(IndexError):
        path.edge(0)
    with pytest.raises(IndexError):
        path.edge(2)


def test_path_equality_and_hashing_use_full_sequence() -> None:
    first = Path(("n1", "e1", "n2"))
    same = Path(("n1", "e1", "n2"))
    different = Path(("n1", "e2", "n2"))

    assert first == same
    assert hash(first) == hash(same)
    assert first != different


def test_concatenate_valid_paths() -> None:
    left = Path.one_length("n1", "e1", "n2")
    right = Path.one_length("n2", "e2", "n3")

    assert left.can_concatenate(right)
    assert left.concatenate(right) == Path(("n1", "e1", "n2", "e2", "n3"))


def test_reject_invalid_concatenation() -> None:
    left = Path.one_length("n1", "e1", "n2")
    right = Path.one_length("n3", "e2", "n4")

    assert not left.can_concatenate(right)
    with pytest.raises(ValueError):
        left.concatenate(right)


def test_pathset_add_union_iteration_len_contains_and_sorted_view() -> None:
    first = Path.one_length("n1", "e1", "n2")
    second = Path.zero_length("n1")
    path_set = PathSet()

    path_set.add(first)
    path_set.add(first)

    assert len(path_set) == 1
    assert first in path_set
    assert list(path_set) == [first]

    union = path_set.union(PathSet([second, first]))

    assert len(union) == 2
    assert union.sorted() == (second, first)
    assert union == PathSet([first, second])


def test_pathset_rejects_non_paths() -> None:
    path_set = PathSet()

    with pytest.raises(TypeError):
        path_set.add("not-a-path")  # type: ignore[arg-type]


def test_solution_space_shape() -> None:
    rows = ({"name": "Moe"},)

    assert SolutionSpace(rows=rows).rows == rows
