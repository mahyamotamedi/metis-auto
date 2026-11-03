"""Decision-router libraries are imported only by their own adapter
(ADR-XXXX (system-one-decision-router)), so offline code, the runtime lock and the
Docker images never need them. ``typesafe-sdk`` is not used at all (owner decision
2026-11-02: httpx with a strict wire model). Static check (``ast``); the adapters named
here arrive in R5 and R6, and the rule holds from now on."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "metis_auto"
ROUTERS = SRC / "adapters" / "routers"

LIBRARIES_BY_ADAPTER = {
    # THX-01 in-process (extra router-local) and its optional ONNX path.
    "thx01": {ROUTERS / "thx01_local.py"},
    "onnxruntime": {ROUTERS / "thx01_local.py"},
    # The router's HTTP clients: a local /v1/systemone server (R5) and Jev via
    # Metis (R6); declared in the router-local extra (TODO-18). The live SDK has
    # its own httpx2.
    "httpx": {ROUTERS / "systemone_http.py", ROUTERS / "jev_metis.py"},
}
# torch and transformers are shared with the compression adapter (ADR-0023).
SHARED_HEAVY = {"torch", "transformers", "safetensors", "huggingface_hub"}
SHARED_ALLOWED = {
    ROUTERS / "thx01_local.py",
    SRC / "adapters" / "compressors" / "llmlingua2.py",
}
NEVER = {"typesafe", "typesafe_sdk"}


def _roots(path: Path) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


def test_router_libraries_only_in_their_adapter():
    offenders = []
    for path in SRC.rglob("*.py"):
        roots = _roots(path)
        for library, allowed in LIBRARIES_BY_ADAPTER.items():
            if library in roots and path not in allowed:
                offenders.append((path.relative_to(SRC).as_posix(), library))
        for library in roots & SHARED_HEAVY:
            if path not in SHARED_ALLOWED:
                offenders.append((path.relative_to(SRC).as_posix(), library))
    assert offenders == []


def test_typesafe_sdk_is_never_imported():
    offenders = [
        path.relative_to(SRC).as_posix()
        for path in SRC.rglob("*.py")
        if _roots(path) & NEVER
    ]
    assert offenders == []


def test_the_routers_package_imports_no_heavy_adapter_eagerly():
    init = (ROUTERS / "__init__.py").read_text(encoding="utf-8")
    code = init.split('"""', 2)[-1]
    assert "thx01_local" not in code
    assert _roots(ROUTERS / "__init__.py") & (SHARED_HEAVY | {"thx01"}) == set()


def test_the_hub_client_uses_the_standard_library_only():
    roots = _roots(ROUTERS / "hub.py")
    assert roots & (SHARED_HEAVY | {"httpx", "requests"}) == set()
