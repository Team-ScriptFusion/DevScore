from main import match_skills


def test_match_skills_direct_match_short_circuits_semantic():
    repos = [{"name": "app", "languages": {"Python": 5000}, "readme_text": ""}]
    results = match_skills(["Python"], repos)
    assert results == [{
        "skill": "Python",
        "verified": True,
        "method": "direct_match",
        "confidence": 1.0,
        "evidence_repo": "app",
        "reason": None,
    }]


def test_match_skills_empty_repos_marks_no_public_repos():
    results = match_skills(["Kubernetes"], [])
    assert results == [{
        "skill": "Kubernetes",
        "verified": False,
        "method": "unverified",
        "confidence": None,
        "evidence_repo": None,
        "reason": "no_public_repos",
    }]


def test_match_skills_falls_back_to_semantic():
    repos = [{
        "name": "ml-project",
        "languages": {"Python": 5000},
        "readme_text": "A deep learning pipeline using TensorFlow for image classification.",
    }]
    results = match_skills(["Machine Learning"], repos)
    assert results[0]["method"] == "semantic_match"


def test_match_skills_preserves_input_order():
    repos = [{"name": "app", "languages": {"Python": 5000}, "readme_text": ""}]
    results = match_skills(["Kubernetes", "Python"], repos)
    assert [r["skill"] for r in results] == ["Kubernetes", "Python"]
