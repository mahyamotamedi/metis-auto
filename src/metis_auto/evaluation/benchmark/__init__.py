"""Paid routing benchmark P-1..P-3 (final sprint plan, "Paid branch").

- ``config``: the benchmark configuration; owner values unset refuse.
- ``arms``: which answering arms are callable, and why not.
- ``tenant``: the 35% tenant cap check.
- ``pilot``: deterministic pilot selection under the cap.
- ``plan``: calls, cost bounds, gates and unset owner values, with no call.
- ``judge``: a real pairwise judge over a ``ModelClient`` (strict JSON).
- ``spot_check``: the 60-item human spot-check, ID-only sheet.
- ``labels``: judged results to R-B3 / R-C3 routing labels.
- ``agreement``: spot-check agreement per judge and language, and the Persian gate.

Decision record: ADR-0053. Status: provisional.
"""
