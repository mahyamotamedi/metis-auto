"""Chronological replay of an exact-match response cache over logged requests.

Counts **candidate hits**, not hits: no answer validity is checked (ADR-0006).
A request can hit only an entry that was *inserted earlier*, meaning the stored
answer's completion time is not after the new request's arrival. Where the
completion time is the logged AI-message timestamp, which is an assumption: the
export carries no call latency.

The functions are pure over a requests frame with columns:
``key`` (str, the cache key), ``t_arrive`` and ``t_done`` (datetime64), and
optionally ``eligible`` (bool). Rows must already be restricted to the requests
under study. The first occurrence of a key is a cold miss.
"""

from __future__ import annotations

import heapq
from collections import OrderedDict

import pandas as pd


def replay(
    req: pd.DataFrame,
    ttl: pd.Timedelta | None = None,
    capacity: int | None = None,
) -> pd.Series:
    """Return a boolean Series (aligned to ``req.index``): candidate hit or not.

    Insertion happens at ``t_done`` of a missed (or evicted/expired) request, so
    events are processed in time order: lookups at ``t_arrive`` and insertions
    at ``t_done``. ``ttl`` expires entries ``ttl`` after insertion; ``capacity``
    keeps at most that many keys with LRU eviction. Requests with
    ``eligible == False`` never look up and never insert.
    """
    elig = req["eligible"].to_numpy() if "eligible" in req else [True] * len(req)
    lookups = [
        (t_a, pos, idx, k, t_d)
        for pos, (idx, t_a, t_d, k) in enumerate(
            zip(req.index, req["t_arrive"], req["t_done"], req["key"], strict=False)
        )
        if elig[pos]
    ]
    lookups.sort(key=lambda e: (e[0], e[1]))
    pending: list[tuple[pd.Timestamp, int, object]] = []  # (t_done, seq, key)
    store: OrderedDict[object, pd.Timestamp] = OrderedDict()  # key -> inserted_at
    hits = pd.Series(False, index=req.index)
    seq = 0
    for t_a, _pos, idx, k, t_d in lookups:
        while (
            pending and pending[0][0] <= t_a
        ):  # answers completed by now become available
            td, _, key = heapq.heappop(pending)
            store[key] = td
            store.move_to_end(key)
            while capacity is not None and len(store) > capacity:
                store.popitem(last=False)
        inserted = store.get(k)
        if inserted is not None and (ttl is None or t_a - inserted <= ttl):
            hits.at[idx] = True
            store.move_to_end(k)
        else:
            if inserted is not None:
                del store[k]  # expired
            seq += 1
            heapq.heappush(pending, (t_d, seq, k))
    return hits


def group_upper_bounds(keys: pd.Series) -> dict[str, float]:
    """The three distinct duplicate metrics for a Series of cache keys.

    ``occurrences_in_dup_groups``: requests whose key occurs more than once.
    ``reusable_upper_bound``: sum over groups of (n - 1), a cold-cache upper
    bound before time, scope, expiry and validity limits.
    ``pairs``: sum of n*(n-1)/2, which is **not** a hit count.
    """
    vc = keys.value_counts()
    dup = vc[vc > 1]
    return {
        "n_requests": float(len(keys)),
        "n_groups": float(len(vc)),
        "n_dup_groups": float(len(dup)),
        "occurrences_in_dup_groups": float(dup.sum()),
        "reusable_upper_bound": float((dup - 1).sum()),
        "pairs": float((dup * (dup - 1) // 2).sum()),
    }
