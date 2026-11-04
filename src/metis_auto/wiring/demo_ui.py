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

Language (UI Stage 2b, ADR-0052 Amendment 1): every visible text comes from
``config/demo/ui_strings.toml`` through an optional translator ``t``; without
one the text is English, as before. Only the texts move: the calculations, the
terms and their order are unchanged. ``term_text`` and ``routing_kind_text``
translate a term label or a badge at display time, so ``cost_view`` and
``waterfall_rows`` keep their English keys.

Called by: scripts/demo_ui.py, tests. Calls: settings, wiring.{chat, live,
from_settings, ui_config}, contracts.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from metis_auto.adapters.system.ledger import LedgerError
from metis_auto.contracts import DecompositionTerm, SavingsDecomposition
from metis_auto.settings import LoadedSettings, SettingsError, repo_root

from .chat import ChatSession, TurnReport
from .from_settings import live_permission
from .live import live_overrides
from .ui_config import STRINGS_PATH, Text, load_strings, translator

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
TERM_KEYS: dict[str, str] = {
    label: "term_" + label.lower().replace(" ", "_") for label in TERM_LABELS.values()
}
"""English term label → its key in the strings table."""
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


def _english() -> Text:
    return translator(load_strings(repo_root() / STRINGS_PATH), "en")


def term_text(label: str, t: Text) -> str:
    """A decomposition term (``CostView.terms`` label) in ``t``'s language."""
    return t(TERM_KEYS[label]) if label in TERM_KEYS else label


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
    t: Text | None = None,
) -> LiveBanner:
    """The banner's state, title and detail. ``reasons`` and ``stopped`` come
    from the settings and the pipeline as they are (not translated)."""
    t = t or _english()
    if live and stopped:
        state, detail = "stopped", t("banner_detail_stopped", stopped=stopped)
    elif live:
        state, detail = "on", t("banner_detail_on")
    elif allowed:
        state, detail = "off", t("banner_detail_off_allowed")
    else:
        why = "; ".join(reasons) if reasons else ""
        state, detail = "off", t("banner_detail_off_blocked", why=why)
    return LiveBanner(state, t(f"banner_{state}"), detail)


