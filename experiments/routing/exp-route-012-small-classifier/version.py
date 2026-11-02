"""EXP-ROUTE-012: small classifier, a routing ``StepVersion`` (final plan R-C3;
FR-ROUTE-01..05, FR-REQ-06, H-5; ADR-0045, ADR-0046).

**Two modes** (owner decision 2026-11-03), ``SmallClassifier(mode, ...)``:

- ``"rules"``: a transparent threshold rule. A request is *simple* only if its
  user message is short (``u_n_chars <= max_u_chars``), it has no RAG
  (``a_rag_n_queries == 0``), no attachments (``u_att_n == 0``), its bot has no
  configured functions (``bot_n_functions == 0``) and its effective input is at
  most ``max_input_tokens``. Unknown is never simple. No threshold has a
  default: the script freezes them (README).
- ``"logistic"``: numpy logistic regression (``fit_logistic``, L2, Newton
  steps) on the pre-generation features ``FEATURES``, trained only from labels
  whose source is declared (``labels_source`` ``synthetic:<name>`` or
  ``benchmark:<name>``; None refuses). Never labels from logged answers or
  cost. ``nested_cv`` chooses the L2 strength in session- and family-grouped
  nested cross-validation. No real labels exist yet (P-1..P-3 not run).

**Features** come only from information available before generation
(FR-REQ-06): ``FEATURES``. ``feature_matrix`` refuses any other column, so an
answer-derived one (``a_n_chars``, ``a_is_json``, ``a_finish_reason``,
``a_tool_n_calls``, output tokens, cost) can never enter.

**Routing** (``apply``): eligibility and candidate cost come only from
``analysis.routing_base`` (``eligibility_frame``, ``candidate_costs``; NaN =
not eligible, never 0). A simple request's *target* is the cheapest eligible
candidate (ties: candidate order); it moves only if the target is strictly
cheaper than the incumbent (the logged model at list price,
``baselines_full.model_row_costs``) and is another model. Never upward;
everything else keeps its incumbent; fees never change. ``route_reason``
records why: routing_base's first failing reason, ``no_eligible_candidate``,
``not_simple``, ``incumbent_unpriced``, ``no_cheaper_candidate`` or
``moved``.

**Reasoning models** (owner decision 2026-11-03): a candidate whose catalogue
row has the capability ``hidden_reasoning_billed_as_output`` has a list-price
cost that ignores its hidden reasoning. The primary version refuses such a
candidate (``candidate_sets``); ``include_reasoning_models=True`` gives the
secondary version, a *lower bound on candidate cost*.

**Per baseline** (``baseline_frames``), the incumbent is the baseline's model
for the row and the same strict rule applies in that baseline's units:
repriced baselines compare the target's list cost with the baseline's
(``baselines_full.repriced_row_costs``); ``as_logged`` compares the target's
cost at its implied recorded-unit rates (``implied_unit_rates.csv``) with the
recorded ``block_token_cost``. A target without the rates it needs makes the
saving unknown (the row leaves both sides), never 0; rows not moved save
exactly 0.

Evidence: *simulation* (logged tokens assumed model-independent).
Candidate code: loaded by file path only (scripts, tests); ``metis_auto`` never
imports it.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd

from metis_auto.analysis.baselines_full import (
    REPRICED_KEYS,
    model_row_costs,
    repriced_row_costs,
    token_counts,
)
from metis_auto.analysis.lever_result import LeverResult, Manifest
from metis_auto.analysis.levers import (
    BLOCKS,
    ReplayContext,
    Step,
    block_column,
    summarise_slices,
)
from metis_auto.analysis.replay_scope import bot_sufficiency
from metis_auto.analysis.routing_base import (
    REASON_COLUMN,
    candidate_costs,
    candidate_list,
    eligibility_frame,
)
from metis_auto.analysis.stats import cluster_bootstrap_ratio

VERSION_PREFIX = "route.small_classifier"
EVIDENCE = "simulation"
MODES = ("rules", "logistic")
REASONING_CAPABILITY = "hidden_reasoning_billed_as_output"
OVER_8K_TOKENS = 8000
TOP_BOTS = 20
TOP_TENANTS = 10
QUALITY_NOT_PROVEN = "quality not proven: no labels (P-1..P-3 not run)"
LABEL_SOURCE = re.compile(r"^(synthetic|benchmark):[a-z0-9][a-z0-9_.\-]*$")

FEATURES = (
    "u_n_chars",
    "u_lang",
    "turn",
    "n_prior_msgs",
    "prior_chars",
    "a_rag_n_queries",
    "u_att_n",
    "bot_n_functions",
    "bot_ins_n_chars",
    "input_tokens",
)
"""Known before generation (FR-REQ-06): user message length and language, turn,
history size, RAG presence (retrieval runs before the answer), attachments,
configured functions, bot instruction size, effective input tokens."""
LANGS = ("fa", "fa_en_mixed", "short_uncertain", "arabic_script_other", "en")
LANGS += ("structured", "other")

SIMPLE = "route_simple"
TARGET = "route_target"
TARGET_COST = "route_target_cost"
INCUMBENT_COST = "route_incumbent_cost"
MOVED = "route_moved"
ROUTED = "routed_model"
REASON = "route_reason"
N_ELIGIBLE = "route_n_eligible"
INPUT_TOKENS = "route_input_tokens"
OVER_8K = "route_over_8k"
MOVED_B = "route_moved_in_baseline"
SAVING_UNKNOWN = "route_saving_unknown"


# --- candidates ------------------------------------------------------------------


def reasoning_models(catalogue: Mapping[str, Any] | pd.DataFrame) -> frozenset[str]:
    """Catalogue models whose row lists ``REASONING_CAPABILITY``."""
    rows = (
        catalogue.to_dict("records")
        if isinstance(catalogue, pd.DataFrame)
        else list(catalogue.get("models", []))
    )
    found = set()
    for m in rows:
        caps = m.get("capabilities") or ()
        if any(
            isinstance(c, Mapping) and c.get("name") == REASONING_CAPABILITY
            for c in caps
        ):
            found.add(str(m["model_id"]))
    return frozenset(found)


def candidate_sets(
    rules: Mapping[str, Any], catalogue: Mapping[str, Any] | pd.DataFrame
) -> dict[str, tuple[str, ...]]:
    """``primary`` (reasoning models excluded) and ``with_reasoning_models``
    (every routing candidate), in ``candidate_list`` order."""
    every = candidate_list(rules)
    hidden = reasoning_models(catalogue)
    return {
        "primary": tuple(m for m in every if m not in hidden),
        "with_reasoning_models": every,
    }


# --- features and labels ---------------------------------------------------------


def feature_matrix(
    req: pd.DataFrame,
    features: Sequence[str] = FEATURES,
    *,
    cached_separately: frozenset[str],
) -> pd.DataFrame:
    """Numeric features (``log1p`` of counts, one-hot language), NaN = unknown.
    Refuses any feature outside ``FEATURES``."""
    bad = [f for f in features if f not in FEATURES]
    if bad:
        raise ValueError(
            f"features {bad} are not known before generation (FR-REQ-06); "
            f"allowed: {FEATURES}"
        )
    cols: dict[str, pd.Series] = {}
    for f in features:
        if f == "u_lang":
            lang = req["u_lang"]
            for label in LANGS:
                cols[f"lang:{label}"] = lang.eq(label).astype(float)
            cols["lang:missing"] = lang.isna().astype(float)
            continue
        if f == "input_tokens":
            value = token_counts(req, cached_separately)["input"]
        else:
            value = pd.to_numeric(req[f], errors="coerce")
        cols[f] = np.log1p(value.astype(float).clip(lower=0))
    return pd.DataFrame(cols, index=req.index)


def _check_source(labels_source: str | None) -> str:
    if labels_source is None:
        raise ValueError(
            "labels_source is required: no labels without a declared source "
            "(P-3 benchmark labels, or synthetic in tests)"
        )
    if not isinstance(labels_source, str) or not LABEL_SOURCE.match(labels_source):
        raise ValueError(
            f"labels_source {labels_source!r} is not declared: use "
            "'benchmark:<name>' or 'synthetic:<name>'; never logged answers or cost"
        )
    return labels_source


@dataclass(frozen=True, eq=False)
class LogisticModel:
    """A fitted logistic regression; ``proba`` imputes the training medians."""

    features: tuple[str, ...]
    columns: tuple[str, ...]
    medians: np.ndarray
    mean: np.ndarray
    scale: np.ndarray
    coef: np.ndarray
    intercept: float
    labels_source: str
    l2: float
    threshold: float = 0.5

    def proba(
        self, req: pd.DataFrame, *, cached_separately: frozenset[str]
    ) -> pd.Series:
        x = feature_matrix(req, self.features, cached_separately=cached_separately)
        z = self._design(x[list(self.columns)].to_numpy(dtype=float))
        return pd.Series(_sigmoid(z @ self.coef + self.intercept), index=req.index)

    def _design(self, x: np.ndarray) -> np.ndarray:
        x = np.where(np.isnan(x), self.medians, x)
        return (x - self.mean) / self.scale


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def fit_logistic(
    train: pd.DataFrame,
    labels: pd.Series,
    *,
    labels_source: str | None,
    l2: float,
    cached_separately: frozenset[str],
    features: Sequence[str] = FEATURES,
    iterations: int = 50,
) -> LogisticModel:
    """L2-penalised logistic regression by Newton steps (numpy only).

    ``labels`` (bool, ``train``'s index; NaN rows dropped) must come from a
    declared source (``_check_source``)."""
    source = _check_source(labels_source)
    if l2 <= 0:
        raise ValueError("l2 must be positive")
    x_frame = feature_matrix(train, features, cached_separately=cached_separately)
    y_all = labels.reindex(train.index)
    keep = y_all.notna().to_numpy()
    x = x_frame.to_numpy(dtype=float)[keep]
    y = y_all[keep].astype(bool).to_numpy(dtype=float)
    if len(y) == 0:
        raise ValueError("no labelled rows to fit")
    medians = np.nan_to_num(np.nanmedian(np.where(np.isnan(x).all(0), 0, x), axis=0))
    x = np.where(np.isnan(x), medians, x)
    mean, scale = x.mean(axis=0), x.std(axis=0)
    scale = np.where(scale > 0, scale, 1.0)
    z = np.column_stack([np.ones(len(x)), (x - mean) / scale])
    w = np.zeros(z.shape[1])
    penalty = np.full(z.shape[1], float(l2))
    penalty[0] = 1e-6  # the intercept is (almost) not penalised
    for _ in range(iterations):
        p = _sigmoid(z @ w)
        grad = z.T @ (p - y) + penalty * w
        hess = (z * (p * (1 - p))[:, None]).T @ z + np.diag(penalty)
        step = np.linalg.solve(hess, grad)
        w -= step
        if np.max(np.abs(step)) < 1e-8:
            break
    return LogisticModel(
        features=tuple(features),
        columns=tuple(x_frame.columns),
        medians=medians,
        mean=mean,
        scale=scale,
        coef=w[1:],
        intercept=float(w[0]),
        labels_source=source,
        l2=float(l2),
    )


def _log_loss(p: np.ndarray, y: np.ndarray) -> float:
    p = np.clip(p, 1e-12, 1 - 1e-12)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def component_folds(req: pd.DataFrame, *, n_folds: int, seed: int) -> pd.Series:
    """Fold per row. Sessions joined by a duplicate family (``bot_id`` +
    ``u_h_norm``, as in ``replay_scope``; a missing ``u_h_norm`` joins nothing)
    form one component, and a component never spans two folds. Components are
    ordered by a seeded hash and dealt round-robin, so folds are balanced."""
    sessions = req["session_id"].astype(str).to_numpy()
    parent = {s: s for s in pd.unique(sessions)}

    def root(s: str) -> str:
        while parent[s] != s:
            parent[s] = parent[parent[s]]
            s = parent[s]
        return s

    has = req["u_h_norm"].notna().to_numpy()
    fam = (req["bot_id"].astype(str) + "\x1f" + req["u_h_norm"].astype(str)).to_numpy()
    first: dict[str, str] = {}
    for s, f in zip(sessions[has], fam[has], strict=True):
        if f in first:
            a, b = root(first[f]), root(s)
            if a != b:
                parent[max(a, b)] = min(a, b)
        else:
            first[f] = s
    comp = np.array([root(s) for s in sessions])
    order = sorted(
        pd.unique(comp),
        key=lambda c: hashlib.blake2b(
            f"{seed}\x1f{c}".encode(), digest_size=8
        ).digest(),
    )
    fold = {c: i % n_folds for i, c in enumerate(order)}
    return pd.Series([fold[c] for c in comp], index=req.index, name="fold")


def nested_cv(
    req: pd.DataFrame,
    labels: pd.Series,
    *,
    labels_source: str | None,
    l2_grid: Sequence[float],
    outer: int,
    inner: int,
    seed: int,
    min_n: int | None,
    cached_separately: frozenset[str],
    features: Sequence[str] = FEATURES,
    fit: Callable[..., LogisticModel] = fit_logistic,
    n_boot: int = 500,
) -> dict[str, Any]:
    """Session- and family-grouped nested CV of the logistic mode.

    Inner folds of each outer training part choose ``l2`` by mean log loss
    (ties: the stronger penalty); the outer fold is scored by a model fitted on
    its training part only. Fewer labelled rows than ``min_n``: ``status``
    ``insufficient``, no estimate. Otherwise the out-of-fold accuracy with a
    session-clustered bootstrap interval (``analysis.stats``)."""
    source = _check_source(labels_source)
    if min_n is None:
        raise ValueError("min_n is required (sprint.toml [sufficiency])")
    rows = labels.reindex(req.index).notna()
    data, y = req[rows], labels.reindex(req.index)[rows].astype(bool)
    folds = component_folds(data, n_folds=outer, seed=seed)
    base = {"labels_source": source, "n_labels": int(len(y)), "outer_folds": folds}
    if len(y) < min_n:
        return base | {
            "status": "insufficient",
            "accuracy": None,
            "ci": None,
            "outer": [],
        }
    kw = dict(
        labels_source=source, features=features, cached_separately=cached_separately
    )
    oof = pd.Series(np.nan, index=data.index)
    record = []
    for f in range(outer):
        train, test = data[folds != f], data[folds == f]
        if train.empty or test.empty:
            continue
        ifolds = component_folds(train, n_folds=inner, seed=seed + 1 + f)
        losses = {}
        for l2 in l2_grid:
            scores = []
            for g in range(inner):
                itrain, itest = train[ifolds != g], train[ifolds == g]
                if itrain.empty or itest.empty:
                    continue
                m = fit(itrain, y[itrain.index], l2=l2, **kw)
                p = m.proba(itest, cached_separately=cached_separately).to_numpy()
                scores.append(_log_loss(p, y[itest.index].to_numpy(dtype=float)))
            losses[l2] = float(np.mean(scores)) if scores else math.inf
        chosen = min(losses, key=lambda k: (losses[k], -k))
        model = fit(train, y[train.index], l2=chosen, **kw)
        p = model.proba(test, cached_separately=cached_separately)
        oof[test.index] = p
        truth = y[test.index].to_numpy(dtype=float)
        record.append(
            {
                "fold": f,
                "l2": chosen,
                "n_train": int(len(train)),
                "n_test": int(len(test)),
                "accuracy": float(np.mean((p.to_numpy() >= 0.5) == truth.astype(bool))),
                "log_loss": _log_loss(p.to_numpy(), truth),
            }
        )
    scored = oof.notna()
    correct = ((oof[scored] >= 0.5) == y[scored]).to_numpy(dtype=float)
    est, lo, hi = cluster_bootstrap_ratio(
        correct,
        np.ones(len(correct)),
        data.loc[scored, "session_id"].astype(str).to_numpy(),
        n_boot=n_boot,
        seed=seed,
    )
    return base | {
        "status": "estimated",
        "accuracy": est,
        "ci": (lo, hi),
        "outer": record,
        "oof_proba": oof,
    }


def least_aggressive(
    table: Mapping[Any, Mapping[str, float]], *, tolerance: float
) -> Any:
    """Among settings whose ``saving_share`` is within ``tolerance`` of the best,
    the one that moves the fewest requests (ties: the smaller setting)."""
    best = max(t["saving_share"] for t in table.values())
    near = [
        k for k, t in table.items() if t["saving_share"] >= best - tolerance - 1e-12
    ]
    return min(near, key=lambda k: (table[k]["moved_share"], k))


# --- the version -----------------------------------------------------------------


def rule_simple(
    req: pd.DataFrame,
    *,
    max_u_chars: float,
    max_input_tokens: float,
    cached_separately: frozenset[str],
) -> pd.Series:
    """The ``rules`` mode test; unknown (NaN) is never simple."""

    def num(col: str) -> pd.Series:
        return pd.to_numeric(req[col], errors="coerce")

    eff = token_counts(req, cached_separately)["input"]
    return (
        num("u_n_chars").le(max_u_chars)
        & num("a_rag_n_queries").eq(0)
        & num("u_att_n").eq(0)
        & num("bot_n_functions").eq(0)
        & eff.le(max_input_tokens)
    ).astype(bool)


class SmallClassifier:
    """Routing ``StepVersion`` (module docstring). No threshold has a default."""

    step: Step = "routing"

    def __init__(
        self,
        mode: str,
        *,
        rules: Mapping[str, Any],
        candidates: Sequence[str],
        cached_separately: frozenset[str],
        max_u_chars: float | None = None,
        max_input_tokens: float | None = None,
        model: LogisticModel | None = None,
        include_reasoning_models: bool = False,
    ) -> None:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, not {mode!r}")
        if mode == "rules" and (max_u_chars is None or max_input_tokens is None):
            raise ValueError("rules mode needs max_u_chars and max_input_tokens")
        if mode == "logistic":
            if model is None:
                raise ValueError(
                    "logistic mode needs a model fitted on declared labels"
                )
            _check_source(model.labels_source)
        allowed = candidate_list(rules)
        if not candidates or any(c not in allowed for c in candidates):
            raise ValueError(f"candidates must be routing candidates: {allowed}")
        self.mode = mode
        self.rules = rules
        self.candidates = tuple(candidates)
        self.cached_separately = cached_separately
        self.max_u_chars = max_u_chars
        self.max_input_tokens = max_input_tokens
        self.model = model
        self.include_reasoning_models = include_reasoning_models
        suffix = ".with_reasoning_models" if include_reasoning_models else ""
        self.name = f"{VERSION_PREFIX}.{mode}{suffix}"

    def simple(self, req: pd.DataFrame) -> pd.Series:
        if self.mode == "rules":
            return rule_simple(
                req,
                max_u_chars=self.max_u_chars,
                max_input_tokens=self.max_input_tokens,
                cached_separately=self.cached_separately,
            )
        p = self.model.proba(req, cached_separately=self.cached_separately)
        return (p >= self.model.threshold).astype(bool)

    def apply(self, req: pd.DataFrame, ctx: ReplayContext) -> pd.DataFrame:
        hidden = reasoning_models(ctx.catalogue) & set(self.candidates)
        if hidden and not self.include_reasoning_models:
            raise ValueError(
                f"{sorted(hidden)} have {REASONING_CAPABILITY}: excluded from the "
                "primary version (include_reasoning_models=True for the lower bound)"
            )
        sep = self.cached_separately
        out = req.copy()
        simple = self.simple(req)
        elig = eligibility_frame(req, ctx, rules=self.rules, cached_separately=sep)
        costs = candidate_costs(
            req, ctx, self.candidates, rules=self.rules, cached_separately=sep
        )
        arr = costs[list(self.candidates)].to_numpy(dtype=float)
        has = ~np.isnan(arr).all(axis=1)
        pick = np.argmin(np.where(np.isnan(arr), np.inf, arr), axis=1)
        names = np.array(self.candidates, dtype=object)
        target = pd.Series(
            np.where(has, names[pick], None), index=req.index, dtype=object
        )
        target_cost = pd.Series(
            np.where(has, arr[np.arange(len(arr)), pick], np.nan), index=req.index
        )
        tokens = token_counts(req, sep)
        incumbent = req["bot_provider_model"].astype(object)
        known_models = _model_ids(ctx.catalogue)
        inc_cost = pd.Series(np.nan, index=req.index)
        for model in pd.unique(incumbent.dropna()):
            if str(model) in known_models:
                rows = incumbent.eq(model)
                cost = model_row_costs(
                    req, ctx, str(model), cached_separately=sep, tokens=tokens
                )
                inc_cost[rows] = cost[rows]
        moved = (
            simple & target.notna() & target_cost.lt(inc_cost) & target.ne(incumbent)
        )
        reason_base = elig[REASON_COLUMN]
        any_ours = elig[list(self.candidates)].any(axis=1)
        reason = np.select(
            [
                ~any_ours & reason_base.notna(),
                ~any_ours,
                ~simple,
                inc_cost.isna(),
                ~moved,
            ],
            [
                reason_base.astype(object),
                "no_eligible_candidate",
                "not_simple",
                "incumbent_unpriced",
                "no_cheaper_candidate",
            ],
            "moved",
        )
        out[SIMPLE] = simple
        out[TARGET] = target
        out[TARGET_COST] = target_cost
        out[INCUMBENT_COST] = inc_cost
        out[MOVED] = moved.astype(bool)
        out[ROUTED] = incumbent.where(~moved, target)
        out[REASON] = pd.Series(reason, index=req.index, dtype=object)
        out[N_ELIGIBLE] = elig[list(self.candidates)].sum(axis=1).astype(int)
        out[INPUT_TOKENS] = tokens["input"]
        out[OVER_8K] = tokens["input"].gt(OVER_8K_TOKENS)
        return out


def _model_ids(catalogue: Mapping[str, Any] | pd.DataFrame) -> frozenset[str]:
    rows = (
        catalogue.to_dict("records")
        if isinstance(catalogue, pd.DataFrame)
        else list(catalogue.get("models", []))
    )
    return frozenset(str(m["model_id"]) for m in rows)


# --- per baseline ----------------------------------------------------------------


def implied_cost(
    tokens: pd.DataFrame, model: pd.Series, rates: Mapping[str, Mapping[str, float]]
) -> pd.Series:
    """Recorded-unit cost of each row on ``model`` at its implied rates per 1M
    tokens (``input``, ``output``, ``cached``). A rate is needed only for a token
    part above 0; a needed rate that is missing gives NaN (unknown)."""
    out = pd.Series(np.nan, index=tokens.index)
    uncached = tokens["input"] - tokens["cached"]
    for m in pd.unique(model.dropna()):
        rows = model.eq(m)
        r = rates.get(str(m), {})
        total = pd.Series(0.0, index=tokens.index)[rows]
        for part, rate_key in (
            (uncached, "input"),
            (tokens["cached"], "cached"),
            (tokens["output"], "output"),
        ):
            rate = r.get(rate_key, np.nan)
            rate = np.nan if rate is None else float(rate)
            value = part[rows]
            total = total + (value * rate).where(value.ne(0), 0.0).where(value.notna())
        out[rows] = total / 1e6
    return out


def baseline_frames(
    req: pd.DataFrame,
    out: pd.DataFrame,
    ctx: ReplayContext,
    *,
    baseline: str,
    premium_model: str,
    cached_separately: frozenset[str],
    cheap_model: str,
    rates: Mapping[str, Mapping[str, float]],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Before and after cost blocks of one baseline, for ``summarise_slices``.

    The incumbent is the baseline's model for the row: the logged model
    (``as_logged``, ``todays_models``), the premium model, or the best single
    cheap model. A simple row moves (``MOVED_B``) only if its target is another
    model and strictly cheaper in the baseline's units. ``as_logged``: recorded
    blocks, the target at ``implied_cost``; an unknown target cost removes the
    row from both sides (``SAVING_UNKNOWN``). Repriced: list prices;
    ``block_fees`` is 0 on both sides only so the slices sum (``lever_result``
    drops the baseline fee)."""
    llm = req["llm_request"].astype(bool)
    before = req[["llm_request"]].copy()
    after = before.copy()
    fee_col, tok_col = (block_column(b) for b in BLOCKS)
    target = out[TARGET].reindex(req.index)
    candidate = (
        out[SIMPLE].reindex(req.index).fillna(False).astype(bool) & target.notna()
    )
    if baseline == "as_logged":
        tokens = token_counts(req, cached_separately)
        cost = implied_cost(tokens, target.where(candidate), rates)
        recorded = req[tok_col]
        unknown = candidate & cost.isna() & recorded.notna()
        moved = (
            candidate & cost.lt(recorded) & target.ne(req["bot_provider_model"])
        ).astype(bool)
        before[fee_col] = req[fee_col].where(~unknown)
        after[fee_col] = req[fee_col].where(~unknown)
        before[tok_col] = recorded.where(~unknown)
        after[tok_col] = recorded.where(~moved, cost).where(~unknown)
    elif baseline in REPRICED_KEYS:
        inc = repriced_row_costs(
            req,
            ctx,
            premium_model=premium_model,
            cached_separately=cached_separately,
            cheap_model=cheap_model,
        )[baseline]
        inc_model = {
            "todays_models": req["bot_provider_model"],
            "premium_gpt_5_5": pd.Series(premium_model, index=req.index),
            "best_single_cheap": pd.Series(cheap_model, index=req.index),
        }[baseline]
        cost = out[TARGET_COST].reindex(req.index)
        moved = (candidate & cost.lt(inc) & target.ne(inc_model)).astype(bool)
        unknown = pd.Series(False, index=req.index)
        zero = (inc * 0.0).where(inc.notna())
        before[fee_col], after[fee_col] = zero, zero
        before[tok_col] = inc
        after[tok_col] = inc.where(~moved, cost)
    else:
        raise ValueError(f"unknown baseline {baseline}")
    after[MOVED_B] = moved & llm
    after[SAVING_UNKNOWN] = unknown & llm
    return before, after


# --- the result ------------------------------------------------------------------


def _decimal(value: float) -> Decimal:
    """Fixed nine-decimal Decimal (and no negative zero), as in ``levers``."""
    return Decimal(f"{value + 0.0:.9f}")


def _fsum(values: pd.Series) -> float:
    return math.fsum(values.dropna().to_numpy(dtype=float))


def assumptions(baseline: str, version: SmallClassifier) -> tuple[str, ...]:
    """The authored assumptions of one result (``LeverResult.assumptions``)."""
    if version.mode == "rules":
        how = (
            f"Rule: simple = u_n_chars <= {version.max_u_chars:g}, no RAG query, no "
            "attachment (unknown = not simple), no configured function, effective "
            f"input <= {version.max_input_tokens:g} tokens; pre-generation only."
        )
        quality = QUALITY_NOT_PROVEN
    else:
        how = (
            "Logistic regression (numpy) on pre-generation features; labels from "
            f"{version.model.labels_source} (declared source)."
        )
        quality = (
            f"quality not proven: labels {version.model.labels_source}; only "
            "benchmark judgements (P-3) could support quality."
        )
    if version.include_reasoning_models:
        cands = (
            "lower bound on candidate cost, hidden reasoning not counted: candidates "
            f"with {REASONING_CAPABILITY} are included at list price."
        )
    else:
        cands = (
            f"Candidates with {REASONING_CAPABILITY} excluded (catalogue): their "
            "list-price cost ignores hidden reasoning tokens."
        )
    price = (
        "as_logged: recorded token cost less the routed model's cost at its implied "
        "rates (implied_unit_rates.csv, recorded units); a missing rate is unknown, "
        "never zero."
        if baseline == "as_logged"
        else "Repriced: incumbent = the baseline's model; target at list price "
        "(routing_base.candidate_costs). Fees not priced in price-file units "
        "(ADR-0036), so baseline_cost has no fees key."
    )
    return (
        quality,
        how,
        cands,
        "Cost simulation: logged tokens assumed model-independent (tokenizers "
        "differ); logged output length unchanged.",
        "Eligibility and candidate cost: analysis.routing_base (ADR-0045); the "
        "cheapest eligible candidate moves only if strictly cheaper, never upward.",
        price,
        "Fees unchanged by routing; rows not moved save exactly 0.",
    )


def _ranked(keys: pd.Series, rows: pd.Series) -> list[Any]:
    """Keys ranked by LLM request count (ties: first appearance); never shown."""
    counts = keys[rows].value_counts(sort=False)
    first = {k: i for i, k in enumerate(pd.unique(keys[rows]))}
    return sorted(counts.index, key=lambda k: (-counts[k], first[k]))


def lever_result(
    before: pd.DataFrame,
    after: pd.DataFrame,
    out: pd.DataFrame,
    *,
    version_id: str,
    baseline: str,
    manifest: Manifest,
    assumptions: Sequence[str],
    min_n: int | None,
    tenant_cap: float,
) -> LeverResult:
    """One ``LeverResult``: slices ``all``, ``llm_only``, ``over_8k``,
    ``traffic_weighted`` (per-bot saving shares weighted by LLM requests),
    ``bot_rank:<n>`` (largest bots; below ``min_n`` ``insufficient``, no share),
    ``tenant_rank:<n>`` (``share`` of LLM requests, ``over_cap`` above
    ``tenant_cap``) and ``routing`` (counts, targets, concentration). Ranks
    only, never IDs. Top-level blocks from ``llm_only``; fee saving 0; a
    session-clustered interval on the ``llm_only`` saving share."""
    fee_col, tok_col = (block_column(b) for b in BLOCKS)
    llm = before["llm_request"].astype(bool)
    repriced = baseline in REPRICED_KEYS
    unknown = after[SAVING_UNKNOWN].astype(bool)
    known = llm & before[[fee_col, tok_col]].notna().all(axis=1)
    moved = after[MOVED_B].astype(bool)
    base_row = (before[fee_col] + before[tok_col]).where(known, 0.0)
    save_row = (base_row - (after[fee_col] + after[tok_col])).where(known, 0.0)

    def tidy(s: dict[str, Decimal], rows: pd.Series) -> dict[str, Decimal]:
        s["n_saving_unknown"] = Decimal(int((rows & unknown).sum()))
        s["n_moved"] = Decimal(int((rows & moved).sum()))
        if repriced:
            s.pop("baseline:fees", None)
        return s

    slices = summarise_slices(before, after)
    over = out[OVER_8K].reindex(before.index).fillna(False).astype(bool)
    slices["over_8k"] = summarise_slices(before[over], after[over])["llm_only"]
    for name, rows in (
        ("all", pd.Series(True, index=llm.index)),
        ("llm_only", llm),
        ("over_8k", llm & over),
    ):
        tidy(slices[name], rows)

    bots, tenants = out["bot_id"], out["user_id"]
    status = bot_sufficiency(out[llm], min_n)
    total_save = _fsum(save_row[llm])
    weighted, weight = 0.0, 0
    for i, bot in enumerate(_ranked(bots, llm), start=1):
        rows = llm & bots.eq(bot)
        n = int(rows.sum())
        base, save = _fsum(base_row[rows]), _fsum(save_row[rows])
        if status.get(bot) == "sufficient" and base > 0:
            weighted += n * save / base
            weight += n
        if i > TOP_BOTS:
            continue
        s: dict[str, Decimal] = {
            "n_requests": Decimal(n),
            "n_moved": Decimal(int((rows & moved).sum())),
            "insufficient": Decimal(int(status.get(bot) != "sufficient")),
        }
        if status.get(bot) == "sufficient" and base > 0:
            s["baseline:total"] = _decimal(base)
            s["saving:total"] = _decimal(save)
            s["saving_share"] = _decimal(save / base)
            if total_save > 0:
                s["share_of_saving"] = _decimal(save / total_save)
        slices[f"bot_rank:{i}"] = s
    slices["traffic_weighted"] = {"n_requests": Decimal(weight)}
    if weight:
        slices["traffic_weighted"]["saving_share"] = _decimal(weighted / weight)

    n_llm = int(llm.sum())
    over_cap = 0
    max_share = 0.0
    for i, tenant in enumerate(_ranked(tenants, llm), start=1):
        rows = llm & tenants.eq(tenant)
        share = int(rows.sum()) / n_llm
        over_cap += int(share > tenant_cap)
        max_share = max(max_share, share)
        if i > TOP_TENANTS:
            continue
        base, save = _fsum(base_row[rows]), _fsum(save_row[rows])
        s = {
            "n_requests": Decimal(int(rows.sum())),
            "share": _decimal(share),
            "over_cap": Decimal(int(share > tenant_cap)),
        }
        if base > 0:
            s["saving_share"] = _decimal(save / base)
        if total_save > 0:
            s["share_of_saving"] = _decimal(save / total_save)
        slices[f"tenant_rank:{i}"] = s

    simple = out[SIMPLE].reindex(llm.index).fillna(False).astype(bool) & llm
    target = out[TARGET].reindex(llm.index)
    routing: dict[str, Decimal] = {
        "n_simple": Decimal(int(simple.sum())),
        "n_with_target": Decimal(int((simple & target.notna()).sum())),
        "n_moved": Decimal(int((llm & moved).sum())),
        "n_saving_unknown": Decimal(int((llm & unknown).sum())),
        "n_tenants_over_cap": Decimal(over_cap),
        "max_tenant_share": _decimal(max_share),
    }
    for model, n in target[llm & moved].value_counts().sort_index().items():
        routing[f"moved_to:{model}"] = Decimal(int(n))
    for reason, n in (
        out[REASON].reindex(llm.index)[llm].value_counts().sort_index().items()
    ):
        routing[f"n_reason:{reason}"] = Decimal(int(n))
    if total_save > 0:
        by_bot = save_row[llm].groupby(bots[llm]).sum().sort_values(ascending=False)
        by_tenant = save_row[llm].groupby(tenants[llm]).sum().max()
        routing["saving_share_top_bot"] = _decimal(by_bot.iloc[:1].sum() / total_save)
        routing["saving_share_top5_bots"] = _decimal(by_bot.iloc[:5].sum() / total_save)
        routing["saving_share_top_tenant"] = _decimal(by_tenant / total_save)
    slices["routing"] = routing

    ci_low = ci_high = None
    rows = known & ~unknown
    if rows.any() and _fsum(base_row[rows]) > 0:
        _, lo, hi = cluster_bootstrap_ratio(
            save_row[rows].to_numpy(dtype=float),
            base_row[rows].to_numpy(dtype=float),
            out.loc[rows[rows].index, "session_id"].astype(str).to_numpy(),
            seed=manifest.seed,
        )
        ci_low, ci_high = round(lo, 9), round(hi, 9)

    top = slices["llm_only"]
    names = (*BLOCKS, "total")
    return LeverResult(
        lever_id=f"{version_id}.{baseline}",
        step="routing",
        version=version_id,
        n_requests=len(before),
        n_eligible=int(
            (llm & (out[N_ELIGIBLE].reindex(llm.index).fillna(0) > 0)).sum()
        ),
        baseline=baseline,
        baseline_cost={
            b: top[f"baseline:{b}"] for b in names if f"baseline:{b}" in top
        },
        saving={b: top[f"saving:{b}"] for b in names},
        ci_low=ci_low,
        ci_high=ci_high,
        slices=slices,
        evidence_class=EVIDENCE,
        correctness_state="unmeasured",
        assumptions=tuple(assumptions),
        manifest=manifest,
    )
