"""The UI libraries (extra ``ui``: Streamlit and the Altair and pandas it
brings) are imported only by the demo page, ``scripts/demo_ui.py`` (Demo B),
its live smoke test (``scripts/demo_ui_live_check.py``, which drives the page
with Streamlit's test runner), and the page's tests; the package never needs
them. Static check (``ast``)."""

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
UI_LIBRARIES = {"streamlit", "altair"}
ALLOWED = {
    REPO / "scripts" / "demo_ui.py",
    REPO / "scripts" / "demo_ui_live_check.py",
    REPO / "tests" / "integration" / "test_demo_ui_app.py",
}


def _roots(tree: ast.AST) -> set[str]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


def test_ui_libraries_only_in_the_demo_page():
    offenders = [
        path.relative_to(REPO).as_posix()
        for folder in ("src", "scripts", "tests")
        for path in (REPO / folder).rglob("*.py")
        if path not in ALLOWED
        and _roots(ast.parse(path.read_text(encoding="utf-8"))) & UI_LIBRARIES
    ]
    assert offenders == []


def test_the_page_never_touches_the_key_or_logs():
    tree = ast.parse((REPO / "scripts" / "demo_ui.py").read_text(encoding="utf-8"))
    tree.body = tree.body[1:]  # the docstring explains the key; the code never uses it
    source = ast.unparse(tree)
    for forbidden in ("METIS_API_KEY", "get_secret_value", ".env", "logging", "print("):
        assert forbidden not in source, forbidden
