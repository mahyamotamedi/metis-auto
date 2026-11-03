"""View model of the lever results for the demo (CMP-20; final plan D-1, D-2).

Responsibility: turn ``reports/levers/<lever_id>.json`` files (ADR-0032) into
what the demo page shows, with no Streamlit import and no replay logic:
- ``load_view``: every ``*.json`` in one folder through the shared loader
  ``LeverResult.from_json``; other files are never opened, and JSON that is not
  a ``LeverResult`` is counted as skipped. No folder or no result gives an
  empty view with a message, not an error.
- ``waterfall``: one result's baseline, saving and after-cost per cost block
  (``levers.BLOCKS``: ``fees``, ``token_cost``), with totals that are the sum
  of the rows. The unit comes from the baseline (``compare.BASELINES``):
  recorded or repriced, never mixed; ``for_baseline`` picks one baseline.
- ``slice_rows``: the slices to display. Rank slices become labels such as
  ``bot-07``; a slice name outside the known forms is dropped, so no bot or
  user ID can reach a screen (licence: aggregates only).
- ``dashboard`` (D-2, spec UI-S07): everything the Results page draws, for one
  baseline, one slice and one language (strings from ``wiring.ui_config``):
  the savings overview per step with a version switch (UI-R21, UI-R24), the
  waterfall by cost block (UI-R22), the version comparison of
  ``compare.compare`` (UI-R23), the cache monitor (UI-R25), the greeting
  gate's token part (UI-R27), routing per bot (UI-R26), evidence labels
  (UI-R28), direction (UI-R29) and the empty state (UI-R30).
- ``display_name`` (UI Stage 2b): a short name per version from
  ``config/demo/lever_names.toml`` with its owner pipeline, e.g. "Retrieval
  cache, 90 days (B)"; the raw id goes to a muted caption or tooltip only. An id
  with no name shows the raw id and a "no display name" marker. Numbers are
  formatted by ``wiring.ui_format.fmt`` (ADR-0052 Amendment 1).

Display rules (ADR-0050):
- A repriced baseline has no fees (ADR-0036): its fees row is "not priced",
  never unknown, and its totals are the token cost ("token cost only, fees not
  priced"). A slice that holds ``baseline:fees`` inside a repriced result is in
  recorded units and is not shown.
- An ``other`` block (F-2) is shown as part of ``token_cost`` (owner decision
  2026-11-02) and is not added to the totals a second time.
- The overview shows each step's chosen version; steps are never added up
  (they can overlap, Review Focus 1). No combined result exists until
  ``final.json`` has an agreed format (I-2).
- Ranks come from ``compare.compare`` only (one step, one group, one baseline);
  the group label leaves out the data revision hash.

Traceability: QA-PRIV (content- and ID-free screens), QA-COST and FR-ACCT-05
(savings per block against a named baseline), FR-REQ-04 (unknown is shown as
unknown, never 0), QA-REPRO (results carry their manifest), FR-EVAL-02 (like
with like), FR-FIN-02 (demo dashboard).
Called by: tests; scripts/demo_pages/results.py (D-2). Calls:
analysis.{lever_result, levers, compare} (read only), wiring.ui_config,
wiring.ui_format.
"""

from __future__ import annotations

import math
import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError

from metis_auto.analysis.compare import BASELINES, compare
from metis_auto.analysis.lever_result import LeverResult
from metis_auto.analysis.levers import BLOCKS
from metis_auto.wiring.ui_config import Strings, Text, direction
from metis_auto.wiring.ui_format import fmt

LRI, PDI = "\u2066", "\u2069"

LEVERS_DIR = Path("reports") / "levers"
SPRINT_TOML = Path("config") / "evaluation" / "sprint.toml"
LEVER_NAMES_PATH = Path("config") / "demo" / "lever_names.toml"
FINAL_JSON = "final.json"
STEPS = ("cache", "context", "routing")
RESULT_SLICE = "result"
"""The slice option that shows the result's own totals (with its interval)."""
EXTRA_BLOCKS = ("other",)
"""F-2's block: part of ``token_cost`` (owner decision 2026-11-02)."""
NOT_PRICED = "token cost only, fees not priced"
DEFAULT_BASELINE = "as_logged"

EMPTY_MESSAGE = (
    "No lever results yet. A replay writes them to reports/levers/<lever_id>.json."
)

_RANK = re.compile(r"^(bot|tenant)_rank:([1-9][0-9]{0,3})$")
_LANG = re.compile(r"^lang:[a-z_]{1,16}$")
_PLAIN_SLICES = ("all", "llm_only", "traffic_weighted", "over_8k")
_UNITS = {b.key: "recorded" if b.recorded else "repriced" for b in BASELINES}
_SUFFIX = re.compile(
    r"(\.|__)(" + "|".join(re.escape(b.key) for b in BASELINES) + r")$"
)


@dataclass(frozen=True)
class LeverView:
    results: tuple[LeverResult, ...]
    """Sorted by ``lever_id``."""
    skipped: int
    """``*.json`` files that are not a valid ``LeverResult``."""

    @property
    def empty(self) -> bool:
        return not self.results

    @property
    def message(self) -> str | None:
        return EMPTY_MESSAGE if self.empty else None

    @property
    def baselines(self) -> tuple[str, ...]:
        return tuple(sorted({r.baseline for r in self.results}))

    def for_baseline(self, baseline: str) -> tuple[LeverResult, ...]:
        return tuple(r for r in self.results if r.baseline == baseline)


