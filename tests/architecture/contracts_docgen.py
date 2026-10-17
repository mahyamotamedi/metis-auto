"""Generate docs/architecture/contracts_reference.md from the contract code.

The field tables are generated so they cannot drift from the models. The
narrative (purpose, producers, consumers, versioning) is hand-written in
contracts.md. ``test_contracts_reference.py`` fails if the file is stale.

Regenerate:  python tests/architecture/contracts_docgen.py
"""

from __future__ import annotations

import importlib
import inspect
import sys
from enum import Enum
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUTPUT = REPO / "docs" / "architecture" / "contracts_reference.md"

# Module order follows the request lifecycle, then replay and evaluation.
MODULES = [
    "_base",
    "request",
    "tokens",
    "accounting",
    "measurement",
    "features",
    "reference_data",
    "routing",
    "caching",
    "context",
    "model_io",
    "attempts",
    "response",
    "events",
    "replay",
    "evaluation",
]

HEADER = """\
# Contract Field Reference (generated)

**Do not edit by hand.** Generated from `src/metis_auto/contracts/` by
`tests/architecture/contracts_docgen.py`; a test fails when it is stale.
Design, producers, consumers, and versioning: [contracts.md](contracts.md).

Columns: **Req.** = required (no default). **Privacy** = the field's class
([contracts.md §2.2](contracts.md#22-privacy-classes)); `inherit` takes the
class of the enclosing field. Types are shown as written in the source.
"""


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _first_line(doc: str | None) -> str:
    return (inspect.cleandoc(doc).split("\n\n")[0].replace("\n", " ")) if doc else ""


def _model_section(cls) -> list[str]:
    from metis_auto.contracts._base import privacy_of

    lines = [f"### `{cls.__name__}`", ""]
    summary = _first_line(cls.__doc__)
    if summary:
        lines += [summary, ""]
    lines += [
        "| Field | Type | Req. | Privacy | Description |",
        "|---|---|---|---|---|",
    ]
    annotations = {}
    for base in reversed(cls.__mro__):
        annotations.update(getattr(base, "__annotations__", {}))
    for name, info in cls.model_fields.items():
        privacy = privacy_of(cls, name)
        kind = annotations.get(name, info.annotation)
        type_text = (
            kind if isinstance(kind, str) else getattr(kind, "__name__", str(kind))
        )
        required = "yes" if info.is_required() else ""
        lines.append(
            f"| `{name}` | `{_cell(type_text)}` | {required} "
            f"| {privacy.value if privacy else '**missing**'} "
            f"| {_cell(info.description or '')} |"
        )
    return lines + [""]


def _enum_section(cls) -> list[str]:
    values = ", ".join(f"`{member.value}`" for member in cls)
    summary = _first_line(cls.__doc__) if cls.__doc__ != Enum.__doc__ else ""
    text = f"- **`{cls.__name__}`**: {values}"
    return [text + (f". {summary}" if summary else "")]


def render() -> str:
    sys.path.insert(0, str(REPO / "src"))
    from metis_auto.contracts import ContractModel

    out = [HEADER]
    for short in MODULES:
        module = importlib.import_module(f"metis_auto.contracts.{short}")
        members = [
            obj
            for _, obj in inspect.getmembers(module, inspect.isclass)
            if obj.__module__ == module.__name__
        ]
        members.sort(key=lambda obj: inspect.getsourcelines(obj)[1])
        models = [
            m
            for m in members
            if issubclass(m, ContractModel) and m is not ContractModel
        ]
        enums = [m for m in members if issubclass(m, Enum)]
        if not models and not enums:
            continue
        out += [f"## `contracts.{short}`", "", _first_line(module.__doc__), ""]
        for model in models:
            out += _model_section(model)
        if enums:
            out += ["**Enumerations**", ""]
            for enum in enums:
                out += _enum_section(enum)
            out.append("")
    return "\n".join(out).rstrip() + "\n"


if __name__ == "__main__":
    OUTPUT.write_text(render(), encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(REPO)}")
