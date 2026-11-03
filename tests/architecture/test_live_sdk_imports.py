"""The live SDK (extra ``live``) is imported only by the OpenAI-compatible
adapter (ADR-0021), so offline code never needs it. Static check (``ast``)."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "metis_auto"
LIVE_LIBRARIES = {"openai", "httpx2", "httpcore2"}
ALLOWED = {SRC / "adapters" / "providers" / "openai_compat.py"}


def _roots(tree: ast.AST) -> set[str]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


def test_live_libraries_only_in_the_adapter():
    offenders = [
        path.relative_to(SRC).as_posix()
        for path in SRC.rglob("*.py")
        if path not in ALLOWED
        and _roots(ast.parse(path.read_text(encoding="utf-8"))) & LIVE_LIBRARIES
    ]
    assert offenders == []


def test_the_providers_package_does_not_import_the_adapter_eagerly():
    init = (SRC / "adapters" / "providers" / "__init__.py").read_text(encoding="utf-8")
    assert "openai_compat" not in init


# --- Gemini native adapter: standard-library HTTP, no SDK
# (ADR-0043). -----------------------------------------

GEMINI = SRC / "adapters" / "providers" / "gemini_native.py"
STDLIB_HTTP = {"urllib.request", "http.client"}
HTTP_ALLOWED = {
    GEMINI,
    # Pre-existing (golden dataset, ADR-0028): the Hugging Face token check.
    SRC / "wiring" / "db_ingest.py",
    # Decision router R5 (ADR-XXXX (system-one-decision-router) point 7): the
    # read-only Hugging Face client that pins router model files; never on the
    # request path (scripts/fetch_router_assets.py only).
    SRC / "adapters" / "routers" / "hub.py",
}
NOT_DECLARED = {"google", "httpx", "requests", "aiohttp", "urllib3"}
"""Gemini SDK and HTTP clients that are not declared dependencies."""


def _dotted(tree: ast.AST) -> set[str]:
    """Imported module names in full, ``from a import b`` also as ``a.b``."""
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
            found |= {f"{node.module}.{a.name}" for a in node.names}
    return found


def test_stdlib_http_only_in_the_gemini_adapter():
    offenders = [
        path.relative_to(SRC).as_posix()
        for path in SRC.rglob("*.py")
        if path not in HTTP_ALLOWED
        and _dotted(ast.parse(path.read_text(encoding="utf-8"))) & STDLIB_HTTP
    ]
    assert offenders == []


def test_the_gemini_adapter_uses_stdlib_http_and_no_sdk():
    tree = ast.parse(GEMINI.read_text(encoding="utf-8"))
    assert "urllib.request" in _dotted(tree)
    assert not _roots(tree) & (NOT_DECLARED | LIVE_LIBRARIES)


# Decision router (TODO-18, owner 2026-11-03): httpx is declared in the
# router-local extra and imported only by the router's two HTTP adapters
# (tests/architecture/test_router_imports.py holds that rule).
HTTPX_DECLARED_FOR = {
    SRC / "adapters" / "routers" / "systemone_http.py",
    SRC / "adapters" / "routers" / "jev_metis.py",
}


def _declared(package: str) -> bool:
    import tomllib  # noqa: PLC0415

    project = tomllib.loads(
        (SRC.parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]
    specs = list(project.get("dependencies", []))
    for extra in project.get("optional-dependencies", {}).values():
        specs += extra
    return any(s.split(">")[0].split("=")[0].split("<")[0] == package for s in specs)


def test_no_gemini_sdk_or_undeclared_http_client_anywhere():
    assert _declared("httpx")
    offenders = [
        path.relative_to(SRC).as_posix()
        for path in SRC.rglob("*.py")
        if _roots(ast.parse(path.read_text(encoding="utf-8")))
        & (NOT_DECLARED - {"httpx"} if path in HTTPX_DECLARED_FOR else NOT_DECLARED)
    ]
    assert offenders == []


def test_the_providers_package_does_not_import_the_gemini_adapter_eagerly():
    init = (SRC / "adapters" / "providers" / "__init__.py").read_text(encoding="utf-8")
    assert "gemini_native" not in init