def load_view(folder: Path) -> LeverView:
    results: list[LeverResult] = []
    skipped = 0
    paths = sorted(folder.glob("*.json")) if folder.is_dir() else []
    for path in paths:
        try:
            results.append(LeverResult.from_json(path.read_text(encoding="utf-8")))
        except (UnicodeDecodeError, ValidationError):
            skipped += 1
    results.sort(key=lambda r: r.lever_id)
    return LeverView(results=tuple(results), skipped=skipped)


def cost_unit(baseline: str) -> str:
    """``recorded``, ``repriced``, or ``unknown`` for a baseline not in the list."""
    return _UNITS.get(baseline, "unknown")


@dataclass(frozen=True)
class WaterfallRow:
    block: str
    baseline: Decimal | None
    saving: Decimal | None
    after: Decimal | None
    priced: bool = True
    """False for fees under a repriced baseline: not priced, not unknown."""
    part_of: str | None = None
    """``token_cost`` for F-2's ``other``: shown, never added to the totals."""


@dataclass(frozen=True)
class Waterfall:
    lever_id: str
    baseline: str
    unit: str
    rows: tuple[WaterfallRow, ...]
    baseline_total: Decimal | None
    saving_total: Decimal | None
    after_total: Decimal | None
    note: str | None = None
    """``NOT_PRICED`` (or its translation) under a repriced baseline."""


def _total(values: list[Decimal | None], declared: Decimal | None) -> Decimal | None:
    if any(v is None for v in values):
        return None
    total = sum(values, Decimal(0))
    if declared is not None and declared != total:
        raise ValueError(f"blocks sum to {total}, but the result's total is {declared}")
    return total


def waterfall(result: LeverResult) -> Waterfall:
    """Rows per cost block; a missing block is unknown, and so is every total.

    Under a repriced baseline the fees row is not priced and the totals are the
    token cost (ADR-0036)."""
    return _waterfall(
        result.lever_id, result.baseline, result.baseline_cost, result.saving
    )


def _after(base: Decimal | None, save: Decimal | None) -> Decimal | None:
    return None if base is None or save is None else base - save


def _waterfall(
    lever_id: str,
    baseline: str,
    base: Mapping[str, Decimal],
    save: Mapping[str, Decimal],
    *,
    note: str = NOT_PRICED,
) -> Waterfall:
    repriced = cost_unit(baseline) == "repriced"
    rows = []
    for block in BLOCKS:
        if repriced and block == "fees":
            rows.append(WaterfallRow(block, None, None, None, priced=False))
            continue
        b, s = base.get(block), save.get(block)
        if repriced and block == "token_cost":  # a repriced total is token cost
            b = base.get("total") if b is None else b
            s = save.get("total") if s is None else s
        rows.append(WaterfallRow(block, b, s, _after(b, s)))
    priced = [r for r in rows if r.priced]
    baseline_total = _total([r.baseline for r in priced], base.get("total"))
    saving_total = _total([r.saving for r in priced], save.get("total"))
    after_total = _total([r.after for r in priced], None)
    for block in EXTRA_BLOCKS:
        if block in base or block in save:
            b, s = base.get(block), save.get(block)
            rows.append(WaterfallRow(block, b, s, _after(b, s), part_of="token_cost"))
    return Waterfall(
        lever_id=lever_id,
        baseline=baseline,
        unit=cost_unit(baseline),
        rows=tuple(rows),
        baseline_total=baseline_total,
        saving_total=saving_total,
        after_total=after_total,
        note=note if repriced else None,
    )


def rank_label(kind: str, rank: int) -> str:
    return f"{kind}-{rank:02d}"


def slice_label(name: str) -> str | None:
    """Display label of a slice name, or None if it must not be shown."""
    if name in _PLAIN_SLICES or _LANG.match(name):
        return name
    rank = _RANK.match(name)
    return rank_label(rank[1], int(rank[2])) if rank else None


def slice_rows(result: LeverResult) -> list[tuple[str, dict[str, Decimal]]]:
    """(label, values) for every showable slice, in the result's sorted order."""
    rows = []
    for name in sorted(result.slices):
        label = slice_label(name)
        if label is not None:
            rows.append((label, dict(result.slices[name])))
    return rows


# --- display names (UI Stage 2b, owner review point 3) ----------------------


@dataclass(frozen=True)
class LeverName:
    pattern: re.Pattern[str]
    owner: str
    fa: str
    en: str


@dataclass(frozen=True)
class DisplayName:
    text: str
    """``name (owner)``, or the raw id with the "no display name" marker."""
    id: str
    """The version id (the lever_id without its baseline suffix)."""
    missing: bool = False


_PERSIAN_DIGITS = str.maketrans("0123456789,", "۰۱۲۳۴۵۶۷۸۹٬")


def load_lever_names(path: Path | None = None) -> tuple[LeverName, ...]:
    """The ``[[name]]`` table of ``config/demo/lever_names.toml``, in file
    order; a pattern that does not compile or an entry without fa, en or owner
    refuses the file."""
    data = tomllib.loads((path or LEVER_NAMES_PATH).read_text(encoding="utf-8"))
    names = []
    for n, entry in enumerate(data.get("name", ())):
        missing = [k for k in ("pattern", "owner", "fa", "en") if not entry.get(k)]
        if missing:
            raise ValueError(f"lever name {n} lacks {', '.join(missing)}")
        names.append(
            LeverName(
                re.compile(entry["pattern"]), entry["owner"], entry["fa"], entry["en"]
            )
        )
    return tuple(names)


def _field(value: str, lang: str) -> str:
    text = f"{int(value):,}" if value.isdigit() else value
    return text.translate(_PERSIAN_DIGITS) if lang == "fa" else text


