"""Sample-file loader (CMP-18; contracts.md §4).

Responsibility: read ``data/sample_data/raw/`` (read-only) and yield generic
``Session``s. All sample quirks stop here:
- role ``bot`` → ``assistant``; any other role is an error;
- category → opaque stratum ID; session ID → keyed ``session_ref`` (both via
  the injected ``opaque_ref``, so this module holds no fingerprint key);
- empty or whitespace-only values → absent (O-4);
- null ``model`` / ``provider`` / ``instructions`` → unknown, reason
  ``not_in_log`` (Q-25: in the sample they are null together);
- an optional key missing from a message (``rag``, ``input``, ``attachments``;
  in the sample the answer-side ``model`` / ``provider`` / ``instructions``
  keys are always there) → **absent** by default: these keys appear only
  when present (owner decision Q-37, 2026-10-19; A-61). ``missing_key =
  "unknown"`` (reason ``key_missing``) is the conservative alternative,
  still reported beside it; runs record which. Nulls are not affected;
- attachment ``contentType`` → modality (``IMAGE`` → image, else other); the
  ``content`` string becomes the locator (content class, never inspected);
- possibly truncated retrieved context → ``DataQualityFlag`` on the message
  (component ``retrieved``, flag ``possibly_truncated``). Detected without a
  constant: a value counts as a ceiling when the dataset-wide maximum of the
  joined context length, or of one item's length, is reached by at least
  ``plateau_min_count`` records (A-14);
- ``session_len``, ``user_turns``, ``bot_turns`` are ignored (derivable).

Re-implemented and tested; never taken from the sample-EDA helpers
(ADR-0008). Implements ``ports.DataSource``. Built by: wiring, with a path
from settings and ``opaque_ref`` from the fingerprinter.
Status: implemented (pulled forward from Stage 9 into Stage 8).
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from metis_auto.contracts import (
    AttachmentRef,
    Component,
    ComponentName,
    DataQualityFlag,
    LoggedMessage,
    Modality,
    Name,
    RetrievedContext,
    RetrievedItem,
    Role,
    Session,
)

OpaqueRef = Callable[[str, str], str]
"""``(purpose, raw_id) -> opaque Identifier``; wiring passes a keyed
fingerprint (ADR-0015) so raw dataset IDs never leave the loader."""

MissingKey = Literal["unknown", "absent"]
ROLES = {"user": Role.USER, "bot": Role.ASSISTANT}
MODALITIES = {"IMAGE": Modality.IMAGE}
NOT_IN_LOG = "not_in_log"
KEY_MISSING = "key_missing"
JOIN = "\n"
"""Separator used only to measure the joined context length."""


class SampleFormatError(ValueError):
    """The file does not have the sample's shape (no content in the message)."""


class SampleDataSource:
    def __init__(
        self,
        path: Path,
        opaque_ref: OpaqueRef,
        *,
        missing_key: MissingKey = "absent",
        plateau_min_count: int = 3,
    ) -> None:
        if missing_key not in ("unknown", "absent"):
            raise ValueError("missing_key is 'unknown' or 'absent'")
        self._path = Path(path)
        self._ref = opaque_ref
        self._missing = missing_key
        self._plateau_min = plateau_min_count

    @property
    def dataset(self) -> Name:
        return "sample_v1"

    @property
    def missing_key(self) -> MissingKey:
        return self._missing

    def sessions(self) -> Iterator[Session]:
        raw = self._read()
        ceilings = _ceilings(raw, self._plateau_min)
        for category in raw:
            stratum = self._ref("stratum", str(category["category"]))
            for s in category["sessions"]:
                yield Session(
                    session_ref=self._ref("session_ref", str(s["session_id"])),
                    dataset=self.dataset,
                    stratum=stratum,
                    logged_created_at=_time(s.get("created_at")),
                    messages=tuple(
                        self._message(i, m, ceilings)
                        for i, m in enumerate(s["messages"])
                    ),
                )

    def _read(self) -> list[dict[str, Any]]:
        with self._path.open(encoding="utf-8") as handle:  # read-only
            data = json.load(handle)
        if not isinstance(data, list) or not all(
            isinstance(c, dict) and "sessions" in c and "category" in c for c in data
        ):
            raise SampleFormatError("expected a list of {category, sessions}")
        return data

    def _missing_component(self) -> Component:
        if self._missing == "absent":
            return Component.absent()
        return Component.unknown(KEY_MISSING)

    def _optional(self, m: Mapping[str, Any], key: str, convert) -> Component:
        """Missing key → the configured treatment; null → unknown
        (``not_in_log``); empty → absent (O-4); else present."""
        if key not in m:
            return self._missing_component()
        value = m[key]
        if value is None:
            return Component.unknown(NOT_IN_LOG)
        converted = convert(value)
        return Component.absent() if converted is None else Component.present(converted)

    def _message(
        self, position: int, m: Mapping[str, Any], ceilings: _Ceilings
    ) -> LoggedMessage:
        role = m.get("role")
        if role not in ROLES:
            raise SampleFormatError(f"message {position}: unknown role")
        fields: dict[str, Any] = dict(
            position=position,
            role=ROLES[role],
            text=str(m.get("content") or ""),
            logged_timestamp=_time(m.get("timestamp")),
        )
        if role == "bot":  # answer-side metadata (contracts.md §4)
            fields["model_label"] = self._optional(m, "model", _text)
            fields["provider_label"] = self._optional(m, "provider", _text)
            fields["instructions"] = self._optional(m, "instructions", _text)
            fields["retrieved"] = self._optional(m, "rag", _retrieved)
            fields["structured_input"] = self._optional(m, "input", _structured)
            fields["attachments"] = Component.absent()  # answers carry none
        else:
            fields["attachments"] = self._optional(m, "attachments", _attachments)
            for key in ("model_label", "provider_label", "instructions"):
                fields[key] = Component.absent()  # not a user-side field
            fields["retrieved"] = Component.absent()
            fields["structured_input"] = Component.absent()
        if role == "bot":
            fields["quality_flags"] = ceilings.flags(m)
        return LoggedMessage(**fields)


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        raise SampleFormatError("expected a string")
    return value if value.strip() else None


