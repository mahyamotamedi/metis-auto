"""Results page of the demo UI (D-2, spec UI-S07): the sprint's offline lever
results from ``reports/levers/*.json``, in the Metis analytics style
(screenshots 3 to 6: a filter row, KPI cards, charts in cards).

Layout (UI Stage 2b, ADR-0052 Amendment 1): the filter row, then one tab per
step (Cache, Context, Routing) and a Per bot tab. Inside a tab: the version
switch with its display name and the raw id as a muted caption, the KPI row,
then charts in two columns at about 60/40 (the wider first, so on the right in
Persian), each with its legend centred below; long tables folded in
expanders labelled with a one-line summary.

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
    BOT_CHART_MAX,
    DEFAULT_BASELINE,
    LEVERS_DIR,
    RESULT_SLICE,
    STEPS,
    Card,
    Dashboard,
    StepView,
    dashboard,
    has_final,
    load_final,
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
    axis_format,
    bar_layout,
    card_title_html,
    data_list_html,
    empty_state_html,
    id_caption_html,
    labelled,
    legend_html,
    ltr,
    series_scale,
)

CHART_HEIGHT = 240
ROW_STEP = 24  # px per bar in the horizontal bar charts


def _folder() -> Path:
    injected = st.session_state.get("_test_levers_dir")  # offline tests only
    return Path(injected) if injected else LEVERS_DIR


def _theme():
    return load_theme(st.session_state.get("ui_theme") or DEFAULT_THEME)


def _chart(chart: alt.TopLevelMixin, d: Dashboard) -> None:
    """Every chart gets the theme's Altair config (UI-G05..G07)."""
    config = altair_config(_theme(), d.lang)
    st.altair_chart(chart.configure(**config), width="stretch", theme=None)


def _legend(items) -> None:
    html = legend_html(list(items))
    if html:
        st.html(html)


def _folded(d: Dashboard, key: str) -> None:
    """A long table in a collapsed expander titled with its summary line."""
    rows = d.tables.get(key, ())
    if not rows:
        return
    with st.expander(d.summaries.get(key, d.labels["show_table"]), expanded=False):
        st.table(pd.DataFrame(list(rows)).set_index(list(rows[0])[0]))


def _final(d: Dashboard) -> None:
    """The combined numbers of final.json: rows per pipeline, the winners'
    waterfall, the provisional label, the units caveat and F-2's 'other' block.
    No logic: the view model decided what to show (ADR-0024)."""
    final = d.final
    if final is None:
        return
    st.subheader(d.labels["final_title"])
    st.caption(final.status)
    st.caption(final.units_caveat)
    st.caption(final.other_text)
    rows = []
    for r in final.rows:
        row = {d.labels["final_pipeline"]: r.pipeline}
        row |= {d.labels[f"step_{s}"]: text for s, text in r.steps.items()}
        row[d.labels["final_combined"]] = r.combined
        row[d.labels["final_share"]] = r.share
        row[d.labels["final_rule"]] = (
            d.labels["unknown"]
            if r.rule_holds is None
            else d.labels["final_rule_ok" if r.rule_holds else "final_rule_broken"]
        )
        rows.append(row)
    if rows:
        st.table(pd.DataFrame(rows).set_index(d.labels["final_pipeline"]))
    if final.waterfall:
        with st.expander(
            f"{d.labels['final_waterfall']}: {final.waterfall_pipeline}",
            expanded=False,
        ):
            st.table(
                pd.DataFrame(
                    [
                        {"": w.label, d.labels["saving"]: w.amount}
                        for w in final.waterfall
                    ]
                ).set_index("")
            )


def _no_chart(d: Dashboard) -> None:
    st.html(empty_state_html("bar_chart", d.labels["no_chart"]))


def _bars_height(n: int) -> int:
    return max(CHART_HEIGHT, ROW_STEP * n)


