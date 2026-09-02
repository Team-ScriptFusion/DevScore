from unittest.mock import patch

import torch

from semantic_matcher import THRESHOLD, semantic_match, semantic_match_batch


def test_semantic_match_obvious_match_clears_threshold():
    repos = [{
        "name": "machine-learning",
        "readme_text": "Framework for machine learning.",
    }]
    result = semantic_match("Machine Learning", repos)
    assert result["method"] == "semantic_match"
    assert result["confidence"] >= THRESHOLD
    assert result["verified"] is True
    assert result["reason"] is None
    assert result["evidence_repo"] == "machine-learning"


def test_semantic_match_obvious_non_match_stays_below_threshold():
    repos = [{
        "name": "todo-list-app",
        "readme_text": "A simple to-do list app built with vanilla HTML, CSS and JS checkboxes.",
    }]
    result = semantic_match("Kubernetes", repos)
    assert result["confidence"] < THRESHOLD
    assert result["verified"] is False
    assert result["reason"] == "below_confidence_threshold"


def test_semantic_match_picks_best_scoring_repo():
    repos = [
        {"name": "unrelated", "readme_text": "A recipe-sharing app."},
        {
            "name": "ml-project",
            "readme_text": "Machine learning pipeline using scikit-learn and pandas.",
        },
    ]
    result = semantic_match("Machine Learning", repos)
    assert result["evidence_repo"] == "ml-project"


def test_semantic_match_clamps_negative_similarity():
    """
    Cosine similarity ranges [-1, 1], but the DB constrains confidence to
    [0, 1] — a negative score must not reach the insert.
    """
    repos = [{"name": "todo-list-app", "readme_text": "A simple to-do list."}]
    with patch("semantic_matcher.util.cos_sim", return_value=torch.tensor([[-0.42]])):
        result = semantic_match("q3!!garbled", repos)

    assert result["confidence"] == 0.0
    assert result["verified"] is False
    assert result["reason"] == "below_confidence_threshold"


def test_semantic_match_batch_clamps_negative_similarity():
    repos = [{"name": "todo-list-app", "readme_text": "A simple to-do list."}]
    with patch(
        "semantic_matcher.util.cos_sim", return_value=torch.tensor([[-0.42], [-0.9]])
    ):
        results = semantic_match_batch(["q3!!garbled", "zz~~junk"], repos)

    assert [r["confidence"] for r in results] == [0.0, 0.0]
    assert all(r["verified"] is False for r in results)


def test_semantic_match_batch_agrees_with_individual_calls():
    repos = [
        {"name": "unrelated", "readme_text": "A recipe-sharing app."},
        {
            "name": "ml-project",
            "readme_text": "Machine learning pipeline using scikit-learn and pandas.",
        },
    ]
    skills = ["Machine Learning", "Kubernetes"]

    batched = semantic_match_batch(skills, repos)
    individually = [semantic_match(skill, repos) for skill in skills]

    assert [r["skill"] for r in batched] == skills
    for batch_result, single_result in zip(batched, individually):
        assert batch_result["skill"] == single_result["skill"]
        assert batch_result["evidence_repo"] == single_result["evidence_repo"]
        assert batch_result["verified"] == single_result["verified"]
        assert batch_result["method"] == single_result["method"]
        assert batch_result["reason"] == single_result["reason"]
        assert abs(batch_result["confidence"] - single_result["confidence"]) < 0.01


def test_semantic_match_batch_no_skills_returns_empty():
    repos = [{"name": "app", "readme_text": "An app."}]
    assert semantic_match_batch([], repos) == []
