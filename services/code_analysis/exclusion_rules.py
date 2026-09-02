"""Phase 3 — exclusion rules (module spec section 6). Each rule is a
pure predicate; the caller (main.py) is responsible for recording the
matching reason rather than silently dropping a repo."""

MAX_TARBALL_BYTES = 25 * 1024 * 1024  # 25MB
MIN_TOTAL_LINES = 20

# Soft, unreliable heuristic — documented as such, not presented as a
# solved problem (module spec's own framing). Substring match, case
# insensitive, against the repo name only.
TUTORIAL_NAME_PATTERNS = (
    "tutorial", "clone", "practice", "bootcamp", "learning",
    "-starter", "hello-world",
)


def is_fork(repo_metadata: dict) -> bool:
    return bool(repo_metadata.get("fork"))


def is_too_large(content_length_bytes) -> bool:
    return content_length_bytes is not None and content_length_bytes > MAX_TARBALL_BYTES


def is_empty(total_lines: int) -> bool:
    return total_lines < MIN_TOTAL_LINES


def matches_tutorial_heuristic(repo_name: str) -> bool:
    name = repo_name.lower()
    return any(pattern in name for pattern in TUTORIAL_NAME_PATTERNS)
