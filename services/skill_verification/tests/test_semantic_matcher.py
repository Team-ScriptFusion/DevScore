from semantic_matcher import THRESHOLD, semantic_match


def test_semantic_match_obvious_match_clears_threshold():
    repos = [{
        "name": "deep-learning-toolkit",
        "readme_text": (
            "A PyTorch and TensorFlow based deep learning library for "
            "training neural networks on image classification datasets."
        ),
    }]
    result = semantic_match("Machine Learning", repos)
    assert result["method"] == "semantic_match"
    assert result["confidence"] >= THRESHOLD
    assert result["verified"] is True
    assert result["reason"] is None
    assert result["evidence_repo"] == "deep-learning-toolkit"


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
