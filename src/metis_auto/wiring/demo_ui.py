"""View model for the Demo B browser UI (CMP-20; Demo milestone B).

Responsibility: turn what ``wiring.chat`` already computes into what the
Streamlit page (``scripts/demo_ui.py``) shows, with no Streamlit import and no
routing, caching, or accounting logic of its own:
- the SYNTHETIC bot presets (``config/demo/presets-synthetic.toml``);
- the live-call banner (on, off, blocked and why, stopped), from
  ``live_permission`` on the same overrides ``ChatSession`` uses;
- the cost view of a ``TurnReport`` (paid, premium estimate, % saved, the
  decomposition terms in their fixed order, as numbers) and the budget view
  (lifetime and per-run caps, the configured warning thresholds);
- the per-message details rows, a friendly text for a refused or failed
  call, and the display direction of a text (right-to-left for Persian).

Everything is content-free except ``Preset`` (synthetic texts) and
``text_direction`` (reads a text, returns only "rtl" or "ltr").
Called by: scripts/demo_ui.py, tests. Calls: settings, wiring.{chat, live,
from_settings}, contracts.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from metis_auto.contracts import DecompositionTerm, SavingsDecomposition
from metis_auto.settings import LoadedSettings, SettingsError, repo_root

from .chat import ChatSession, TurnReport
from .from_settings import live_permission
from .live import live_overrides

PRESETS_PATH = Path("config") / "demo" / "presets-synthetic.toml"

TERM_LABELS: dict[DecompositionTerm, str] = {
    DecompositionTerm.PREMIUM_BASELINE: "Premium estimate",
    DecompositionTerm.ROUTING_SAVING: "Routing",
    DecompositionTerm.COMPRESSION_SAVING: "Compression",
    DecompositionTerm.CACHE_SAVING: "Cache",
    DecompositionTerm.PROVIDER_CACHE_SAVING: "Provider cache",
    DecompositionTerm.EXTRA_COST: "Extra cost",
    DecompositionTerm.ACTUALLY_PAID: "Actually paid",
}
SAVING_TERMS = frozenset(
    {
        DecompositionTerm.ROUTING_SAVING,
        DecompositionTerm.COMPRESSION_SAVING,
        DecompositionTerm.CACHE_SAVING,
        DecompositionTerm.PROVIDER_CACHE_SAVING,
    }
)
PREMIUM_CAVEATS = (
    "The premium figure is an estimate for gpt-5.5, never a call: it assumes the "
    "premium answer has the same length, and hidden reasoning is not counted "
    "(a lower bound)."
)
DEMO_CAVEAT = (
    "Routing rules, cache sharing, and compression are placeholder demo settings, "
    "not tuned: they show the mechanism, not a measured saving."
)

# --- presets (SYNTHETIC content) ---


@dataclass(frozen=True)
class Preset:
    key: str
    title: str
    description: str
    instructions: str
    documents: tuple[str, ...]
    suggested: tuple[str, ...]
    """Example messages for the demo script (SYNTHETIC)."""


def load_presets(path: Path | None = None) -> tuple[Preset, ...]:
    """The SYNTHETIC bot presets, in file order. Every text must carry the
    ``[SYNTHETIC]`` marker, so a preset can never be mistaken for real data."""
    file = path or repo_root() / PRESETS_PATH
    data = tomllib.loads(file.read_text(encoding="utf-8"))
    presets = []
    for key, raw in data.get("presets", {}).items():
        preset = Preset(
            key=key,
            title=raw["title"],
            description=raw["description"],
            instructions=raw["instructions"].strip(),
            documents=tuple(d.strip() for d in raw["documents"]),
            suggested=tuple(raw.get("suggested", ())),
        )
        unmarked = [
            t
            for t in (preset.instructions, *preset.documents)
            if "[SYNTHETIC]" not in t
        ]
        if unmarked:
            raise ValueError(f"preset {key!r}: every text must be marked [SYNTHETIC]")
        presets.append(preset)
    return tuple(presets)


# --- text direction (display only) ---

_ARABIC_SCRIPT = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
_LATIN = re.compile(r"[A-Za-zÀ-ɏ]")
_FENCED = re.compile(r"```.*?(```|$)", re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`\n]*`")


def text_direction(text: str) -> str:
    """ "rtl" when Persian (Arabic-script) letters are at least as many as
    Latin ones, outside code; else "ltr". Display only: routing uses the
    language detector, not this."""
    prose = _INLINE_CODE.sub(" ", _FENCED.sub(" ", text))
    rtl = len(_ARABIC_SCRIPT.findall(prose))
    ltr = len(_LATIN.findall(prose))
    return "rtl" if rtl and rtl >= ltr else "ltr"


# --- live banner ---


@dataclass(frozen=True)
class LiveBanner:
    state: str
    """``off`` (fake mode), ``on``, ``blocked``, or ``stopped``."""
    title: str
    detail: str


Loader = Callable[[Mapping[str, Any]], LoadedSettings]


def live_check(load: Loader) -> tuple[bool, tuple[str, ...]]:
    """Would a live session be allowed now? Same overrides as ``ChatSession``
    (the experiment's key); the runtime's key comes from config/local.toml."""
    try:
        loaded = load(live_overrides())
    except SettingsError as exc:
        return False, (str(exc),)
    permission = live_permission(loaded)
    return permission.allowed, permission.reasons


def live_banner(
    *,
    live: bool,
    allowed: bool,
    reasons: tuple[str, ...],
    stopped: str | None = None,
) -> LiveBanner:
    if live and stopped:
        return LiveBanner(
            "stopped",
            "Live calls STOPPED for this run",
            f"{stopped}. Switch to fake mode and back to start a new run.",
        )
    if live:
        return LiveBanner(
            "on",
            "Live calls ON: real models, real money",
            "Every call goes through the spend guard and the ledger. Use only "
            "your own or SYNTHETIC messages.",
        )
    why = "; ".join(reasons) if reasons else ""
    if allowed:
        return LiveBanner(
            "off",
            "Fake mode: live calls OFF (free)",
            "Answers are canned [SYNTHETIC] text; the routing, cache, and cost "
            "numbers are real. Live mode is available on this computer.",
        )
    return LiveBanner(
        "off",
        "Fake mode: live calls OFF (free)",
        "Answers are canned [SYNTHETIC] text; the routing, cache, and cost numbers "
        f"are real. Live mode is blocked here: {why}.",
    )


def blocked_banner(reasons: tuple[str, ...] | str) -> LiveBanner:
    text = reasons if isinstance(reasons, str) else "; ".join(reasons)
    return LiveBanner(
        "blocked",
        "Live calls BLOCKED: still in fake mode",
        f"{text}. See the quickstart §4–§5 (.env and config/local.toml).",
    )


# --- cost view ---


@dataclass(frozen=True)
class CostView:
    paid: Decimal | None
    premium: Decimal | None
    saved_fraction: float | None
    terms: tuple[tuple[str, Decimal | None], ...]
    """(label, signed amount) in the fixed order: savings negative,
    extra cost positive, baseline and paid as totals."""
    messages: int
    cache_hits: int
    currency: str


def cost_view(parts: SavingsDecomposition | None) -> CostView | None:
    if parts is None:
        return None
    amounts: dict[DecompositionTerm, Decimal | None] = {}
    currency = "USD"
    for t in parts.terms:
        amounts[t.term] = t.amount.amount if t.amount is not None else None
        if t.amount is not None:
            currency = t.amount.currency
    signed = []
    for term in DecompositionTerm:
        value = amounts.get(term)
        if value is not None and term in SAVING_TERMS:
            value = -value
        signed.append((TERM_LABELS[term], value))
    paid = amounts.get(DecompositionTerm.ACTUALLY_PAID)
    premium = amounts.get(DecompositionTerm.PREMIUM_BASELINE)
    saved = (
        float((premium - paid) / premium)
        if paid is not None and premium is not None and premium > 0
        else None
    )
    return CostView(
        paid=paid,
        premium=premium,
        saved_fraction=saved,
        terms=tuple(signed),
        messages=parts.messages,
        cache_hits=parts.cache_hits,
        currency=currency,
    )


def money(value: Decimal | None, currency: str = "USD") -> str:
    return "not computed" if value is None else f"{value:.6f} {currency}"


def waterfall_rows(view: CostView) -> list[dict[str, Any]]:
    """Bars for a waterfall chart: start, end, kind (total, saving, extra).
    Not-computed terms are left out (the table shows them)."""
    rows = []
    level = Decimal(0)
    for order, (label, value) in enumerate(view.terms):
        if value is None:
            continue
        if label in (
            TERM_LABELS[DecompositionTerm.PREMIUM_BASELINE],
            TERM_LABELS[DecompositionTerm.ACTUALLY_PAID],
        ):
            start, end, kind = Decimal(0), value, "total"
            level = value
        else:
            start, end = level, level + value
            kind = "saving" if value <= 0 else "extra cost"
            level = end
        rows.append(
            {
                "order": order,
                "term": label,
                "start": float(min(start, end)),
                "end": float(max(start, end)),
                "amount": float(value),
                "kind": kind,
                "label": f"{value:+.6f}" if kind != "total" else f"{value:.6f}",
            }
        )
    return rows


# --- budget view ---


@dataclass(frozen=True)
class BudgetView:
    currency: str
    lifetime_spent: Decimal
    lifetime_cap: Decimal
    lifetime_fraction: float
    run_spent: Decimal
    run_cap: Decimal | None
    run_fraction: float | None
    warn_at: tuple[float, ...]
    crossed: float | None
    """The highest configured warning fraction reached, if any."""


def budget_view(chat: ChatSession) -> BudgetView | None:
    if chat.ledger is None:
        return None
    status = chat.ledger.status()
    warn_at = tuple(sorted(chat.loaded.settings.budget.warn_at))
    fraction = status.lifetime_fraction
    crossed = max((w for w in warn_at if fraction >= w), default=None)
    run_fraction = (
        float(status.run_spent / status.run_cap)
        if status.run_cap is not None and status.run_cap > 0
        else None
    )
    return BudgetView(
        currency=status.currency,
        lifetime_spent=status.lifetime_spent,
        lifetime_cap=status.lifetime_cap,
        lifetime_fraction=fraction,
        run_spent=status.run_spent,
        run_cap=status.run_cap,
        run_fraction=run_fraction,
        warn_at=warn_at,
        crossed=crossed,
    )


# --- per-message details ---

ROUTING_KINDS = (  # first match wins: "re-routed … re-anchored" before "anchored"
    ("served from cache", "cache"),
    ("greeting", "greeting"),
    ("re-routed", "re-routed"),
    ("stayed", "stayed"),
    ("anchored", "anchored"),
    ("per-request", "per request"),
)


def routing_kind(report: TurnReport) -> str:
    """A one-word badge for the routing decision (from the chat's label)."""
    decision = report.routing.get("decision", "")
    if report.served_by == "cache":
        return "cache"
    if not report.routing:
        return "fixed model" if report.served_by == "model" else "-"
    kind = next((k for text, k in ROUTING_KINDS if text in decision), "routed")
    if "ESCALATED" in decision:
        kind += " + escalated"
    return kind


def detail_sections(report: TurnReport) -> list[tuple[str, list[tuple[str, str]]]]:
    """(section, rows) for the expandable per-message details. Content-free."""
    r = report.routing
    model = report.model_id or "-"
    if report.served_by == "cache" and model == "demo-seed":
        model = "demo-seed (a LOGGED sample answer, shown locally, never sent)"
    sections: list[tuple[str, list[tuple[str, str]]]] = [
        (
            "Served",
            [
                ("served by", report.served_by),
                ("model", model),
                ("provider-reported model", report.provider_model or "-"),
                (
                    "status",
                    report.status + (f" ({report.failure})" if report.failure else ""),
                ),
            ],
        ),
    ]
    if r:
        sections.append(
            (
                "Routing",
                [
                    ("decision", r.get("decision", "-")),
                    ("reason code", r.get("reason_code", "-")),
                    ("target", r.get("target", "-")),
                    ("anchor before", r.get("anchor_before", "-")),
                    ("escalation chain", r.get("chain", "-")),
                    ("policy", r.get("policy", "-")),
                ],
            )
        )
    if report.features:
        f = report.features
        sections.append(
            (
                "Features",
                [
                    ("language", f.get("language", "-")),
                    ("code", f.get("code", "-")),
                    ("coding intent", f.get("coding_intent", "-")),
                    ("length bucket", f.get("length_bucket", "-")),
                    ("greeting", f.get("greeting", "-")),
                    ("earlier user turns", f.get("turn_depth", "-")),
                ],
            )
        )
    if report.cache:
        sections.append(("Cache lookups", [("lookup", c) for c in report.cache]))
    tokens = report.tokens or {}
    sections.append(
        (
            "Tokens",
            [
                ("input", tokens.get("input", "-")),
                ("cached input (provider)", tokens.get("cached_input", "-")),
                ("output", tokens.get("output", "-")),
                ("reasoning (hidden)", tokens.get("reasoning", "-")),
                ("template overhead", tokens.get("template_overhead", "-")),
            ]
            if tokens
            else [("tokens", "none: no model call")],
        )
    )
    sections.append(
        (
            "Cost",
            [
                ("cost", report.cost),
                ("cost caveats", ", ".join(report.cost_caveats) or "-"),
                ("premium estimate (gpt-5.5, never called)", report.premium_estimate),
                ("premium caveats", ", ".join(report.premium_caveats) or "-"),
            ],
        )
    )
    c = report.compression
    sections.append(
        (
            "Compression",
            [
                ("compressor", c["compressor"]),
                ("what it shortened", c["components"]),
                ("token method", c["token_method"]),
                ("time", f"{c['time_ms']} ms"),
            ]
            if c
            else [("compression", "off")],
        )
    )
    overhead = f"{report.overhead_ms:.2f} ms" if report.overhead_ms is not None else "-"
    sections.append(
        (
            "Overhead",
            [("Metis-Auto time", overhead), ("helper calls", report.overhead_cost)],
        )
    )
    return sections


def friendly_failure(report: TurnReport) -> str | None:
    """A plain-language note for a refused or failed call, or None."""
    if report.live_stopped:
        return (
            "Live calls were stopped for this run: a call failed without reporting "
            "its cost, so its estimate was charged to be safe. Switch to fake mode "
            "and back to start a new run; if it repeats, check the key and network."
        )
    if report.failure == "budget_exhausted":
        b = report.budget
        where = (
            f" (this run: {b['run_spent']} of {b['run_cap']} {b['currency']}; "
            f"lifetime: {b['lifetime_spent']} of {b['lifetime_cap']})"
            if b
            else ""
        )
        return (
            "The budget guard stopped this call before it was made: it could go "
            f"over the per-run or lifetime cap{where}. Nothing was charged. Start a "
            "new run (switch to fake and back), or ask the project owner."
        )
    if report.failure == "no_eligible_model":
        return "No model could take this message (disabled or unknown limits)."
    if report.failure:
        return f"No answer: {report.failure}."
    return None


__all__ = [
    "DEMO_CAVEAT",
    "PREMIUM_CAVEATS",
    "PRESETS_PATH",
    "BudgetView",
    "CostView",
    "LiveBanner",
    "Preset",
    "blocked_banner",
    "budget_view",
    "cost_view",
    "detail_sections",
    "friendly_failure",
    "live_banner",
    "live_check",
    "load_presets",
    "money",
    "routing_kind",
    "text_direction",
    "waterfall_rows",
]