def display_name(
    lever_id: str, lang: str, t: Text, names: Sequence[LeverName]
) -> DisplayName:
    """The short name of a version in ``lang`` with its owner, e.g.
    ``حافظه‌ی بازیابی، ۹۰ روز (B)``; the first pattern that matches the whole
    id (baseline suffix removed) wins."""
    key = _SUFFIX.sub("", lever_id)
    for name in names:
        match = name.pattern.fullmatch(key)
        if match:
            fields = {k: _field(v, lang) for k, v in match.groupdict().items()}
            template = name.fa if lang == "fa" else name.en
            return DisplayName(f"{template.format(**fields)} ({name.owner})", key)
    return DisplayName(f"{key} ({t('name_missing')})", key, missing=True)


# --- D-2 results dashboard (spec UI-S07) ------------------------------------


def tenant_cap(path: Path = SPRINT_TOML) -> Decimal:
    """``[sample] tenant_cap`` of the sprint config (plan decision rule)."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    cap = Decimal(str(data["sample"]["tenant_cap"]))
    if not Decimal(0) < cap <= Decimal(1):
        raise ValueError("tenant_cap must be a share in (0, 1]")
    return cap


def has_final(folder: Path) -> bool:
    return (folder / FINAL_JSON).is_file()


def version_key(result: LeverResult) -> str:
    """The result's name without its baseline suffix: the same across the four
    baselines, so a chosen version survives a baseline switch."""
    return _SUFFIX.sub("", result.lever_id)


@dataclass(frozen=True)
class Option:
    key: str
    label: str


@dataclass(frozen=True)
class Card:
    key: str
    label: str
    value: Decimal | None
    """The stored (or summed) figure; None is unknown or not applicable."""
    text: str
    note: str = ""
    """Words about the figure (not isolated): shown as the card's caption."""


@dataclass(frozen=True)
class StepView:
    step: str
    title: str
    options: tuple[str, ...]
    chosen: str | None
    result_id: str | None
    cards: tuple[Card, ...] = ()
    interval: tuple[float, float] | None = None
    waterfall: Waterfall | None = None
    chart: tuple[dict[str, object], ...] = ()
    """Waterfall bars; empty when a value is unknown (UI-G08)."""
    blocks: tuple[dict[str, object], ...] = ()
    """Stacked bars (UI-G03): the cost before and after the step by priced
    block; empty when a value is unknown."""
    breakdown: tuple[dict[str, object], ...] = ()
    """Donut (UI-G04): the cost left after the step and each block's saving,
    adding up to the baseline cost; empty when a value is unknown or negative."""
    unit: str = ""
    unit_note: str | None = None
    evidence: str = ""
    quality: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class ComparisonRow:
    rank: int | None
    status: str
    """The ``compare`` status (``ranked``, ``insufficient evidence``, ...)."""
    status_label: str
    version: str
    baseline: str
    group: str
    saving: Decimal | None
    saving_share: Decimal | None
    interval: tuple[float, float] | None
    eligible: str
    correctness: str
    evidence_class: str
    tenant_flag: str
    unit: str
    name: str = ""
    """The version's display name (``display_name``)."""


@dataclass(frozen=True)
class CacheRow:
    version: str
    source: str
    """``retrieval``, ``session_memo`` or ``requests``: where the counts are."""
    lookups: int | None = None
    hits: int | None = None
    misses: int | None = None
    guard_blocks: int | None = None
    gate_skips: int | None = None
    shadow_sampled: int | None = None
    shadow_agree: int | None = None
    shadow_unknown: int | None = None
    guard_reasons: Mapping[str, int] | None = None
    """None: no result carries reasons yet."""
    misses_note: str = ""


@dataclass(frozen=True)
class GateView:
    version: str
    token_saving: Decimal | None
    lower_bound: bool
    skipped: int | None
    unit: str
    note: str
    text: str = ""
    """``token_saving`` formatted (``unknown`` when absent)."""
    skipped_text: str = ""
    name: str = ""


@dataclass(frozen=True)
class BotRow:
    label: str
    n_requests: int | None
    n_moved: int | None
    moved_share: Decimal | None
    saving: Decimal | None
    saving_share: Decimal | None
    share_of_saving: Decimal | None
    insufficient: bool


@dataclass(frozen=True)
class TenantRow:
    label: str
    n_requests: int | None
    share: Decimal | None
    flagged: bool
    flag_text: str
    saving_share: Decimal | None
    share_of_saving: Decimal | None


@dataclass(frozen=True)
class RoutingTable:
    version: str
    bots: tuple[BotRow, ...]
    tenants: tuple[TenantRow, ...]
    traffic_weighted_share: Decimal | None
    caveats: tuple[str, ...]
    message: str | None = None
    traffic_weighted_text: str = ""
    name: str = ""


@dataclass(frozen=True)
class Dashboard:
    lang: str
    direction: str
    labels: Mapping[str, str]
    empty: bool
    empty_message: str | None = None
    baseline: str | None = None
    baselines: tuple[Option, ...] = ()
    slice_name: str = RESULT_SLICE
    slices: tuple[Option, ...] = ()
    combined_note: str | None = None
    overview: tuple[StepView, ...] = ()
    comparison: Mapping[str, tuple[ComparisonRow, ...]] = ()  # type: ignore[assignment]
    comparison_chart: Mapping[str, tuple[dict[str, object], ...]] = ()  # type: ignore[assignment]
    cache: tuple[CacheRow, ...] = ()
    gate: GateView | None = None
    routing: RoutingTable | None = None
    skipped_note: str | None = None
    tables: Mapping[str, tuple[dict[str, str], ...]] = ()  # type: ignore[assignment]
    """Display tables, cells formatted and headers translated: ``waterfall:<step>``,
    ``comparison:<step>``, ``cache``, ``bots``, ``tenants``."""
    names: Mapping[str, DisplayName] = ()  # type: ignore[assignment]
    """Display name per version key (UI Stage 2b)."""
    summaries: Mapping[str, str] = ()  # type: ignore[assignment]
    """One-line summary per table key: the label of its folded expander."""
    cache_cards: tuple[Card, ...] = ()
    """The chosen cache version's monitor counts as KPI cards."""
    routing_cards: tuple[Card, ...] = ()
    """Per-bot tab KPI cards: traffic-weighted saving, bots, tenants over cap."""
    bot_chart: tuple[dict[str, object], ...] = ()
    """Share of the routing saving per bot rank (bars); bots with a value."""
    tenant_chart: tuple[dict[str, object], ...] = ()
    """Share of requests per tenant rank, flagged over the cap (bars)."""