def blocked_banner(
    reasons: tuple[str, ...] | str, *, t: Text | None = None
) -> LiveBanner:
    t = t or _english()
    text = reasons if isinstance(reasons, str) else "; ".join(reasons)
    return LiveBanner(
        "blocked", t("banner_blocked"), t("banner_detail_blocked", text=text)
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
    """Plain-text amount (English; the page formats with ``ui_format.fmt``)."""
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


def header_budget(chat: ChatSession) -> BudgetView | None:
    """``budget_view`` for the header, in both modes (UI Stage 2b): None when
    no budget is configured or the ledger cannot be read, which the header
    shows as unknown, never as a number."""
    try:
        return budget_view(chat)
    except LedgerError:
        return None


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


def routing_kind_text(kind: str, t: Text) -> str:
    """A ``routing_kind`` badge in ``t``'s language (``-`` stays)."""
    base, plus, _ = kind.partition(" + ")
    if base == "-":
        return base
    text = t("rkind_" + base.replace("-", "_").replace(" ", "_"))
    return f"{text} + {t('rkind_escalated')}" if plus else text


def served_text(served_by: str, t: Text) -> str:
    """``model``, ``cache`` or ``none`` in ``t``'s language."""
    key = f"served_{served_by}"
    return t(key) if served_by in ("model", "cache", "none") else served_by


def detail_sections(
    report: TurnReport, *, t: Text | None = None
) -> list[tuple[str, list[tuple[str, str]]]]:
    """(section, rows) for the expandable per-message details. Content-free.
    Values come from the report as they are (model ids, states, amounts)."""
    t = t or _english()
    r = report.routing
    model = report.model_id or "-"
    if report.served_by == "cache" and model == "demo-seed":
        model = t("det_seed_model")
    sections: list[tuple[str, list[tuple[str, str]]]] = [
        (
            t("det_sec_served"),
            [
                (t("det_served_by"), served_text(report.served_by, t)),
                (t("det_model"), model),
                (t("det_provider_model"), report.provider_model or "-"),
                (
                    t("det_status"),
                    report.status + (f" ({report.failure})" if report.failure else ""),
                ),
            ],
        ),
    ]
    if r:
        sections.append(
            (
                t("det_sec_routing"),
                [
                    (t("det_decision"), r.get("decision", "-")),
                    (t("det_reason_code"), r.get("reason_code", "-")),
                    (t("det_target"), r.get("target", "-")),
                    (t("routing_tier"), r.get("tier", "-")),
                    *(
                        [(t("routing_safe_tier"), r["safe_tier_note"])]
                        if "safe_tier_note" in r
                        else []
                    ),
                    (t("det_anchor_before"), r.get("anchor_before", "-")),
                    (t("det_chain"), r.get("chain", "-")),
                    (t("det_policy"), r.get("policy", "-")),
                ],
            )
        )
    if report.features:
        f = report.features
        sections.append(
            (
                t("det_sec_features"),
                [
                    (t("det_language"), f.get("language", "-")),
                    (t("det_code"), f.get("code", "-")),
                    (t("det_coding_intent"), f.get("coding_intent", "-")),
                    (t("det_length_bucket"), f.get("length_bucket", "-")),
                    (t("det_greeting"), f.get("greeting", "-")),
                    (t("det_turn_depth"), f.get("turn_depth", "-")),
                ],
            )
        )
    if report.cache:
        sections.append(
            (t("det_sec_cache"), [(t("det_lookup"), c) for c in report.cache])
        )
    tokens = report.tokens or {}
    sections.append(
        (
            t("det_sec_tokens"),
            [
                (t("det_input"), tokens.get("input", "-")),
                (t("det_cached_input"), tokens.get("cached_input", "-")),
                (t("det_output"), tokens.get("output", "-")),
                (t("det_reasoning"), tokens.get("reasoning", "-")),
                (t("det_template_overhead"), tokens.get("template_overhead", "-")),
            ]
            if tokens
            else [(t("det_tokens"), t("det_no_call"))],
        )
    )
    sections.append(
        (
            t("det_sec_cost"),
            [
                (t("det_cost"), report.cost),
                (t("det_cost_caveats"), ", ".join(report.cost_caveats) or "-"),
                (t("det_premium"), report.premium_estimate),
                (t("det_premium_caveats"), ", ".join(report.premium_caveats) or "-"),
            ],
        )
    )
    c = report.compression
    sections.append(
        (
            t("det_sec_compression"),
            [
                (t("det_compressor"), c["compressor"]),
                (t("det_shortened"), c["components"]),
                (t("det_token_method"), c["token_method"]),
                (t("det_time"), f"{c['time_ms']} ms"),
            ]
            if c
            else [(t("det_compression"), t("det_off"))],
        )
    )
    d = report.dedup
    if d:  # only when the demo's dedup ran for this answer
        sections.append(
            (
                t("dedup_title"),
                [
                    (
                        t("dedup_row_chunks"),
                        f"{d['items_removed']} / {d['items_total']}",
                    ),
                    (t("dedup_row_tokens"), d["tokens_removed"]),
                    (t("dedup_row_saving"), d.get("saving", "-")),
                ],
            )
        )
    overhead = f"{report.overhead_ms:.2f} ms" if report.overhead_ms is not None else "-"
    sections.append(
        (
            t("det_sec_overhead"),
            [
                (t("det_overhead_time"), overhead),
                (t("det_helper_calls"), report.overhead_cost),
            ],
        )
    )
    return sections


def friendly_failure(report: TurnReport, *, t: Text | None = None) -> str | None:
    """A plain-language note for a refused or failed call, or None."""
    t = t or _english()
    if report.live_stopped:
        return t("fail_stopped")
    if report.failure == "budget_exhausted":
        b = report.budget
        where = (
            t(
                "fail_budget_where",
                rs=b["run_spent"],
                rc=b["run_cap"],
                c=b["currency"],
                ls=b["lifetime_spent"],
                lc=b["lifetime_cap"],
            )
            if b
            else ""
        )
        return t("fail_budget", where=where)
    if report.failure == "no_eligible_model":
        return t("fail_no_model")
    if report.failure:
        return t("fail_other", failure=report.failure)
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
    "header_budget",
    "live_banner",
    "live_check",
    "load_presets",
    "money",
    "routing_kind",
    "routing_kind_text",
    "served_text",
    "term_text",
    "text_direction",
    "waterfall_rows",
]
