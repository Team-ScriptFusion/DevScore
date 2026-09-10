from split import assign_split


def test_assign_split_deterministic_for_seed():
    ids = ["a", "b", "c", "d", "e", "f"]
    first = assign_split(ids, 0.5, seed=7)
    second = assign_split(ids, 0.5, seed=7)
    assert first == second


def test_assign_split_respects_train_fraction():
    ids = [f"u{i}" for i in range(10)]
    result = assign_split(ids, 0.7, seed=3)
    train_count = sum(1 for v in result.values() if v == "train")
    assert train_count == 7
    assert set(result.keys()) == set(ids)


def test_assign_split_is_idempotent_for_already_assigned_ids():
    ids = ["a", "b", "c", "d"]
    first = assign_split(ids, 0.5, seed=1)
    second = assign_split(ids, 0.5, seed=1, existing=first)
    assert second == first


def test_assign_split_only_assigns_new_ids_not_in_existing():
    existing = {"a": "train", "b": "test"}
    result = assign_split(["a", "b", "c"], 0.5, seed=1, existing=existing)
    assert result["a"] == "train"
    assert result["b"] == "test"
    assert result["c"] in ("train", "test")


def test_assign_split_empty_ids_returns_empty():
    assert assign_split([], 0.7, seed=1) == {}