def dashboard(
    view: LeverView,
    *,
    strings: Strings,
    tenant_cap: Decimal,
    lang: str = "fa",
    baseline: str | None = None,
    slice_name: str = RESULT_SLICE,
    choices: Mapping[str, str] | None = None,
    final_present: bool = False,
    lever_names: Sequence[LeverName] | None = None,
) -> Dashboard:
    """The Results page for one baseline, slice and language; nothing invented.

    An unknown ``baseline``, ``slice_name`` or chosen version falls back to the
    default, so a stale widget value never breaks the page."""
    t = _Text(strings, lang)
    labels = {k: strings.text(k, lang) for k in strings.keys()}
    skipped = t("skipped_files", n=view.skipped) if view.skipped else None
    if view.empty:
        return Dashboard(
            lang=lang,
            direction=direction(lang),
            labels=labels,
            empty=True,
            empty_message=f"{t('empty_title')} {t('empty_message')}",
            comparison={},
            comparison_chart={},
            skipped_note=skipped,
        )
    keys = [b.key for b in BASELINES]
    baseline = baseline if baseline in keys else DEFAULT_BASELINE
    results = view.for_baseline(baseline)
    slices = _slice_options(results, t)
    if slice_name not in {o.key for o in slices}:
        slice_name = RESULT_SLICE
    known = load_lever_names() if lever_names is None else lever_names
    names = {
        version_key(r): display_name(r.lever_id, lang, t, known) for r in view.results
    }
    rows = _comparison_rows(view, baseline, tenant_cap, t, names)
    chosen = _choices(results, rows, choices or {})
    by_key = {version_key(r): r for r in results}
    overview = tuple(
        _step_view(step, results, chosen.get(step), by_key, slice_name, t)
        for step in STEPS
    )
    cache = tuple(
        replace(row, misses_note=t(f"misses_{row.source}"))
        for row in cache_monitor(results)
    )
    routing_key = chosen.get("routing")
    routing = (
        replace(
            _routing(by_key[routing_key], tenant_cap, t),
            name=names[routing_key].text,
        )
        if routing_key
        else None
    )
    gate = _gate(results, t)
    if gate is not None:
        gate = replace(gate, name=names[gate.version].text)
    tables = _tables(overview, rows, cache, routing, t, names)
    return Dashboard(
        lang=lang,
        direction=direction(lang),
        labels=labels,
        empty=False,
        baseline=baseline,
        baselines=tuple(Option(k, t(f"baseline_{k}")) for k in keys),
        slice_name=slice_name,
        slices=slices,
        combined_note=t("combined_unformatted" if final_present else "combined_absent"),
        overview=overview,
        comparison=rows,
        comparison_chart={step: _comparison_chart(r, t) for step, r in rows.items()},
        cache=cache,
        gate=gate,
        routing=routing,
        skipped_note=skipped,
        tables=tables,
        names=names,
        summaries=_summaries(tables, rows, routing, t),
        cache_cards=_cache_cards(cache, chosen.get("cache"), t),
        routing_cards=_routing_cards(routing, t),
        bot_chart=_bot_chart(routing, t),
        tenant_chart=_tenant_chart(routing, t),
    )


class _Text:
    def __init__(self, strings: Strings, lang: str) -> None:
        self.strings, self.lang = strings, lang

    def __call__(self, key: str, **fields: object) -> str:
        """A string with every number field LTR-isolated (UI-V07), so a count in
        a Persian sentence never reorders."""
        isolated = {
            k: f"{LRI}{v}{PDI}"
            if isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)
            else v
            for k, v in fields.items()
        }
        return self.strings.text(key, self.lang, **isolated)

    def amount(self, value: Decimal | None) -> str:
        return fmt(value, "money", unknown=self("unknown"))

    def share(self, value: Decimal | float | None) -> str:
        return fmt(value, "percent", unknown=self("unknown"))

    def count(self, value: int | None) -> str:
        return fmt(value, "count", unknown=self("not_reported"))

    def interval(self, ci: tuple[float, float] | None) -> str:
        return fmt(ci, "interval", unknown=self("interval_none"))

    def unit(self, result: LeverResult) -> str:
        if cost_unit(result.baseline) == "recorded":
            return self("unit_recorded")
        return self("unit_repriced", pv=result.manifest.price_version)

    def evidence(self, evidence_class: str, correctness_state: str) -> str:
        ev = self("ev_" + re.sub(r"[ -]", "_", evidence_class))
        return f"{ev} · {self.correctness(correctness_state)}"

    def correctness(self, state: str) -> str:
        if state in ("unmeasured", "measured"):
            return self(f"corr_{state}")
        sampled = re.fullmatch(r"sampled:([0-9]+)", state)
        return (
            self("corr_sampled", n=int(sampled[1])) if sampled else self("corr_unknown")
        )


