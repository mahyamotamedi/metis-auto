"""Results page of the demo UI (D-2, spec UI-S07): the sprint's offline lever
results from ``reports/levers/*.json``, in the Metis analytics style
(screenshots 3 to 6: a filter row, KPI cards, charts in cards).

A thin page over ``metis_auto.wiring.lever_view.dashboard`` (ADR-0024, spec
UI-R02): every number, label, ranking, string and colour comes from wiring or
config; this file only lays them out. Theme and language come from the session
(set by the header in ``scripts/demo_ui.py``; run that file, not this one).
Streamlit and Altair are imported only here and in ``scripts/demo_ui.py``
(tested). Builds no chat and makes no call.
"""

from __future__ import annotations

from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from metis_auto.wiring.lever_view import (
    DEFAULT_BASELINE,
    LEVERS_DIR,
    RESULT_SLICE,
    STEPS,
    Dashboard,
    StepView,
    dashboard,
    has_final,
    load_view,
    tenant_cap,
)
from metis_auto.wiring.ui_config import (
    DEFAULT_LANGUAGE,
    DEFAULT_THEME,
    load_strings,
    load_theme,
)
from metis_auto.wiring.ui_style import (
    altair_config,
    card_title_html,
    empty_state_html,
    labelled,
    ltr,
    section_title_html,
)


def _folder() -> Path:
    injected = st.session_state.get("_test_levers_dir")  # offline tests only
    return Path(injected) if injected else LEVERS_DIR


def _theme():
    return load_theme(st.session_state.get("ui_theme") or DEFAULT_THEME)


def _chart(chart: alt.TopLevelMixin, d: Dashboard) -> None:
    """Every chart gets the theme's Altair config (UI-G05..G07)."""
    config = altair_config(_theme(), d.lang)
    st.altair_chart(chart.configure(**config), width="stretch", theme=None)


def _table(d: Dashboard, key: str, *, folded: bool = True) -> None:
    rows = d.tables.get(key, ())
    if not rows:
        return
    if folded:
        with st.expander(d.labels["show_table"]):
            st.table(pd.DataFrame(list(rows)).set_index(list(rows[0])[0]))
    else:
        st.table(pd.DataFrame(list(rows)).set_index(list(rows[0])[0]))


def _no_chart(d: Dashboard) -> None:
    st.html(empty_state_html("bar_chart", d.labels["no_chart"]))


def _waterfall_chart(d: Dashboard, step: StepView) -> None:
    if not step.chart:
        _no_chart(d)
        return
    kinds = _theme().kinds
    data = pd.DataFrame(list(step.chart))
    bars = (
        alt.Chart(data)
        .mark_bar(cornerRadius=3, height=18)
        .encode(
            y=alt.Y("label:N", sort=list(data["label"]), title=None),
            x=alt.X("start:Q", title=step.unit),
            x2="end:Q",
            color=alt.Color(
                "kind:N",
                scale=alt.Scale(domain=list(kinds), range=list(kinds.values())),
                legend=None,
            ),
            tooltip=[alt.Tooltip("label:N", title=""), alt.Tooltip("text:N", title="")],
        )
        .properties(height=240)
    )
    _chart(bars, d)


def _block_chart(d: Dashboard, step: StepView) -> None:
    """Stacked bars, before and after by cost block (UI-G03)."""
    if not step.blocks:
        _no_chart(d)
        return
    data = pd.DataFrame(list(step.blocks))
    bars = (
        alt.Chart(data)
        .mark_bar(size=56)
        .encode(
            x=alt.X(
                "stage:N",
                sort=list(dict.fromkeys(data["stage"])),
                title=None,
                axis=alt.Axis(labelAngle=0),
            ),
            y=alt.Y("value:Q", title=None, stack="zero"),
            color=alt.Color(
                "block:N", sort=list(dict.fromkeys(data["block"])), title=None
            ),
            order=alt.Order("order:Q"),
            tooltip=[
                alt.Tooltip("stage:N", title=""),
                alt.Tooltip("block:N", title=""),
                alt.Tooltip("text:N", title=""),
            ],
        )
        .properties(height=240)
    )
    _chart(bars, d)


