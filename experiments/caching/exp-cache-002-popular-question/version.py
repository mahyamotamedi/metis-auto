"""Popular-question cache, a nightly curated answer cache (exp-cache-002).

Final plan R-A1; tests H-8 with the ADR-0016 Part 1 design (curated cache, rebuilt
every night from a rolling window). Traces: H-8, X1, FR-XCACHE-02, FR-XCACHE-04,
FR-XCACHE-05, ADR-0006, ADR-0007, ADR-0011, ADR-0016. A *candidate* step version
for the full-data lever replay (ADR-0031): it lives here, outside ``metis_auto``,
and is loaded only by scripts and tests through ``wiring.experiments``.

For each naive calendar day *d* of ``u_timestamp`` (Q-06), the admitted keys are
those with at least ``min_count`` eligible occurrences in at least
``min_sessions`` distinct sessions on days *d - window_days* to *d - 1*: no
look-ahead and no same-day admission. A request on day *d* is a candidate hit if
it is eligible, its key is admitted for *d*, and ``ctx.guard`` (when given)
allows ``(key, bot)``. The stored answer is the mode of ``a_h_norm`` over the
window's occurrences of the key; ties go to the most recently answered, then to
the smallest hash. ``pq_answer_agrees`` says whether a hit's own logged answer has
that hash: agreement, not correctness (ADR-0016, ``logged_match``).

Key (verified 2026-11-02 in ``analysis/ingest.py`` and ``requests_table.py``):
``bot_id`` + ``bot_ins_h_exact`` (instruction fingerprint of the bot snapshot) +
``u_h_norm`` (``fingerprint(normalize_safe(text))``), prefixed with ``key_version``
by ``cache_guard.versioned_key`` (ADR-0034: the guard refuses any other key, so the
caller passes the guard's own ``key_version``). Variants:

- ``first_turn`` (headline): only requests with no logged history may be
  admitted or hit (ADR-0016 Part 1 point 3). ``n_prior_msgs`` at an AI row counts
  every earlier USER/AI message, *including the request's own question*, so the
  first answer of a session has ``n_prior_msgs == 1``.
- ``all_turns`` (upper bound): any turn, history ignored. Unsafe for follow-ups.

``apply`` returns a copy with the same index. Hit rows get
``served_from_cache = True`` and zero known cost blocks (unknown stays unknown).
Added columns are counts and flags only (``pq_eligible``,
``pq_admitted_keys_day``, ``pq_answer_agrees``); keys stay in memory (``keys``).
"""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

from metis_auto.analysis.cache_guard import versioned_key
from metis_auto.analysis.levers import BLOCKS, ReplayContext, block_column

Variant = Literal["first_turn", "all_turns"]
VARIANTS = ("first_turn", "all_turns")
MAX_WINDOW_DAYS = 180
FIRST_TURN_PRIOR_MSGS = 1
"""Only the request's own user message precedes it (``history_columns``)."""
NO_INSTRUCTIONS = "-"
"""Key part for a bot without an instruction hash (null and blank both lack one)."""

_COMMON = (
    "Hits are candidate hits: the logged answer is not checked against the new "
    "request (ADR-0006); correctness unmeasured until the K-1 review (X1).",
    "Saving is the recorded cost of avoided calls, before lookup overhead and "
    "before the build cost (regeneration or judging) that ADR-0016 charges.",
    "Measured potential, not a serving decision: global scope within a bot; every "
    "bot has one owner account, so cross-user reuse is unmeasured (ADR-0016).",
    "Ineligible: no user text, non-STOP or empty answer, attachments, tools, "
    "actions, bad times, workflow rows, memory on or unknown, RAG run or unknown.",
    "No time-sensitivity detector exists (TODO-07): time-dependent questions can "
    "be admitted.",
    "Instructions are a bot snapshot (bot_ins_h_exact): changes over time are not "
    "seen, so the instruction key part does not split a bot's traffic.",
    "Days are naive calendar days of the user timestamp (Q-06).",
)
_FIRST_TURN = (
    "Headline variant: only requests with no logged history (n_prior_msgs == 1, "
    "the request's own question) are admitted or hit.",
)
_ALL_TURNS = (
    "Variant all_turns: upper bound, unsafe for follow-up questions; any turn, "
    "key ignores history.",
)

_REQUIRED = (
    "llm_request",
    "bot_id",
    "session_id",
    "u_timestamp",
    "a_timestamp",
    "u_content_state",
    "a_content_state",
    "a_finish_reason",
    "u_att_n",
    "a_tool_n_calls",
    "a_action_types",
    "bot_memory_enabled",
    "a_rag_state",
    "a_rag_n_queries",
    "n_prior_msgs",
    "u_h_norm",
    "a_h_norm",
    "bot_ins_h_exact",
)