def _slice_options(results: Sequence[LeverResult], t: _Text) -> tuple[Option, ...]:
    present = {name for r in results for name in r.slices}
    options = [Option(RESULT_SLICE, t("slice_result"))]
    options += [Option(n, t(f"slice_{n}")) for n in _PLAIN_SLICES if n in present]
    options += [
        Option(n, t("slice_lang", code=_lang_name(n.removeprefix("lang:"), t)))
        for n in sorted(present)
        if _LANG.match(n)
    ]
    return tuple(options)


def _lang_name(code: str, t: _Text) -> str:
    """A language slice's code in words (``lang_code_<code>``); a code without
    an entry stays as it is."""
    key = f"lang_code_{code}"
    return t(key) if key in t.strings.table else code


# --- comparison (UI-R23) ---


def _clean(value: object) -> object:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if type(value).__name__ == "NAType":  # pandas' missing marker
        return None
    return value


_STATUS_KEYS = {
    "ranked": "status_ranked",
    "insufficient evidence": "status_insufficient",
    "baseline missing": "status_missing",
    "duplicate version": "status_duplicate",
}


def _comparison_rows(
    view: LeverView,
    baseline: str,
    cap: Decimal,
    t: _Text,
    names: Mapping[str, DisplayName],
) -> dict[str, tuple[ComparisonRow, ...]]:
    frame = compare(view.results, baseline=baseline, max_tenant_share=cap)
    # Some writers reuse one lever_id under all four baselines (only the file
    # names differ), so the lookup is per baseline.
    by_id = {r.lever_id: r for r in view.for_baseline(baseline)}
    groups: dict[object, int] = {}
    out: dict[str, list[ComparisonRow]] = {}
    for raw in frame.astype(object).to_dict("records"):
        row = {k: _clean(v) for k, v in raw.items()}
        step = str(row["step"])
        result = by_id.get(str(row["lever_id"])) if row["lever_id"] else None
        if result is None:  # baseline missing: name it by another baseline's file
            twin = next(
                (
                    r
                    for r in view.results
                    if (r.step, r.version) == (step, row["version"])
                ),
                None,
            )
            version = version_key(twin) if twin else str(row["version"])
            group = ""
        else:
            version = version_key(result)
            n = groups.setdefault(row["group"], len(groups) + 1)
            group = t(
                "group_text",
                n=n,
                requests=t.count(result.n_requests),
                pv=result.manifest.price_version,
            )
        ci = (
            (float(row["ci_low"]), float(row["ci_high"]))
            if row["ci_low"] is not None and row["ci_high"] is not None
            else None
        )
        out.setdefault(step, []).append(
            ComparisonRow(
                rank=None if row["rank"] is None else int(row["rank"]),
                status=str(row["status"]),
                status_label=t(_STATUS_KEYS.get(str(row["status"]), "unknown")),
                version=version,
                baseline=baseline,
                group=group,
                saving=row["saving"],  # type: ignore[arg-type]
                saving_share=row["saving_share"],  # type: ignore[arg-type]
                interval=ci,
                eligible=t(
                    "eligible_of",
                    a=t.count(result.n_eligible),
                    b=t.count(result.n_requests),
                )
                if result
                else str(row["eligible"] or "—"),
                correctness=t.correctness(result.correctness_state) if result else "—",
                evidence_class=(
                    t.evidence(result.evidence_class, result.correctness_state)
                    if result
                    else "—"
                ),
                tenant_flag=_tenant_flag(row["tenant_flag"], cap, t),
                unit=t.unit(result) if result else "",
                name=names[version].text if version in names else version,
            )
        )
    return {step: tuple(rows) for step, rows in out.items()}


def _tenant_flag(flag: object, cap: Decimal, t: _Text) -> str:
    """``compare``'s tenant flag (``ok``, ``over N%``, ``unknown``) in words."""
    if flag == "ok":
        return t("flag_ok")
    if isinstance(flag, str) and flag.startswith("over "):
        return t("flag_over_cap", cap=f"\u2066{t.share(cap)}\u2069")
    return t("unknown")


def _comparison_chart(
    rows: Sequence[ComparisonRow], t: _Text
) -> tuple[dict[str, object], ...]:
    """One bar per version with a saving share: the display name on the axis,
    the raw id and the formatted share only in the tooltip."""
    return tuple(
        {
            "version": r.name or r.version,
            "id": r.version,
            "saving_share": float(r.saving_share),
            "ranked": r.status == "ranked",
            "status": r.status_label,
            "text": t.share(r.saving_share),
        }
        for r in rows
        if r.saving_share is not None
    )


