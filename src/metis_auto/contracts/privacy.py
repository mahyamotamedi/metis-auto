"""Static inspection of privacy classes (contracts.md §2.2, QA-PRIV).

Reads only the field metadata declared with ``field()``; it never looks at
values. Used by tests now and by the event recorder (CMP-03) in Stage 5.
"""

from __future__ import annotations

from typing import Annotated, Any, get_args, get_origin

from pydantic import BaseModel

from ._base import Privacy, privacy_of


def _model_types(annotation: Any) -> list[type[BaseModel]]:
    """Every pydantic model class reachable inside a type annotation."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    origin = get_origin(annotation)
    if origin is None:
        return []
    args = get_args(annotation)
    if origin is Annotated:
        args = args[:1]
    found: list[type[BaseModel]] = []
    for arg in args:
        found.extend(_model_types(arg))
    return found


def iter_fields(
    model: type[BaseModel], parent: Privacy | None = None, prefix: str = ""
) -> list[tuple[str, Privacy | None]]:
    """``(path, effective privacy)`` for every field, recursing into models.

    ``INHERIT`` resolves to the enclosing field's class. Recursion stops at
    CONTENT fields: everything under them is content.
    """
    out: list[tuple[str, Privacy | None]] = []
    seen: set[tuple[type[BaseModel], Privacy | None]] = set()

    def walk(cls: type[BaseModel], inherited: Privacy | None, path: str) -> None:
        if (cls, inherited) in seen:
            return
        seen.add((cls, inherited))
        for name, info in cls.model_fields.items():
            declared = privacy_of(cls, name)
            effective = inherited if declared is Privacy.INHERIT else declared
            here = f"{path}{name}"
            out.append((here, effective))
            if effective is Privacy.CONTENT:
                continue
            for sub in _model_types(info.annotation):
                walk(sub, effective, f"{here}.")

    walk(model, parent, prefix)
    return out


def content_paths(model: type[BaseModel]) -> list[str]:
    """Field paths whose effective privacy class is CONTENT."""
    return [path for path, p in iter_fields(model) if p is Privacy.CONTENT]


def unclassified_fields(model: type[BaseModel]) -> list[str]:
    """Fields declared without a privacy class (every field must have one)."""
    missing = []
    for name in model.model_fields:
        if privacy_of(model, name) is None:
            missing.append(f"{model.__name__}.{name}")
    return missing
