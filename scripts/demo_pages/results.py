"""Results page of the demo UI (D-2, spec UI-S07): the sprint's offline lever
results from ``reports/levers/*.json``.

A thin page over ``metis_auto.wiring.lever_view.dashboard`` (ADR-0024, spec
UI-R02): every number, label, ranking, string and colour comes from wiring or
config; this file only lays them out. Reached from the top navigation of
``scripts/demo_ui.py`` (run that file, not this one). Streamlit and Altair are
imported only here and in ``scripts/demo_ui.py`` (tested). Builds no chat and
makes no call.
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
    LANGUAGE_NAMES,
    LANGUAGES,
    chart_theme,
    load_strings,
)


def _folder() -> Path:
    injected = st.session_state.get("_test_levers_dir")  # offline tests only
    return Path(injected) if injected else LEVERS_DIR


def _table(d: Dashboard, key: str) -> None:
    rows = d.tables.get(key, ())
    if rows:
        st.dataframe(pd.DataFrame(list(rows)), hide_index=True, width="stretch")


def _axes(chart: alt.Chart) -> alt.Chart:
    theme = chart_theme()
    return chart.configure_axis(
        gridOpacity=theme.grid_opacity, domainOpacity=theme.domain_opacity
    ).configure_view(strokeOpacity=0)


def _waterfall_chart(d: Dashboard, step: StepView) -> None:
    if not step.chart:
        st.caption(d.labels["no_chart"])
        return
    colours = chart_theme().colours
    data = pd.DataFrame(list(step.chart))
    bars = (
        alt.Chart(data)
        .mark_bar(cornerRadius=3, height=16)
        .encode(
            y=alt.Y("label:N", sort=list(data["label"]), title=None),
            x=alt.X("start:Q", title=step.unit),
            x2="end:Q",
            color=alt.Color(
                "kind:N",
                scale=alt.Scale(domain=list(colours), range=list(colours.values())),
                legend=None,
            ),
            tooltip=[alt.Tooltip("label:N", title=""), alt.Tooltip("text:N", title="")],
        )
        .properties(height=alt.Step(28))
    )
    st.altair_chart(_axes(bars), width="stretch")


def _comparison_chart(d: Dashboard, step: str) -> None:
    rows = d.comparison_chart.get(step, ())
    if not rows:
        st.caption(d.labels["no_chart"])
        return
    colour = chart_theme().colours["total"]
    data = pd.DataFrame(list(rows))
    bars = (
        alt.Chart(data)
        .mark_bar(cornerRadius=3, color=colour)
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
        .properties(height=alt.Step(24))
    )
    st.altair_chart(_axes(bars), width="stretch")


def _overview(d: Dashboard) -> None:
    st.header(d.labels["overview"])
    st.caption(d.combined_note)
    for step in d.overview:
        with st.container(border=True):
            st.subheader(step.title)
            if step.options:
                st.selectbox(
                    d.labels["version_switch"],
                    step.options,
                    index=step.options.index(step.chosen),
                    key=f"res_ver_{step.step}_{d.baseline}",
                )
            if step.message:
                st.info(step.message)
            if step.cards:
                for col, card in zip(
                    st.columns(len(step.cards)), step.cards, strict=True
                ):
                    col.metric(card.label, card.text, border=True)
            if step.result_id is not None:
                st.caption(" · ".join(p for p in (step.unit, step.unit_note) if p))
                st.caption(" · ".join(p for p in (step.evidence, step.quality) if p))
            if step.waterfall is not None:
                st.markdown(f"**{d.labels['waterfall']}**")
                _waterfall_chart(d, step)
                _table(d, f"waterfall:{step.step}")


def _comparison(d: Dashboard) -> None:
    st.header(d.labels["comparison"])
    st.caption(d.labels["ranked_note"])
    for step in d.overview:
        if f"comparison:{step.step}" not in d.tables:
            continue
        st.subheader(step.title)
        _comparison_chart(d, step.step)
        _table(d, f"comparison:{step.step}")


def _cache(d: Dashboard) -> None:
    st.header(d.labels["cache_monitor"])
    _table(d, "cache")
    st.caption(d.labels["guard_reasons_none"])
    if d.gate is not None:
        st.subheader(d.labels["greeting_gate"])
        c1, c2 = st.columns(2)
        c1.metric(d.labels["saving"], d.gate.text, border=True)
        c2.metric(d.labels["gate_skipped"], d.gate.skipped_text, border=True)
        st.caption(
            " · ".join(p for p in (d.gate.version, d.gate.unit, d.gate.note) if p)
        )


def _routing(d: Dashboard) -> None:
    st.header(d.labels["routing"])
    if d.routing is None:
        st.info(d.labels["step_none"])
        return
    st.caption(d.routing.version)
    if d.routing.message:
        st.info(d.routing.message)
    _table(d, "bots")
    _table(d, "tenants")
    if d.routing.traffic_weighted_share is not None:
        st.metric(
            d.labels["traffic_weighted_share"],
            d.routing.traffic_weighted_text,
            border=True,
        )
    if d.routing.caveats:
        with st.expander(d.labels["caveats"]):
            for caveat in d.routing.caveats:
                st.markdown(f"- {caveat}")


def page() -> None:
    strings = load_strings()
    lang = st.session_state.get("res_lang") or LANGUAGES[0]
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
        st.segmented_control(
            d.labels["language"],
            LANGUAGES,
            default=LANGUAGES[0],
            required=True,
            format_func=LANGUAGE_NAMES.get,
            key="res_lang",
        )
        st.title(d.labels["title"])
        st.caption(d.labels["subtitle"])
        st.caption(d.labels["results_not_toggles"])
        if lang == "fa" and not strings.persian_reviewed:
            st.caption(d.labels["persian_note"])
        if d.skipped_note:
            st.caption(d.skipped_note)
        if d.empty:
            st.info(d.empty_message, icon=":material/inbox:")
            return
        baselines = [o.key for o in d.baselines]
        labels = {o.key: o.label for o in d.baselines}
        slices = {o.key: o.label for o in d.slices}
        c1, c2 = st.columns(2)
        c1.selectbox(
            d.labels["baseline"],
            baselines,
            index=baselines.index(d.baseline),
            format_func=labels.get,
            key="res_baseline",
        )
        c2.selectbox(
            d.labels["slice"],
            list(slices),
            index=list(slices).index(d.slice_name),
            format_func=slices.get,
            key=f"res_slice_{d.baseline}",
        )
        _overview(d)
        _comparison(d)
        _cache(d)
        _routing(d)


page()
