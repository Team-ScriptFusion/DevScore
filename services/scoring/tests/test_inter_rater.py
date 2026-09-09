from inter_rater import compute_inter_rater


def test_compute_inter_rater_perfect_agreement():
    pairs = [(80, 80), (60, 60), (90, 90), (40, 40)]
    result = compute_inter_rater(pairs)
    assert result == {"spearman_rho": 1.0, "alpha": 1.0, "sample_size": 4}


def test_compute_inter_rater_disagreement_scores_lower_than_agreement():
    agree = compute_inter_rater([(80, 82), (60, 58), (90, 91), (40, 42)])
    disagree = compute_inter_rater([(80, 20), (60, 95), (90, 10), (40, 88)])
    assert agree["spearman_rho"] > disagree["spearman_rho"]
    assert agree["alpha"] > disagree["alpha"]
