"""
Skill/language-name synonym table for direct matching (Phase 1). Grow this
as real student data surfaces new aliases — this is a living list, not a
one-time task (per the module's known risk: normalization needs ongoing
tuning).
"""

SYNONYMS = {
    "js": "javascript",
    "ts": "typescript",
    "golang": "go",
    "py": "python",
    "csharp": "c#",
    "c sharp": "c#",
    "cpp": "c++",
    "c plus plus": "c++",
    "node": "node.js",
    "nodejs": "node.js",
    "reactjs": "react",
    "react.js": "react",
    "vuejs": "vue",
    "vue.js": "vue",
    "postgres": "postgresql",
    "html5": "html",
    "css3": "css",
    "k8s": "kubernetes",
}


def normalize(term: str) -> str:
    """Lowercase, strip, and resolve through the synonym table."""
    key = term.strip().lower()
    return SYNONYMS.get(key, key)