def _retrieved(value: Any) -> RetrievedContext | None:
    if not isinstance(value, Mapping):
        raise SampleFormatError("rag: expected an object")
    items = tuple(
        RetrievedItem(text=t)
        for t in value.get("context") or ()
        if isinstance(t, str) and t.strip()
    )
    if not items:
        return None
    query = value.get("query")
    q = (
        Component.present(query)
        if isinstance(query, str) and query.strip()
        else Component[str].absent()
        if "query" in value
        else Component[str].unknown(KEY_MISSING)
    )
    return RetrievedContext(items=items, query=q)


def _structured(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        raise SampleFormatError("input: expected an object")
    return dict(value) if value else None


def _attachments(value: Any) -> tuple[AttachmentRef, ...] | None:
    if not isinstance(value, list):
        raise SampleFormatError("attachments: expected a list")
    refs = tuple(
        AttachmentRef(
            modality=MODALITIES.get(str(a.get("contentType", "")), Modality.OTHER),
            locator=a.get("content") or None,
        )
        for a in value
        if isinstance(a, Mapping)
    )
    return refs or None


def _time(value: Any) -> datetime | None:
    """Naive timestamp (A-06); an aware value is an error, not converted."""
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is not None:
        raise SampleFormatError("expected a naive timestamp")
    return parsed


class _Ceilings:
    """Plateau values of retrieved-context length (A-14), found in the data."""

    def __init__(self, joined: int | None, item: int | None) -> None:
        self.joined = joined
        self.item = item

    def flags(self, m: Mapping[str, Any]) -> tuple[DataQualityFlag, ...]:
        texts = _context_texts(m)
        if not texts:
            return ()
        at_ceiling = (
            self.joined is not None and len(JOIN.join(texts)) == self.joined
        ) or (self.item is not None and any(len(t) == self.item for t in texts))
        if not at_ceiling:
            return ()
        return (
            DataQualityFlag(
                component=ComponentName.RETRIEVED, flag="possibly_truncated"
            ),
        )


def _context_texts(m: Mapping[str, Any]) -> list[str]:
    rag = m.get("rag")
    if not isinstance(rag, Mapping):
        return []
    return [t for t in rag.get("context") or () if isinstance(t, str) and t.strip()]


def _plateau(lengths: list[int], min_count: int) -> int | None:
    if not lengths:
        return None
    top = max(lengths)
    return top if Counter(lengths)[top] >= min_count else None


def _ceilings(raw: list[dict[str, Any]], min_count: int) -> _Ceilings:
    joined: list[int] = []
    items: list[int] = []
    for category in raw:
        for s in category["sessions"]:
            for m in s["messages"]:
                texts = _context_texts(m)
                if texts:
                    joined.append(len(JOIN.join(texts)))
                    items.extend(len(t) for t in texts)
    return _Ceilings(_plateau(joined, min_count), _plateau(items, min_count))