def _tables(
    overview: Sequence[StepView],
    comparison: Mapping[str, Sequence[ComparisonRow]],
    cache: Sequence[CacheRow],
    routing: RoutingTable | None,
    t: _Text,
    names: Mapping[str, DisplayName],
) -> dict[str, tuple[dict[str, str], ...]]:
    count = t.count

    def name(version: str) -> str:
        return names[version].text if version in names else version

    out: dict[str, tuple[dict[str, str], ...]] = {}
    for step in overview:
        if step.waterfall is None:
            continue
        out[f"waterfall:{step.step}"] = tuple(
            {
                t("row_block"): t(f"block_{r.block}"),
                t("row_before"): t.amount(r.baseline)
                if r.priced
                else t("not_priced_cell"),
                t("row_saving"): t.amount(r.saving)
                if r.priced
                else t("not_priced_cell"),
                t("row_after"): t.amount(r.after) if r.priced else t("not_priced_cell"),
            }
            for r in step.waterfall.rows
        )
    for step, rows in comparison.items():
        out[f"comparison:{step}"] = tuple(
            {
                t("col_rank"): "—" if r.rank is None else str(r.rank),
                t("col_status"): r.status_label,
                t("col_version"): r.name or r.version,
                t("saving"): t.amount(r.saving),
                t("saving_share"): t.share(r.saving_share),
                t("interval"): t.interval(r.interval),
                t("col_eligible"): r.eligible,
                t("col_evidence"): r.evidence_class,
                t("col_tenant"): r.tenant_flag,
                t("col_group"): r.group,
            }
            for r in rows
        )
    out["cache"] = tuple(
        {
            t("col_version"): name(r.version),
            t("lookups"): count(r.lookups),
            t("hits"): count(r.hits),
            t("misses"): count(r.misses),
            t("guard_blocks"): count(r.guard_blocks),
            t("gate_skips"): count(r.gate_skips),
            t("shadow"): t("not_reported")
            if r.shadow_sampled is None
            else " / ".join(
                count(n) for n in (r.shadow_sampled, r.shadow_agree, r.shadow_unknown)
            ),
            t("misses_how"): r.misses_note,
        }
        for r in cache
    )
    if routing is not None:
        out["bots"] = tuple(
            {
                t("bot"): b.label,
                t("requests"): count(b.n_requests),
                t("moved"): count(b.n_moved),
                t("moved_share"): t.share(b.moved_share),
                t("saving"): t.amount(b.saving),
                t("saving_share"): t.share(b.saving_share),
                t("share_of_saving"): t.share(b.share_of_saving),
                t("insufficient"): "✓" if b.insufficient else "",
            }
            for b in routing.bots
        )
        out["tenants"] = tuple(
            {
                t("tenant"): r.label,
                t("requests"): count(r.n_requests),
                t("tenant_share"): t.share(r.share),
                t("col_tenant"): r.flag_text,
                t("saving_share"): t.share(r.saving_share),
                t("share_of_saving"): t.share(r.share_of_saving),
            }
            for r in routing.tenants
        )
    return out


def _choices(
    results: Sequence[LeverResult],
    rows: Mapping[str, Sequence[ComparisonRow]],
    wanted: Mapping[str, str],
) -> dict[str, str]:
    """Per step: the wanted version if it exists, else the first rank 1, else
    the first version."""
    chosen = {}
    for step in STEPS:
        options = sorted({version_key(r) for r in results if r.step == step})
        if not options:
            continue
        if wanted.get(step) in options:
            chosen[step] = wanted[step]
            continue
        first = next(
            (r.version for r in rows.get(step, ()) if r.rank == 1),
            None,
        )
        chosen[step] = first if first in options else options[0]
    return chosen


# --- overview and waterfall (UI-R21, UI-R22, UI-R24, UI-R28) ---


def _split(values: Mapping[str, Decimal], prefix: str) -> dict[str, Decimal]:
    return {
        k.removeprefix(prefix): v for k, v in values.items() if k.startswith(prefix)
    }


def _step_view(
    step: str,
    results: Sequence[LeverResult],
    chosen: str | None,
    by_key: Mapping[str, LeverResult],
    slice_name: str,
    t: _Text,
) -> StepView:
    options = tuple(sorted({version_key(r) for r in results if r.step == step}))
    base = StepView(step, t(f"step_{step}"), options, chosen, None)
    if chosen is None:
        return replace(base, message=t("step_none"))
    result = by_key[chosen]
    repriced = cost_unit(result.baseline) == "repriced"
    base = replace(
        base,
        result_id=result.lever_id,
        unit=t.unit(result),
        unit_note=t("not_priced") if repriced else None,
        evidence=t.evidence(result.evidence_class, result.correctness_state),
        quality=t("quality_line") if result.correctness_state != "measured" else None,
    )
    if slice_name == RESULT_SLICE:
        cost, save, stored_share = result.baseline_cost, result.saving, None
        ci = (
            (result.ci_low, result.ci_high)
            if result.ci_low is not None and result.ci_high is not None
            else None
        )
    else:
        values = result.slices.get(slice_name)
        if values is None:
            return replace(base, message=t("slice_missing"))
        if repriced and "baseline:fees" in values:
            return replace(base, message=t("slice_other_units"))
        cost, save = _split(values, "baseline:"), _split(values, "saving:")
        stored_share, ci = values.get("saving_share"), None
    try:
        wf = _waterfall(
            result.lever_id, result.baseline, cost, save, note=t("not_priced")
        )
    except ValueError:
        return replace(base, message=t("inconsistent"))
    share = stored_share
    if share is None and wf.saving_total is not None and wf.baseline_total:
        share = wf.saving_total / wf.baseline_total
    interval_text = t.interval(ci)
    interval_note = t("interval_result_only") if slice_name != RESULT_SLICE else ""
    cards = (
        Card(
            "baseline_cost",
            t("baseline_cost"),
            wf.baseline_total,
            t.amount(wf.baseline_total),
        ),
        Card("saving", t("saving"), wf.saving_total, t.amount(wf.saving_total)),
        Card("saving_share", t("saving_share"), share, t.share(share)),
        Card("interval", t("interval"), None, interval_text, interval_note),
    )
    return replace(
        base,
        cards=cards,
        interval=ci,
        waterfall=wf,
        chart=_waterfall_chart(wf, t),
        blocks=_block_bars(wf, t),
        breakdown=_breakdown(wf, t),
    )


def _block_bars(wf: Waterfall, t: _Text) -> tuple[dict[str, object], ...]:
    """Before and after by priced block (fees not priced and ``other``, which is
    part of token cost, are left out); none if a value is unknown."""
    priced = [r for r in wf.rows if r.priced and r.part_of is None]
    if not priced or any(r.baseline is None or r.after is None for r in priced):
        return ()
    bars = []
    for stage, field in (("row_before", "baseline"), ("row_after", "after")):
        for order, row in enumerate(priced):
            value = getattr(row, field)
            bars.append(
                {
                    "stage": t(stage),
                    "block": t(f"block_{row.block}"),
                    "order": order,
                    "value": float(value),
                    "text": t.amount(value),
                }
            )
    return tuple(bars)


