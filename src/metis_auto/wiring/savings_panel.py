"""The savings panel beside the chat as a view model (UI spec Stage 3, UI-L04,
UI-D01..D13, UI-G01..G04; no Streamlit, no new calculation).

Responsibility: for one chat workspace's session, hand the page what it draws:

- the existing calculations, unchanged: ``cost_view`` of the last message and
  of the session, and ``waterfall_rows`` of each (UI-R03, UI-D13: the budget
  bars and detail sections stay in the page as they were);
- the label of what is estimated and what is observed (UI-D02): in fake mode
  every cost is an estimate from token counts, and the premium baseline is
  always an estimate (ADR-0026), so both carry "est."; live mode shows the
  provider-reported cost without the tag;
- the last message's facts (UI-D05..D11): model selected and used, which of
  cache, context optimisation and routing applied, tokens with their method
  label, latency where it is measured;
- the chart rows (UI-G01..G04), only from the session's answered messages:
  cumulative actual vs premium cost, input vs output tokens per message, cost
  by model used per message, and the savings terms of the session's
  decomposition. A message whose cost or tokens were not computed is left out
  of its chart, never drawn as 0 (UI-G08); no messages, no rows.

Traceability: FR-FIN-02 (demo UI), FR-REQ-04 (unknown stays unknown),
ADR-0026 (premium baseline is an estimate), UI-D01..D13, UI-G01..G08.
Called by: scripts/demo_pages/workspace.py. Calls: wiring.demo_ui, wiring.ui_format.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from metis_auto.wiring.chat import TurnReport
from metis_auto.wiring.demo_ui import (
    CostView,
    cost_view,
    term_text,
    waterfall_rows,
)
from metis_auto.wiring.demo_workspace import ChatWorkspace, Journey
from metis_auto.wiring.ui_config import Text
from metis_auto.wiring.ui_format import fmt

LRI, PDI = "⁦", "⁩"
DASH = "—"
FIXED_REASON = "fixed_model"
"""The routing reason of a fixed model: the user's choice, not routing."""
_COUNT = re.compile(r"^\s*(\d+)\s*(?:\((.*)\))?")


def _ltr(value: object) -> str:
    return f"{LRI}{value}{PDI}"


@dataclass(frozen=True)
class Charts:
    cost_trend: tuple[dict[str, Any], ...] = ()
    tokens: tuple[dict[str, Any], ...] = ()
    by_model: tuple[dict[str, Any], ...] = ()
    breakdown: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class Facts:
    model_selected: str
    model_used: str
    routing_applied: bool
    cache_applied: bool
    context_applied: bool
    input_tokens: str
    output_tokens: str
    latency: str


@dataclass(frozen=True)
class PanelView:
    empty: bool
    title: str
    """Titles the small-screen expander: the session saving (UI-L05)."""
    message: CostView | None = None
    session: CostView | None = None
    waterfall_message: list[dict[str, Any]] = field(default_factory=list)
    waterfall_session: list[dict[str, Any]] = field(default_factory=list)
    actual_is_estimate: bool = True
    actual_label: str = ""
    premium_label: str = ""
    facts: Facts | None = None
    charts: Charts = field(default_factory=Charts)


def _tokens(text: str | None) -> tuple[int, str] | None:
    """``"123 (exact)"`` → (123, "exact"); ``"not reported"`` or ``"-"`` → None."""
    match = _COUNT.match(text or "")
    return (int(match.group(1)), match.group(2) or "") if match else None


def _model_label(report: TurnReport, t: Text) -> str:
    if report.model_id:
        return report.model_id
    return t("served_cache") if report.served_by == "cache" else DASH


def charts_for(
    reports: list[TurnReport], session: CostView | None, t: Text, *, live: bool
) -> Charts:
    actual_series = t("ws_series_actual" if live else "ws_series_actual_est")
    premium_series = t("ws_series_premium_est")
    trend: list[dict[str, Any]] = []
    tokens: list[dict[str, Any]] = []
    by_model: list[dict[str, Any]] = []
    paid_total = premium_total = 0.0
    for n, report in enumerate(reports, 1):
        view = cost_view(report.parts)
        if view is not None and view.paid is not None and view.premium is not None:
            paid_total += float(view.paid)
            premium_total += float(view.premium)
            trend.append({"n": n, "series": actual_series, "value": paid_total})
            trend.append({"n": n, "series": premium_series, "value": premium_total})
        if view is not None and view.paid is not None:
            by_model.append(
                {"n": n, "model": _model_label(report, t), "cost": float(view.paid)}
            )
        for key, series in (
            ("input", t("ws_series_input")),
            ("output", t("ws_series_output")),
        ):
            count = _tokens(report.tokens.get(key))
            if count is not None:
                tokens.append(
                    {"n": n, "series": series, "tokens": count[0], "method": count[1]}
                )
    breakdown = []
    if session is not None:
        for label, value in session.terms:
            if value is not None and value < 0:
                breakdown.append(
                    {
                        "key": label,
                        "term": term_text(label, t),
                        "amount": float(-value),
                    }
                )
    return Charts(tuple(trend), tuple(tokens), tuple(by_model), tuple(breakdown))


def facts_for(ws: ChatWorkspace, report: TurnReport, t: Text) -> Facts:
    if ws.journey == Journey.DIRECT:
        selected = _ltr(ws.preferred_model)
    else:
        selected = t("ws_selected_by_bot")
    if ws.session.live and report.overhead_ms is not None:
        latency = t("ws_latency_overhead", ms=_ltr(f"{report.overhead_ms:.0f} ms"))
    else:
        latency = t("ws_latency_not_measured")
    return Facts(
        model_selected=selected,
        model_used=_ltr(_model_label(report, t)),
        routing_applied=bool(report.routing)
        and report.routing.get("reason_code") != FIXED_REASON,
        cache_applied=report.served_by == "cache",
        context_applied=bool(report.compression),
        input_tokens=report.tokens.get("input", DASH),
        output_tokens=report.tokens.get("output", DASH),
        latency=latency,
    )


def panel_view(ws: ChatWorkspace, t: Text) -> PanelView:
    live = ws.session.live
    estimate = not live
    actual = t("actually_paid") if live else t("ws_actual_est")
    premium = t("ws_premium_est")
    answered = [r for r in ws.reports if r.parts is not None]
    if not answered:
        return PanelView(
            empty=True,
            title=t("ws_panel_saving", share=DASH),
            actual_is_estimate=estimate,
            actual_label=actual,
            premium_label=premium,
        )
    last = answered[-1]
    message = cost_view(last.parts)
    session = cost_view(last.session_parts)
    share = (
        _ltr(fmt(session.saved_fraction, "percent"))
        if session is not None and session.saved_fraction is not None
        else DASH
    )
    return PanelView(
        empty=False,
        title=t("ws_panel_saving", share=share),
        message=message,
        session=session,
        waterfall_message=waterfall_rows(message) if message else [],
        waterfall_session=waterfall_rows(session) if session else [],
        actual_is_estimate=estimate,
        actual_label=actual,
        premium_label=premium,
        facts=facts_for(ws, last, t),
        charts=charts_for(answered, session, t, live=live),
    )