def _hbar_axes(d: Dashboard, kind: str, title: str | None):
    """Category and value axes of a horizontal bar chart, right to left in
    Persian (``bar_layout``)."""
    layout = bar_layout(d.lang)
    y_axis = alt.Axis(labelOverlap=False, orient=layout["y_orient"], labelLimit=260)
    x_axis = alt.Axis(format=axis_format(kind))
    x_scale = alt.Scale(reverse=layout["x_reverse"])
    return y_axis, x_axis, x_scale, title


# --- charts ---------------------------------------------------------------------


def _waterfall_chart(d: Dashboard, step: StepView) -> None:
    if not step.chart:
        _no_chart(d)
        return
    kinds = _theme().kinds
    data = pd.DataFrame(list(step.chart))
    y_axis, x_axis, x_scale, title = _hbar_axes(d, "money", step.unit)
    bars = (
        alt.Chart(data)
        .mark_bar(cornerRadius=3, height=18)
        .encode(
            y=alt.Y("label:N", sort=list(data["label"]), title=None, axis=y_axis),
            x=alt.X("start:Q", title=title, axis=x_axis, scale=x_scale),
            x2="end:Q",
            color=alt.Color(
                "kind:N",
                scale=alt.Scale(domain=list(kinds), range=list(kinds.values())),
                legend=None,
            ),
            tooltip=[alt.Tooltip("label:N", title=""), alt.Tooltip("text:N", title="")],
        )
        .properties(height=CHART_HEIGHT)
    )
    _chart(bars, d)
    present = set(data["kind"])
    _legend(
        (d.labels[f"kind_{k.replace(' ', '_')}"], c)
        for k, c in kinds.items()
        if k in present
    )


def _block_chart(d: Dashboard, step: StepView, height: int) -> None:
    """Stacked bars, before and after by cost block (UI-G03)."""
    if not step.blocks:
        _no_chart(d)
        return
    data = pd.DataFrame(list(step.blocks))
    blocks = list(dict.fromkeys(data["block"]))
    domain, colours = series_scale(_theme(), blocks)
    stages = list(dict.fromkeys(data["stage"]))
    bars = (
        alt.Chart(data)
        .mark_bar(size=48)
        .encode(
            x=alt.X(
                "stage:N",
                sort=stages,
                title=None,
                axis=alt.Axis(labelAngle=0),
                scale=alt.Scale(reverse=bar_layout(d.lang)["x_reverse"]),
            ),
            y=alt.Y(
                "value:Q",
                title=step.unit,
                stack="zero",
                axis=alt.Axis(format=axis_format("money")),
            ),
            color=alt.Color(
                "block:N",
                scale=alt.Scale(domain=domain, range=colours),
                legend=None,
            ),
            order=alt.Order("order:Q"),
            tooltip=[
                alt.Tooltip("stage:N", title=""),
                alt.Tooltip("block:N", title=""),
                alt.Tooltip("text:N", title=""),
            ],
        )
        .properties(height=height)
    )
    _chart(bars, d)
    _legend(zip(domain, colours, strict=True))


def _breakdown_chart(d: Dashboard, step: StepView) -> None:
    """A thick donut with hairline gaps: the cost left and each saving (UI-G04)."""
    if not step.breakdown:
        _no_chart(d)
        return
    data = pd.DataFrame(list(step.breakdown))
    domain, colours = series_scale(_theme(), list(data["part"]))
    donut = (
        alt.Chart(data)
        .mark_arc(innerRadius=62, outerRadius=100)
        .encode(
            theta=alt.Theta("value:Q", stack=True),
            color=alt.Color(
                "part:N",
                scale=alt.Scale(domain=domain, range=colours),
                legend=None,
            ),
            order=alt.Order("order:Q"),
            tooltip=[alt.Tooltip("part:N", title=""), alt.Tooltip("text:N", title="")],
        )
        .properties(height=CHART_HEIGHT)
    )
    _chart(donut, d)
    _legend(zip(domain, colours, strict=True))


