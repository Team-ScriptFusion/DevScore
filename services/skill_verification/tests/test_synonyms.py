from synonyms import normalize


def test_normalize_passes_through_unknown_terms():
    assert normalize("Python") == "python"


def test_normalize_resolves_known_synonym():
    assert normalize("JS") == "javascript"


def test_normalize_strips_and_lowercases():
    assert normalize("  Golang ") == "go"


def test_normalize_empty_string():
    assert normalize("") == ""