def _breakdown(wf: Waterfall, t: _Text) -> tuple[dict[str, object], ...]:
    """The after-cost and each priced block's saving: slices of the baseline
    cost. None when a value is unknown, or a saving or the after-cost is negative
    (an extra cost is no slice of the baseline)."""
    priced = [r for r in wf.rows if r.priced and r.part_of is None]
    if wf.after_total is None or wf.after_total < 0 or not priced:
        return ()
    if any(r.saving is None or r.saving < 0 for r in priced):
        return ()
    parts = [("part_remaining", None, wf.after_total)]
    parts += [("part_saved", r.block, r.saving) for r in priced if r.saving]
    return tuple(
        {
            "part": t(key, block=t(f"block_{block}")) if block else t(key),
            "order": order,
            "value": float(value),
            "text": t.amount(value),
        }
        for order, (key, block, value) in enumerate(parts)
    )


def _waterfall_chart(wf: Waterfall, t: _Text) -> tuple[dict[str, object], ...]:
    """Bars from the baseline down to the after-cost; none if a value is unknown
    (UI-G08: no invented data)."""
    priced = [r for r in wf.rows if r.priced and r.part_of is None]
    if wf.baseline_total is None or wf.after_total is None:
        return ()
    if any(r.saving is None for r in priced):
        return ()
    bars: list[dict[str, object]] = [
        _bar(t("row_before"), 0, wf.baseline_total, "total", t)
    ]
    running = wf.baseline_total
    for row in priced:
        assert row.saving is not None
        bars.append(
            _bar(
                f"{t('row_saving')}: {t('block_' + row.block)}",
                running - row.saving,
                running,
                "saving",
                t,
                value=row.saving,
            )
        )
        running -= row.saving
    bars.append(_bar(t("row_after"), 0, wf.after_total, "total", t))
    return tuple(bars)


def _bar(
    label: str,
    start: Decimal | int,
    end: Decimal,
    kind: str,
    t: _Text,
    *,
    value: Decimal | None = None,
) -> dict[str, object]:
    shown = end - start if value is None else value
    return {
        "label": label,
        "start": float(start),
        "end": float(end),
        "kind": kind,
        "text": t.amount(Decimal(shown)),
    }


# --- cache monitor (UI-R25) and greeting gate (UI-R27) ---


def _count(values: Mapping[str, Decimal], key: str) -> int | None:
    value = values.get(key)
    return None if value is None else int(value)


def cache_monitor(results: Sequence[LeverResult]) -> tuple[CacheRow, ...]:
    """Counts from the cache results' own slices; absent counts stay None.

    - ``retrieval`` slice (retrieval-result cache): misses = lookups − hits −
      guard blocks − ineligible (its four lookup statuses).
    - ``session_memo`` slice (session memo + greeting gate): hits = reused,
      misses = lookups that ran (``n_performed``).
    - otherwise the ``all`` slice's ``n_cache_hits``: misses = eligible requests
      not served from the cache.
    No result carries guard-block reasons yet, so ``guard_reasons`` is None.
    """
    rows = []
    for r in sorted(results, key=version_key):
        if r.step != "cache":
            continue
        if "retrieval" in r.slices:
            s = r.slices["retrieval"]
            parts = [
                _count(s, k)
                for k in ("n_lookups_llm", "n_hits", "n_guard_blocks", "n_ineligible")
            ]
            lookups, hits, guard, ineligible = parts
            misses = (
                lookups - hits - guard - ineligible  # type: ignore[operator]
                if None not in parts
                else None
            )
            rows.append(
                CacheRow(
                    version_key(r),
                    "retrieval",
                    lookups=lookups,
                    hits=hits,
                    misses=misses,
                    guard_blocks=guard,
                    shadow_sampled=_count(s, "n_shadow_sampled"),
                    shadow_agree=_count(s, "n_shadow_agree"),
                    shadow_unknown=_count(s, "n_shadow_unknown"),
                )
            )
        elif "session_memo" in r.slices:
            s = r.slices["session_memo"]
            rows.append(
                CacheRow(
                    version_key(r),
                    "session_memo",
                    lookups=_count(s, "n_retrieval_turns"),
                    hits=_count(s, "n_reused"),
                    misses=_count(s, "n_performed"),
                    guard_blocks=_count(s, "n_guard_block"),
                    gate_skips=_count(s, "n_skipped_phatic"),
                )
            )
        else:
            hits = _count(r.slices["all"], "n_cache_hits")
            misses = (
                r.n_eligible - hits
                if hits is not None and hits <= r.n_eligible
                else None
            )
            rows.append(CacheRow(version_key(r), "requests", hits=hits, misses=misses))
    return tuple(rows)


def _gate(results: Sequence[LeverResult], t: _Text) -> GateView | None:
    """The greeting gate's token part (ADR-0039): recorded baseline → the
    result's token-cost saving (the memo saves fees only); repriced → the
    slice's ``token_saving_lower_bound``."""
    for r in sorted(results, key=version_key):
        if r.step != "cache" or "session_memo" not in r.slices:
            continue
        s = r.slices["session_memo"]
        repriced = cost_unit(r.baseline) == "repriced"
        value = (
            s.get("token_saving_lower_bound")
            if repriced
            else r.saving.get("token_cost")
        )
        return GateView(
            version=version_key(r),
            token_saving=value,
            lower_bound=repriced,
            skipped=_count(s, "n_skipped_phatic"),
            unit=t.unit(r),
            note=t("gate_lower_bound") if repriced else "",
            text=t.amount(value),
            skipped_text=t.count(_count(s, "n_skipped_phatic")),
        )
    return None