def _comparison_chart(d: Dashboard, step: str, height: int) -> None:
    """One compact horizontal bar per version, by display name (UI-R23)."""
    rows = d.comparison_chart.get(step, ())
    if not rows:
        _no_chart(d)
        return
    colour = _theme().kinds["total"]
    muted = _theme().colours["text_muted"]  # unranked: the muted gray, both themes
    data = pd.DataFrame(list(rows))
    y_axis, x_axis, x_scale, title = _hbar_axes(d, "percent", d.labels["saving_share"])
    bars = (
        alt.Chart(data)
        .mark_bar(color=colour, height=14)
        .encode(
            y=alt.Y("version:N", sort="-x", title=None, axis=y_axis),
            x=alt.X("saving_share:Q", title=title, axis=x_axis, scale=x_scale),
            color=alt.condition("datum.ranked", alt.value(colour), alt.value(muted)),
            tooltip=[
                alt.Tooltip("version:N", title=d.labels["col_version"]),
                alt.Tooltip("id:N", title=d.labels["id_caption"]),
                alt.Tooltip("text:N", title=d.labels["saving_share"]),
                alt.Tooltip("status:N", title=d.labels["col_status"]),
            ],
        )
        .properties(height=height)
    )
    _chart(bars, d)
    items = [(d.labels["legend_ranked"], colour)]
    if not all(r["ranked"] for r in rows):
        items.append((d.labels["legend_unranked"], muted))
    _legend(items)


def _share_bars(
    d: Dashboard, rows, colour_field: str | None, colours: dict[object, str]
) -> None:
    """Horizontal bars of shares by rank label (per-bot tab)."""
    data = pd.DataFrame(list(rows))
    y_axis, x_axis, x_scale, _ = _hbar_axes(d, "percent", None)
    colour = (
        alt.Color(
            f"{colour_field}:N",
            scale=alt.Scale(domain=list(colours), range=list(colours.values())),
            legend=None,
        )
        if colour_field
        else alt.value(next(iter(colours.values())))
    )
    bars = (
        alt.Chart(data)
        .mark_bar(height=14)
        .encode(
            y=alt.Y("label:N", sort=list(data["label"]), title=None, axis=y_axis),
            x=alt.X("value:Q", title=None, axis=x_axis, scale=x_scale),
            color=colour,
            tooltip=[alt.Tooltip("label:N", title=""), alt.Tooltip("text:N", title="")],
        )
        .properties(height=_bars_height(len(data)))
    )
    _chart(bars, d)


# --- blocks ---------------------------------------------------------------------


def _kpis(key: str, cards: list[tuple[str, str, str | None]]) -> None:
    """KPI cards in one row, equal widths (images 3 and 4): muted label, large
    value (LTR-isolated, UI-V07), optional muted caption."""
    with st.container(key=f"mx-row-{key}", horizontal=True):
        for n, (label, value, caption) in enumerate(cards):
            with st.container(key=f"mx-kpi-{key}-{n}"):
                st.metric(label, ltr(value))
                if caption:
                    st.caption(caption)


def _card_kpis(key: str, cards: tuple[Card, ...]) -> None:
    if cards:
        _kpis(key, [(c.label, c.text, c.note or None) for c in cards])


def _version_row(d: Dashboard, step: StepView) -> None:
    """The version switch (display names) and the raw id as a muted caption."""
    with st.container(
        key=f"mx-sec-{step.step}", horizontal=True, vertical_alignment="center"
    ):
        st.selectbox(
            d.labels["version_switch"],
            step.options,
            index=step.options.index(step.chosen),
            key=f"res_ver_{step.step}_{d.baseline}",
            label_visibility="collapsed",
            format_func=lambda v: labelled(d.labels["version_switch"], d.names[v].text),
            width=460,
        )
        st.html(
            id_caption_html(d.labels["id_caption"], d.names[step.chosen].id),
            width="content",
        )


