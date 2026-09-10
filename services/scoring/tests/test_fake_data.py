from fake_data import CATEGORIES, TRUE_WEIGHTS, generate_fake_dataset


def test_generate_fake_dataset_returns_requested_count():
    rows = generate_fake_dataset(20, seed=1)
    assert len(rows) == 20


def test_generate_fake_dataset_is_deterministic_for_seed():
    a = generate_fake_dataset(10, seed=5)
    b = generate_fake_dataset(10, seed=5)
    assert a == b


def test_generate_fake_dataset_scores_within_bounds():
    rows = generate_fake_dataset(50, seed=2)
    for row in rows:
        assert 0.0 <= row["expert_score"] <= 100.0
        assert set(row["vi_by_category"].keys()) == set(CATEGORIES)
        assert 0.0 <= row["code_quality_vi"] <= 1.0


def test_generate_fake_dataset_unique_user_ids():
    rows = generate_fake_dataset(15, seed=3)
    ids = [r["user_id"] for r in rows]
    assert len(ids) == len(set(ids))


def test_true_weights_sum_to_one():
    assert abs(sum(TRUE_WEIGHTS.values()) - 1.0) < 1e-9
