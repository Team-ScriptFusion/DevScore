from synonyms import normalize


def test_js_resolves_to_javascript():
    assert normalize("JS") == "javascript"


def test_golang_resolves_to_go():
    assert normalize("Golang") == "go"


def test_unknown_skill_lowercased_unchanged():
    assert normalize("Kubernetes") == "kubernetes"


def test_whitespace_stripped():
    assert normalize("  TypeScript  ".lower()) == "typescript"