# --- routing per bot (UI-R26) ---


def _routing(result: LeverResult, cap: Decimal, t: _Text) -> RoutingTable:
    repriced = cost_unit(result.baseline) == "repriced"
    bots, tenants, other_units = [], [], False
    for name in sorted(result.slices, key=_rank_order):
        match = _RANK.match(name)
        if not match:
            continue
        s, label = result.slices[name], rank_label(match[1], int(match[2]))
        if match[1] == "bot":
            other_units |= repriced and "baseline:fees" in s
            n, moved = _count(s, "n_requests"), _count(s, "n_moved")
            bots.append(
                BotRow(
                    label=label,
                    n_requests=n,
                    n_moved=moved,
                    moved_share=Decimal(moved) / Decimal(n)
                    if n and moved is not None
                    else None,
                    saving=None if other_units else s.get("saving:total"),
                    saving_share=s.get("saving_share"),
                    share_of_saving=s.get("share_of_saving"),
                    insufficient=s.get("insufficient", Decimal(0)) != 0,
                )
            )
        else:
            share = s.get("share")
            flagged = share is not None and share > cap
            tenants.append(
                TenantRow(
                    label=label,
                    n_requests=_count(s, "n_requests"),
                    share=share,
                    flagged=flagged,
                    flag_text=t("flag_over_cap", cap=f"\u2066{t.share(cap)}\u2069")
                    if flagged
                    else t("flag_ok"),
                    saving_share=s.get("saving_share"),
                    share_of_saving=s.get("share_of_saving"),
                )
            )
    message = None
    if not bots:
        message = t("routing_none")
    elif other_units:
        message = t("slice_other_units")
    traffic = result.slices.get("traffic_weighted", {}).get("saving_share")
    return RoutingTable(
        traffic_weighted_text=t.share(traffic),
        version=version_key(result),
        bots=tuple(bots),
        tenants=tuple(tenants),
        traffic_weighted_share=result.slices.get("traffic_weighted", {}).get(
            "saving_share"
        ),
        caveats=tuple(result.assumptions),
        message=message,
    )


def _rank_order(name: str) -> tuple[str, int]:
    match = _RANK.match(name)
    return (match[1], int(match[2])) if match else ("", 0)


# --- compact layout (UI Stage 2b, owner review point 5) ---

BOT_CHART_MAX = 15
"""Bars in the per-bot chart: the first ranks only; the full list stays in the
folded table."""


def _summaries(
    tables: Mapping[str, Sequence[dict[str, str]]],
    comparison: Mapping[str, Sequence[ComparisonRow]],
    routing: RoutingTable | None,
    t: _Text,
) -> dict[str, str]:
    """One line per table, the label of its folded expander."""
    out = {}
    for key, rows in tables.items():
        kind, _, step = key.partition(":")
        if kind == "waterfall":
            out[key] = t("sum_waterfall", n=len(rows))
        elif kind == "comparison":
            ranked = sum(r.status == "ranked" for r in comparison.get(step, ()))
            out[key] = t("sum_comparison", n=len(rows), ranked=ranked)
        elif kind == "cache":
            out[key] = t("sum_cache", n=len(rows))
    if routing is not None:
        few = sum(b.insufficient for b in routing.bots)
        over = sum(r.flagged for r in routing.tenants)
        out["bots"] = t("sum_bots", n=len(routing.bots), few=few)
        out["tenants"] = t("sum_tenants", n=len(routing.tenants), over=over)
    return out


def _count_card(key: str, label: str, n: int | None, t: _Text) -> Card:
    return Card(key, label, None if n is None else Decimal(n), t.count(n))


def _cache_cards(
    cache: Sequence[CacheRow], chosen: str | None, t: _Text
) -> tuple[Card, ...]:
    """The chosen cache version's counts, as stored (``cache_monitor``)."""
    row = next((r for r in cache if r.version == chosen), None)
    if row is None:
        return ()
    cards = [
        _count_card(k, t(k), getattr(row, k), t)
        for k in ("lookups", "hits", "misses", "guard_blocks")
    ]
    if row.gate_skips is not None:
        cards.append(_count_card("gate_skips", t("gate_skips"), row.gate_skips, t))
    return tuple(cards)


def _routing_cards(routing: RoutingTable | None, t: _Text) -> tuple[Card, ...]:
    if routing is None:
        return ()
    share = routing.traffic_weighted_share
    return (
        Card(
            "traffic_weighted_share",
            t("traffic_weighted_share"),
            share,
            t.share(share),
        ),
        _count_card("bots_count", t("bots_count"), len(routing.bots), t),
        _count_card(
            "tenants_over_cap",
            t("tenants_over_cap"),
            sum(r.flagged for r in routing.tenants),
            t,
        ),
    )


def _bot_chart(routing: RoutingTable | None, t: _Text) -> tuple[dict[str, object], ...]:
    """Share of the saving per bot rank, in rank order; bots without the value
    are left out (UI-G08)."""
    if routing is None:
        return ()
    rows = [b for b in routing.bots if b.share_of_saving is not None]
    return tuple(
        {
            "label": b.label,
            "value": float(b.share_of_saving),  # type: ignore[arg-type]
            "text": t.share(b.share_of_saving),
        }
        for b in rows[:BOT_CHART_MAX]
    )


def _tenant_chart(
    routing: RoutingTable | None, t: _Text
) -> tuple[dict[str, object], ...]:
    if routing is None:
        return ()
    return tuple(
        {
            "label": r.label,
            "value": float(r.share),
            "text": t.share(r.share),
            "flag": r.flag_text,
            "flagged": r.flagged,
        }
        for r in routing.tenants
        if r.share is not None
    )