def _strict_int(name: str, value: object, low: int, high: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an int, got {value!r}")
    if value < low or (high is not None and value > high):
        bound = f"between {low} and {high}" if high is not None else f">= {low}"
        raise ValueError(f"{name} must be {bound}, got {value}")
    return value


class PopularQuestionCache:
    """Nightly popular-question cache; a ``levers.StepVersion`` of step ``cache``."""

    step = "cache"
    version = "pq-v1"
    evidence_class = "simulation"
    correctness_state = "unmeasured"

    def __init__(
        self,
        window_days: int,
        min_count: int,
        min_sessions: int,
        variant: Variant,
        key_version: str,
    ) -> None:
        versioned_key(key_version, "check")  # raises on an empty or "|" version
        if variant not in VARIANTS:
            raise ValueError(f"variant must be one of {VARIANTS}, got {variant!r}")
        self.window_days = _strict_int("window_days", window_days, 1, MAX_WINDOW_DAYS)
        self.min_count = _strict_int("min_count", min_count, 1)
        self.min_sessions = _strict_int("min_sessions", min_sessions, 1)
        self.variant = variant
        self.key_version = key_version
        self.scope_check: dict[str, int] | None = None
        """Counts of the last ``apply``: hits checked, cross-bot, cross-instruction."""
        self.lever_id = f"cache.popular_question.{variant}"
        self.name = self.lever_id
        self.assumptions = _COMMON + (
            _FIRST_TURN if variant == "first_turn" else _ALL_TURNS
        )

    # --- eligibility ---------------------------------------------------------------

    def _steps(self, req: pd.DataFrame) -> list[tuple[str, pd.Series]]:
        missing = [c for c in _REQUIRED if c not in req]
        if missing:
            raise ValueError(f"requests frame lacks {missing}")
        if req["llm_request"].isna().any():
            raise ValueError("llm_request has unknown rows; unknown is not False")
        t_u, t_a = req["u_timestamp"], req["a_timestamp"]
        steps = [
            # The EDA exact-cache funnel (exact_cache_funnel.csv), in its order.
            ("has_user_text", req["u_content_state"].eq("text")),
            (
                "answer_text_and_STOP",
                req["a_content_state"].eq("text") & req["a_finish_reason"].eq("STOP"),
            ),
            ("no_attachments", req["u_att_n"].fillna(0).eq(0)),
            ("no_tools", req["a_tool_n_calls"].fillna(0).eq(0)),
            ("no_actions", req["a_action_types"].fillna("").eq("")),
            ("timestamps_valid", t_u.notna() & t_a.notna() & (t_a >= t_u)),
            # Added here: a known key, LLM rows only, hidden state excluded.
            (
                "key_known",
                req["bot_id"].notna()
                & req["u_h_norm"].notna()
                & req["a_h_norm"].notna(),
            ),
            ("llm_request", req["llm_request"].astype(bool)),
            ("no_memory", req["bot_memory_enabled"].eq(False)),
            (
                "no_rag",
                req["a_rag_state"].isin(["null", "empty", "ok"])
                & req["a_rag_n_queries"].fillna(0).eq(0),
            ),
        ]
        if self.variant == "first_turn":
            steps.append(("first_turn", req["n_prior_msgs"].eq(FIRST_TURN_PRIOR_MSGS)))
        return steps

    def eligible(self, req: pd.DataFrame) -> pd.Series:
        ok = pd.Series(True, index=req.index)
        for _, mask in self._steps(req):
            ok &= mask.fillna(False).astype(bool)
        return ok

    def funnel(self, req: pd.DataFrame) -> pd.DataFrame:
        """Requests still eligible after each step (counts only)."""
        ok = pd.Series(True, index=req.index)
        rows = [("all requests", len(req))]
        for name, mask in self._steps(req):
            ok &= mask.fillna(False).astype(bool)
            rows.append((name, int(ok.sum())))
        return pd.DataFrame(rows, columns=["step", "requests"])

    def keys(self, req: pd.DataFrame) -> pd.Series:
        """Guarded cache key per row; NaN where the bot or the question is unknown.

        Grouping hashes: in memory only, for the guard and the local review sheet.
        Never written to a committed file or to the frame ``apply`` returns.
        """
        known = req["bot_id"].notna() & req["u_h_norm"].notna()
        body = (
            req["bot_id"].astype(str)
            + "|"
            + req["bot_ins_h_exact"].fillna(NO_INSTRUCTIONS).astype(str)
            + "|"
            + req["u_h_norm"].astype(str)
        )
        key = pd.Series(np.nan, index=req.index, dtype=object)
        key[known] = body[known].map(lambda b: versioned_key(self.key_version, b))
        return key

    # --- replay --------------------------------------------------------------------

    def apply(self, req: pd.DataFrame, ctx: ReplayContext) -> pd.DataFrame:
        cols = [block_column(b) for b in BLOCKS]
        if any(c not in req for c in cols):
            raise ValueError(f"cost blocks {cols} are missing; run with_blocks first")
        out = req.copy()
        eligible, served, agrees, admitted_n, _ = self._replay(req, ctx)
        for col in cols:
            out.loc[served & out[col].notna(), col] = 0.0
        out["served_from_cache"] = served
        out["pq_eligible"] = eligible
        out["pq_admitted_keys_day"] = admitted_n
        out["pq_answer_agrees"] = agrees
        return out

    def served_sources(self, req: pd.DataFrame, ctx: ReplayContext) -> pd.Series:
        """Per hit row, the index label of the window row whose answer is served:
        the latest occurrence of the stored answer. In memory only (K-1 sheet)."""
        _, served, _, _, source = self._replay(req, ctx)
        return source[served].astype(req.index.dtype)

    def _replay(self, req: pd.DataFrame, ctx: ReplayContext):
        eligible = self.eligible(req)
        key = self.keys(req)
        day = req["u_timestamp"].dt.normalize()

        e = pd.DataFrame(
            {
                "key": key[eligible],
                "bot": req.loc[eligible, "bot_id"],
                "session": req.loc[eligible, "session_id"],
                "day": day[eligible],
                "t": req.loc[eligible, "a_timestamp"],
            }
        )
        e["kc"] = pd.factorize(e["key"])[0]
        e["sc"] = pd.factorize(e["session"])[0]
        # sort=True: code order is hash order, used as the last tie-break.
        e["ac"] = pd.factorize(req.loc[eligible, "a_h_norm"], sort=True)[0]

        served = pd.Series(False, index=req.index)
        agrees = pd.Series(None, index=req.index, dtype=object)
        source = pd.Series(None, index=req.index, dtype=object)
        admitted_n = pd.Series(np.nan, index=req.index, dtype=float)
        allowed: dict[tuple[str, str], bool] = {}
        window = pd.Timedelta(days=self.window_days)

        for d in sorted(day.dropna().unique()):
            d = pd.Timestamp(d)
            win = e[(e["day"] >= d - window) & (e["day"] < d)]
            stats = win.groupby("kc").agg(n=("kc", "size"), ns=("sc", "nunique"))
            admitted = stats.index[
                (stats["n"] >= self.min_count) & (stats["ns"] >= self.min_sessions)
            ]
            admitted_n[day == d] = float(len(admitted))
            today = e[(e["day"] == d) & e["kc"].isin(admitted)]
            if today.empty:
                continue
            stored = self._stored_answers(win[win["kc"].isin(today["kc"])])
            for idx, k, bot, kc, ac in zip(
                today.index,
                today["key"],
                today["bot"],
                today["kc"],
                today["ac"],
                strict=True,
            ):
                if ctx.guard is not None:
                    pair = (k, str(bot))
                    if pair not in allowed:
                        allowed[pair] = bool(ctx.guard.allows(*pair))
                    if not allowed[pair]:
                        continue
                served.at[idx] = True
                stored_ac, stored_row = stored[kc]
                agrees.at[idx] = bool(ac == stored_ac)
                source.at[idx] = stored_row
        self.scope_check = self._check_scope(req, served, source)
        return eligible, served, agrees, admitted_n, source

    @staticmethod
    def _check_scope(
        req: pd.DataFrame, served: pd.Series, source: pd.Series
    ) -> dict[str, int]:
        """Every hit must reuse an entry of its own bot and instruction fingerprint.

        Compares the hit row with the stored entry's row; any difference raises,
        so a key bug fails the run instead of counting cross-bot hits.
        """
        hit_rows = served.index[served]
        src_rows = source[hit_rows].to_numpy()
        ins = req["bot_ins_h_exact"].fillna(NO_INSTRUCTIONS).astype(str)
        bots = req["bot_id"].astype(str)
        cross_bot = int((bots[hit_rows].to_numpy() != bots[src_rows].to_numpy()).sum())
        cross_ins = int((ins[hit_rows].to_numpy() != ins[src_rows].to_numpy()).sum())
        if cross_bot or cross_ins:
            raise RuntimeError(
                f"scope check failed: {cross_bot} cross-bot and {cross_ins} "
                "cross-instruction hits; the cache key lost its bot or instructions"
            )
        return {
            "hits_checked": len(hit_rows),
            "cross_bot_hits": cross_bot,
            "cross_instruction_hits": cross_ins,
        }

    @staticmethod
    def _stored_answers(win: pd.DataFrame) -> dict[int, tuple[int, object]]:
        """Per key: (answer code, row label). The code is the mode, then the latest
        answered, then the smallest hash; the row is that answer's latest row."""
        latest = win.sort_values("t", kind="stable").drop_duplicates(
            ["kc", "ac"], keep="last"
        )
        pairs = zip(latest["kc"], latest["ac"], strict=True)
        row_of = dict(zip(pairs, latest.index, strict=True))
        per = (
            win.groupby(["kc", "ac"])
            .agg(n=("ac", "size"), last=("t", "max"))
            .reset_index()
            .sort_values(
                ["kc", "n", "last", "ac"], ascending=[True, False, False, True]
            )
        )
        first = per.drop_duplicates("kc")
        return {
            kc: (ac, row_of[(kc, ac)])
            for kc, ac in zip(first["kc"], first["ac"], strict=True)
        }