def _step(d: Dashboard, step: StepView) -> None:
    if step.options:
        _version_row(d, step)
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
    if step.waterfall is not None:
        wide, narrow = st.columns([3, 2], gap="medium")
        with wide, st.container(key=f"mx-card-wf-{step.step}"):
            st.html(card_title_html(d.labels["waterfall"]))
            _waterfall_chart(d, step)
        with narrow, st.container(key=f"mx-card-donut-{step.step}"):
            st.html(card_title_html(d.labels["chart_breakdown"]))
            _breakdown_chart(d, step)
    has_comparison = f"comparison:{step.step}" in d.tables
    if has_comparison or step.waterfall is not None:
        n = len(d.comparison_chart.get(step.step, ()))
        height = _bars_height(n)
        wide, narrow = st.columns([3, 2], gap="medium")
        if has_comparison:
            with wide, st.container(key=f"mx-card-cmp-{step.step}"):
                st.html(card_title_html(d.labels["chart_comparison"]))
                _comparison_chart(d, step.step, height)
                st.caption(d.labels["ranked_note"])
        if step.waterfall is not None:
            with narrow, st.container(key=f"mx-card-blocks-{step.step}"):
                st.html(card_title_html(d.labels["chart_blocks"]))
                _block_chart(d, step, height)
    _folded(d, f"waterfall:{step.step}")
    _folded(d, f"comparison:{step.step}")


def _cache(d: Dashboard) -> None:
    with st.container(key="mx-card-cache"):
        st.html(card_title_html(d.labels["cache_monitor"]))
        if d.cache_cards:
            _card_kpis("cache", d.cache_cards)
        elif not d.tables.get("cache"):
            st.html(empty_state_html("cached", d.labels["step_none"]))
        st.caption(d.labels["guard_reasons_none"])
        _folded(d, "cache")
    if d.gate is not None:
        with st.container(key="mx-card-gate"):
            st.html(card_title_html(d.labels["greeting_gate"]))
            _kpis(
                "gate",
                [
                    (d.labels["saving"], d.gate.text, d.gate.unit),
                    (d.labels["gate_skipped"], d.gate.skipped_text, None),
                ],
            )
            st.caption(" · ".join(p for p in (d.gate.name, d.gate.note) if p))


def _per_bot(d: Dashboard) -> None:
    routing = d.routing
    if routing is None:
        st.html(empty_state_html("alt_route", d.labels["step_none"]))
        return
    with st.container(
        key="mx-sec-per-bot", horizontal=True, vertical_alignment="center"
    ):
        st.html(card_title_html(routing.name), width="content")
        st.html(
            id_caption_html(d.labels["id_caption"], d.names[routing.version].id),
            width="content",
        )
    if routing.message:
        st.info(routing.message, icon=":material/info:")
    _card_kpis("routing", d.routing_cards)
    theme = _theme()
    if d.bot_chart or d.tenant_chart:
        wide, narrow = st.columns([3, 2], gap="medium")
        if d.bot_chart:
            with wide, st.container(key="mx-card-bots"):
                n = min(len(d.bot_chart), BOT_CHART_MAX)
                st.html(card_title_html(d.labels["chart_bots"].format(n=n)))
                colour = theme.kinds["saving"]
                _share_bars(d, d.bot_chart, None, {"bars": colour})
                _legend([(d.labels["share_of_saving"], colour)])
        if d.tenant_chart:
            with narrow, st.container(key="mx-card-tenants"):
                st.html(card_title_html(d.labels["chart_tenants"]))
                flags = {r["flag"]: r["flagged"] for r in d.tenant_chart}
                colours = {
                    flag: theme.colours["warning"] if over else theme.kinds["total"]
                    for flag, over in flags.items()
                }
                _share_bars(d, d.tenant_chart, "flag", colours)
                _legend(colours.items())
    _folded(d, "bots")
    _folded(d, "tenants")
    if routing.caveats:
        with st.expander(d.labels["caveats"], expanded=False):
            st.html(data_list_html(routing.caveats))


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
        final=load_final(folder),
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
        st.caption(d.combined_note)
        steps = {s.step: s for s in d.overview}
        tabs = st.tabs([steps[s].title for s in STEPS] + [d.labels["tab_per_bot"]])
        for tab, name in zip(tabs, STEPS, strict=False):
            with tab:
                _step(d, steps[name])
                if name == "cache":
                    _cache(d)
        with tabs[-1]:
            _per_bot(d)
        _final(d)


page()
