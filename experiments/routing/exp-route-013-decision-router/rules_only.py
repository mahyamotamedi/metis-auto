"""exp-route-013, rules-only mode: tiers for the full-data replay (sprint final
Stage 2; ADR-0047 point 4 and the "Results of the owner's runs"; A-118, A-121;
FR-ROUTE-01, FR-ROUTE-03, FR-REQ-06, H-5).

With ``router.mode = "off"`` the decision router asks nothing. Its tier is the
real domain policy's ``decide_tier`` with no decision result: the gate first
(greeting, code, coding intent, attachment, long message), then the rule-based
fallback, then the safe tier. THX-01 changed no decision on the dev slice
(agreement 1.0 with the rules, A-121), so this is also what the shadow-run
router would have decided there. This module only produces tiers; the step
version (``version.py``, ``DecisionRouterRouting``) turns them into a model on
R-0's routing base.

The domain policy is called row by row (``decide_tier``), once per distinct
feature combination, so replay and inline mode cannot drift.

Text is read **in memory only**, by ``derive_flags``, to compute three flags
per user message with the configured detectors; the table keeps no text.
Everything else comes from the requests frame, and a missing value is unknown,
never zero: an unknown flag or length gives no tier (the version then keeps the
incumbent with reason ``no_decision``).

Pure over injected frames; imports only ``domain``, ``contracts`` and pandas.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

from metis_auto.contracts import ComponentState, Language, RequestFeatures
from metis_auto.domain.features.detectors import (
    detect_code,
    detect_coding_intent,
    is_greeting,
    length_bucket,
)
from metis_auto.domain.routing.decision_policy import DecisionRouterPolicy

NO_BACKEND_NOTE = "rules-only: no decision backend is configured, built or called"
FLAG_COLUMNS = ("has_code", "has_coding_intent", "is_greeting")
FEATURE_SET_VERSION = "replay-rules-only-v1"

_LANGUAGE = {
    "fa": Language.PERSIAN,
    "en": Language.ENGLISH,
    "fa_en_mixed": Language.MIXED,
    "short_uncertain": Language.UNDETERMINED,
}


def require_offline(settings: Any) -> None:
    """Refuse unless this run can call nothing and spend nothing (rule zero):
    the router is off, no dataset text is approved for hosted use, unpriced
    router calls are not allowed, and live calls are not enabled."""
    problems = []
    if settings.router.mode != "off":
        problems.append(f"router.mode is {settings.router.mode!r}, not 'off'")
    if settings.router.real_data_approved:
        problems.append("router.real_data_approved is set")
    if settings.router.allow_unpriced:
        problems.append("router.allow_unpriced is set")
    if settings.live.enabled:
        problems.append("live.enabled is set")
    if problems:
        raise SystemExit("rules-only run refused: " + "; ".join(problems))


def derive_flags(
    message_ids: Sequence[Any], texts: Sequence[object], features: Any
) -> pd.DataFrame:
    """``message_id`` and the three flags per user message, computed in memory
    with the configured detectors (``pipeline.features``). ``label_state`` is
    ``unknown`` for a missing or blank text; no text is kept."""
    rows = []
    for text in texts:
        if not isinstance(text, str) or not text.strip():
            rows.append((False, False, False, "unknown"))
            continue
        code = detect_code(text, features.code)
        rows.append(
            (
                code,
                detect_coding_intent(text, code, features.coding_intent),
                is_greeting(text, features.greeting),
                "ok",
            )
        )
    out = pd.DataFrame(rows, columns=[*FLAG_COLUMNS, "label_state"])
    out.insert(0, "message_id", list(message_ids))
    return out.astype({c: bool for c in FLAG_COLUMNS})


def _features(
    cfg: Any,
    *,
    lang: object,
    chars: int,
    attachments: int | None,
    turn: int | None,
    code: bool,
    intent: bool,
    greeting: bool,
) -> RequestFeatures:
    unknown = ComponentState.UNKNOWN
    return RequestFeatures(
        feature_set_version=FEATURE_SET_VERSION,
        language=_LANGUAGE.get(str(lang), Language.OTHER)
        if isinstance(lang, str)
        else Language.UNDETERMINED,
        message_chars=chars,
        has_code=code,
        has_coding_intent=intent,
        length_bucket=length_bucket(chars, cfg.features.length_bounds),
        is_greeting=greeting,
        attachment_count=attachments,
        turn_depth=turn,
        instructions_state=unknown,
        retrieved_state=unknown,
        structured_input_state=unknown,
        traffic_source_state=unknown,
    )


def _int_or_none(value: object) -> int | None:
    return None if value is None or pd.isna(value) else int(value)  # type: ignore[arg-type]


def rules_only_tiers(
    req: pd.DataFrame, flags: pd.DataFrame, cfg: Any, *, cache: bool = True
) -> pd.Series:
    """Tier (0 or 1) per row of ``req``, NaN where it is unknown.

    ``req`` needs ``user_message_id``, ``u_lang``, ``u_n_chars``, ``u_att_n`` and
    ``turn``; ``flags`` is ``derive_flags`` output. ``cfg`` is the validated
    ``PipelineConfig`` (``pipeline_config`` of a hermetic settings load). With
    ``cache`` the policy runs once per distinct feature tuple."""
    router = cfg.routing.decision_router
    if router is None or cfg.routing.rule_based is None:
        raise ValueError("the pipeline config has no decision_router / rule_based")
    policy = DecisionRouterPolicy(
        router, cfg.routing.rule_based, cfg.catalogue, cfg.prices
    )
    f = flags.drop_duplicates("message_id").set_index("message_id")
    mid = req["user_message_id"]
    known = mid.isin(f.index)
    joined = f.reindex(mid.where(known))
    ok = known.to_numpy() & joined["label_state"].eq("ok").to_numpy()
    chars_known = req["u_n_chars"].notna().to_numpy()
    usable = ok & chars_known
    tiers = np.full(len(req), np.nan)
    memo: dict[tuple, int] = {}
    lang = req["u_lang"].to_numpy(dtype=object)
    chars = req["u_n_chars"].to_numpy(dtype=float)
    att = req["u_att_n"].to_numpy(dtype=float)
    turn = req["turn"].to_numpy(dtype=float)
    code = joined["has_code"].fillna(False).to_numpy(dtype=bool)
    intent = joined["has_coding_intent"].fillna(False).to_numpy(dtype=bool)
    greet = joined["is_greeting"].fillna(False).to_numpy(dtype=bool)
    for i in np.flatnonzero(usable):
        key = (
            lang[i] if isinstance(lang[i], str) else None,
            int(chars[i]),
            _int_or_none(att[i]),
            _int_or_none(turn[i]),
            bool(code[i]),
            bool(intent[i]),
            bool(greet[i]),
        )
        tier = memo.get(key) if cache else None
        if tier is None:
            tier = policy.decide_tier(
                _features(
                    cfg,
                    lang=key[0],
                    chars=key[1],
                    attachments=key[2],
                    turn=key[3],
                    code=key[4],
                    intent=key[5],
                    greeting=key[6],
                )
            ).tier
            if cache:
                memo[key] = tier
        tiers[i] = tier
    return pd.Series(tiers, index=req.index, name="rules_only_tier")