def _breakdown_chart(d: Dashboard, step: StepView) -> None:
    """A thick donut with hairline gaps: the cost left and each saving (UI-G04)."""
    if not step.breakdown:
        _no_chart(d)
        return
    data = pd.DataFrame(list(step.breakdown))
    donut = (
        alt.Chart(data)
        .mark_arc(innerRadius=58, outerRadius=96)
        .encode(
            theta=alt.Theta("value:Q", stack=True),
            color=alt.Color(
                "part:N", sort=list(data["part"]), title=None, legend=alt.Legend()
            ),
            order=alt.Order("order:Q"),
            tooltip=[alt.Tooltip("part:N", title=""), alt.Tooltip("text:N", title="")],
        )
        .properties(height=240)
    )
    _chart(donut, d)


def _comparison_chart(d: Dashboard, step: str) -> None:
    rows = d.comparison_chart.get(step, ())
    if not rows:
        _no_chart(d)
        return
    colour = _theme().kinds["total"]
    data = pd.DataFrame(list(rows))
    bars = (
        alt.Chart(data)
        .mark_bar(color=colour, height=16)
        .encode(
            y=alt.Y("version:N", sort="-x", title=None),
            x=alt.X(
                "saving_share:Q",
                title=d.labels["saving_share"],
                axis=alt.Axis(format="%"),
            ),
            opacity=alt.condition("datum.ranked", alt.value(1.0), alt.value(0.35)),
            tooltip=[
                alt.Tooltip("version:N", title=d.labels["col_version"]),
                alt.Tooltip(
                    "saving_share:Q", format=".2%", title=d.labels["saving_share"]
                ),
                alt.Tooltip("status:N", title=d.labels["col_status"]),
            ],
        )
        .properties(height=alt.Step(26))
    )
    _chart(bars, d)


def _kpis(key: str, cards: list[tuple[str, str, str | None]]) -> None:
    """KPI cards in one row, equal widths (images 3 and 4): muted label, large
    value (LTR-isolated, UI-V07), optional muted caption."""
    with st.container(key=f"mx-row-{key}", horizontal=True):
        for n, (label, value, caption) in enumerate(cards):
            with st.container(key=f"mx-kpi-{key}-{n}"):
                st.metric(label, ltr(value))
                if caption:
                    st.caption(caption)


def _step(d: Dashboard, step: StepView) -> None:
    with st.container(
        key=f"mx-sec-{step.step}", horizontal=True, vertical_alignment="center"
    ):
        st.html(section_title_html(step.title), width="content")
        if step.options:
            st.selectbox(
                d.labels["version_switch"],
                step.options,
                index=step.options.index(step.chosen),
                key=f"res_ver_{step.step}_{d.baseline}",
                label_visibility="collapsed",
                format_func=lambda v: labelled(d.labels["version_switch"], v),
                width=560,
            )
    if step.message:
        st.info(step.message, icon=":material/info:")
    if step.cards:
        captions = {"baseline_cost": step.unit, "saving": step.unit_note}
        _kpis(
            f"step-{step.step}",
            [(c.label, c.text, captions.get(c.key)) for c in step.cards],
        )
    if step.result_id is not None:
        st.caption(" · ".join(p for p in (step.evidence, step.quality) if p))
    if step.waterfall is None:
        return
    wide, narrow, small = st.columns([5, 3, 3], gap="medium")
    with wide, st.container(key=f"mx-card-wf-{step.step}"):
        st.html(card_title_html(d.labels["waterfall"]))
        _waterfall_chart(d, step)
        _table(d, f"waterfall:{step.step}")
    with narrow, st.container(key=f"mx-card-blocks-{step.step}"):
        st.html(card_title_html(d.labels["chart_blocks"]))
        _block_chart(d, step)
    with small, st.container(key=f"mx-card-donut-{step.step}"):
        st.html(card_title_html(d.labels["chart_breakdown"]))
        _breakdown_chart(d, step)


