import os

from static_analysis import analyze_files


def _write(tmp_path, name, content):
    path = os.path.join(str(tmp_path), name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def test_analyze_files_computes_metrics_and_real_nesting_depth(tmp_path):
    # This is the exact regression case for the gotcha found during design:
    # lizard.analyze_file() alone silently reports max_nesting_depth=0 for
    # every function, because it has zero extensions loaded by default.
    # This test fails loudly if that naive form ever creeps back in.
    path = _write(tmp_path, "sample.py", (
        "def add(a, b):\n"
        "    return a + b\n"
        "\n"
        "def complex_fn(x, y, z):\n"
        "    if x > 0:\n"
        "        if y > 0:\n"
        "            for i in range(z):\n"
        "                if i % 2 == 0:\n"
        "                    while i > 0:\n"
        "                        i -= 1\n"
        "                else:\n"
        "                    continue\n"
        "        else:\n"
        "            return -1\n"
        "    return x + y\n"
    ))
    result = analyze_files([path])
    assert result["language"] == "python"
    assert result["total_functions"] == 2
    assert result["max_nesting_depth"] == 5
    assert result["avg_cyclomatic_complexity"] == 3.5


def test_analyze_files_skips_unsupported_extensions(tmp_path):
    path = _write(tmp_path, "notes.txt", "just some notes, not code\n")
    result = analyze_files([path])
    assert result["total_functions"] == 0
    assert result["language"] is None
    assert result["avg_cyclomatic_complexity"] is None


def test_analyze_files_picks_dominant_language_by_nloc(tmp_path):
    py_path = _write(tmp_path, "big.py", "def f():\n" + "    x = 1\n" * 50 + "    return x\n")
    js_path = _write(tmp_path, "small.js", "function g() { return 1; }\n")
    result = analyze_files([py_path, js_path])
    assert result["language"] == "python"


def test_analyze_files_empty_list_returns_zeroed_result():
    result = analyze_files([])
    assert result == {
        "language": None,
        "avg_cyclomatic_complexity": None,
        "total_functions": 0,
        "total_lines": 0,
        "max_nesting_depth": 0,
    }
