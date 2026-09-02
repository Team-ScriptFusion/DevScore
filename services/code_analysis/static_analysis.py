"""
Phase 2 — static analysis via lizard (module spec section 5/8).

CRITICAL: lizard.analyze_file(...) is NOT used here. It is a pre-built
FileAnalyzer with ZERO extensions loaded (see lizard's own source:
`analyze_file = FileAnalyzer(get_extensions([]))`), so its
max_nesting_depth field silently stays 0 for every function regardless
of actual nesting depth. Verified directly during design against a
5-level-deep test function. The 'nd' (nesting depth) extension must be
loaded explicitly, as done below.
"""

import lizard

_ANALYZER = lizard.FileAnalyzer(lizard.get_extensions(['nd']))


def _language_for(path: str):
    """Returns lizard's language name for a file's extension, or None if
    lizard doesn't support it. FileInformation itself has no .language
    attribute (verified directly) — language is derived from the reader
    class lizard would use for this file's extension."""
    reader_cls = lizard.get_reader_for(path)
    if reader_cls is None:
        return None
    return reader_cls.language_names[0]


def analyze_files(file_paths: list) -> dict:
    """
    Runs lizard against every analyzable file in file_paths (silently
    skipping files lizard doesn't support, or that raise on parse), and
    rolls the per-function results up to one repo-level metrics dict.
    """
    all_functions = []
    language_nloc = {}

    for path in file_paths:
        language = _language_for(path)
        if language is None:
            continue
        try:
            file_info = _ANALYZER(path)
        except Exception:
            continue
        if file_info is None:
            continue
        all_functions.extend(file_info.function_list)
        language_nloc[language] = language_nloc.get(language, 0) + (file_info.nloc or 0)

    if not all_functions:
        return {
            "language": None,
            "avg_cyclomatic_complexity": None,
            "total_functions": 0,
            "total_lines": 0,
            "max_nesting_depth": 0,
        }

    dominant_language = max(language_nloc, key=language_nloc.get) if language_nloc else None
    total_ccn = sum(f.cyclomatic_complexity for f in all_functions)
    total_nloc = sum(f.nloc for f in all_functions)
    max_nd = max((f.max_nesting_depth for f in all_functions), default=0)

    return {
        "language": dominant_language,
        "avg_cyclomatic_complexity": round(total_ccn / len(all_functions), 2),
        "total_functions": len(all_functions),
        "total_lines": total_nloc,
        "max_nesting_depth": max_nd,
    }