def _comparison(d: Dashboard) -> None:
    st.header(d.labels["comparison"])
    st.caption(d.labels["ranked_note"])
    for step in d.overview:
        if f"comparison:{step.step}" not in d.tables:
            continue
        with st.container(key=f"mx-card-cmp-{step.step}"):
            st.html(card_title_html(step.title))
            _comparison_chart(d, step.step)
            _table(d, f"comparison:{step.step}")


def _cache(d: Dashboard) -> None:
    st.header(d.labels["cache_monitor"])
    with st.container(key="mx-card-cache"):
        if d.tables.get("cache"):
            _table(d, "cache", folded=False)
        else:
            st.html(empty_state_html("cached", d.labels["step_none"]))
        st.caption(d.labels["guard_reasons_none"])
    if d.gate is not None:
        st.subheader(d.labels["greeting_gate"])
        _kpis(
            "gate",
            [
                (d.labels["saving"], d.gate.text, d.gate.unit),
                (d.labels["gate_skipped"], d.gate.skipped_text, None),
            ],
        )
        st.caption(" · ".join(p for p in (d.gate.version, d.gate.note) if p))


def _routing(d: Dashboard) -> None:
    st.header(d.labels["routing"])
    if d.routing is None:
        st.html(empty_state_html("alt_route", d.labels["step_none"]))
        return
    st.caption(d.routing.version)
    if d.routing.message:
        st.info(d.routing.message, icon=":material/info:")
    if d.routing.traffic_weighted_share is not None:
        _kpis(
            "routing",
            [
                (
                    d.labels["traffic_weighted_share"],
                    d.routing.traffic_weighted_text,
                    None,
                )
            ],
        )
    with st.container(key="mx-card-bots"):
        _table(d, "bots", folded=False)
        _table(d, "tenants", folded=False)
    if d.routing.caveats:
        with st.expander(d.labels["caveats"]):
            for caveat in d.routing.caveats:
                st.markdown(f"- {caveat}")


def page() -> None:
    strings = load_strings()
    lang = st.session_state.get("ui_lang") or DEFAULT_LANGUAGE
    folder = _folder()
    view = load_view(folder)
    baseline = st.session_state.get("res_baseline") or DEFAULT_BASELINE
    slice_name = st.session_state.get(f"res_slice_{baseline}") or RESULT_SLICE
    choices = {
        step: st.session_state.get(f"res_ver_{step}_{baseline}") for step in STEPS
    }
    d = dashboard(
        view,
        strings=strings,
        tenant_cap=tenant_cap(),
        lang=lang,
        baseline=baseline,
        slice_name=slice_name,
        choices={k: v for k, v in choices.items() if v},
        final_present=has_final(folder),
    )
    with st.container(key=f"{d.direction}-results"):
        st.title(d.labels["title"])
        notes = [d.labels["subtitle"], d.labels["results_not_toggles"]]
        if lang == "fa" and not strings.persian_reviewed:
            notes.append(d.labels["persian_note"])
        if d.skipped_note:
            notes.append(d.skipped_note)
        st.caption(" ".join(notes))
        if d.empty:
            st.html(
                empty_state_html(
                    "inbox", d.labels["empty_title"], d.labels["empty_message"]
                )
            )
            return
        baselines = [o.key for o in d.baselines]
        labels = {o.key: o.label for o in d.baselines}
        slices = {o.key: o.label for o in d.slices}
        with st.container(key="mx-filters", horizontal=True):
            st.selectbox(
                d.labels["baseline"],
                baselines,
                index=baselines.index(d.baseline),
                format_func=lambda k: labelled(d.labels["baseline"], labels[k]),
                key="res_baseline",
                label_visibility="collapsed",
                width=360,
            )
            st.selectbox(
                d.labels["slice"],
                list(slices),
                index=list(slices).index(d.slice_name),
                format_func=lambda k: labelled(d.labels["slice"], slices[k]),
                key=f"res_slice_{d.baseline}",
                label_visibility="collapsed",
                width=300,
            )
        st.header(d.labels["overview"])
        st.caption(d.combined_note)
        for step in d.overview:
            _step(d, step)
        _comparison(d)
        _cache(d)
        _routing(d)


page()
