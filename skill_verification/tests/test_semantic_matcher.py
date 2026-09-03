from models import RepoEvidence, SkillStatus
from semantic_matcher import NOT_VERIFIABLE_SKILLS, TfidfEmbeddingProvider, match_semantic


def _repo(name, readme, description=""):
    return RepoEvidence(
        repo_name=name, is_fork=False, description=description, languages={},
        manifests={}, readme_text=readme, commit_count=0, last_commit_at=None,
    )


def test_not_verifiable_skill_never_hits_the_matcher():
    result = match_semantic("Figma", [], TfidfEmbeddingProvider())
    assert result.status == SkillStatus.NOT_VERIFIABLE
    assert "figma" in NOT_VERIFIABLE_SKILLS


def test_no_evidence_text_is_unverified_not_none():
    repo = _repo("empty-repo", readme="")
    result = match_semantic("Machine Learning", [repo], TfidfEmbeddingProvider())
    assert result.status == SkillStatus.UNVERIFIED
    assert "no_evidence_found" in result.reason


def test_obvious_match_scores_higher_than_obvious_non_match():
    ml_repo = _repo(
        "ml-project",
        readme="This project trains a convolutional neural network using TensorFlow "
               "and PyTorch for image classification, with a dataset loader and "
               "a training loop for the deep learning model.",
    )
    todo_repo = _repo(
        "todo-app",
        readme="A simple todo list app where you can add, edit, and delete tasks. "
               "Built with a basic form and a list view.",
    )
    provider = TfidfEmbeddingProvider()
    ml_result = match_semantic("Machine Learning", [ml_repo], provider, threshold=0.0)
    todo_result = match_semantic("Machine Learning", [todo_repo], provider, threshold=0.0)
    assert ml_result.confidence > todo_result.confidence


def test_every_claim_ends_in_a_result_never_none():
    repo = _repo("some-repo", readme="just a readme with unrelated words")
    result = match_semantic("Quantum Computing", [repo], TfidfEmbeddingProvider())
    assert result is not None
    assert result.status in (SkillStatus.VERIFIED, SkillStatus.UNVERIFIED, SkillStatus.NOT_VERIFIABLE)
