"""The one number formatter of the demo UI (UI Stage 2b, owner review
2026-11-03 point 4; ADR-0052 Amendment 1). Cards, tables, tooltips, legends
and the chat cost panel all format through ``fmt``; the value itself is never
changed, only its text.

- ``money`` (USD, recorded cost units, price-file units): 2 decimals at
  ``|v| >= 1`` with thousands separators (``8,212.00``); below 1, 4
  significant digits with trailing zeros dropped, as Metis shows them
  (``$0.001921``, ``$0.00032``); zero is ``0.00``. ``currency="USD"`` puts ``$``
  in front, another currency goes after, ``""`` (the default) shows the bare
  number and the page shows the unit as a muted caption. ``signed`` adds ``+``.
- ``count``: whole number with thousands separators (``8,667``).
- ``percent``: a fraction shown with 1 decimal (``0.0251`` → ``2.5%``).
- ``interval``: a pair of fractions, ``[2.3%, 2.8%]``.
Rounding is half up (``2.25%`` → ``2.3%``). ``None`` returns ``unknown``.

``AXIS_FORMAT`` holds the d3 formats for chart axes, which Vega formats in the
browser (4 significant digits, trailing zeros dropped).

Traceability: FR-FIN-02 (demo dashboard UI), FR-REQ-04 (unknown is shown as
unknown, never 0).
Called by: wiring.lever_view, wiring.ui_style, scripts/demo_ui.py,
scripts/demo_pages/results.py, tests.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

KINDS = ("money", "count", "percent", "interval")
AXIS_FORMAT = {"money": ",.4~g", "count": ",~d", "percent": ".1~%"}
_CENT = Decimal("0.01")
_TENTH = Decimal("0.1")


def _decimal(value: object) -> Decimal:
    # float through str: 0.0225 stays 0.0225, not its binary expansion
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _money(value: Decimal) -> str:
    size = abs(value)
    if size < 1 and size != 0:
        places = 3 - size.adjusted()  # 4 significant digits
        rounded = size.quantize(Decimal(1).scaleb(-places), ROUND_HALF_UP)
        if rounded < 1:
            text = f"{rounded:f}".rstrip("0")
            return text
        size = rounded
    return f"{size.quantize(_CENT, ROUND_HALF_UP):,.2f}"


def _percent(value: object) -> str:
    share = (_decimal(value) * 100).quantize(_TENTH, ROUND_HALF_UP)
    return f"{share:.1f}%"


def fmt(
    value: object,
    kind: str,
    *,
    currency: str = "",
    signed: bool = False,
    unknown: str = "—",
) -> str:
    """``value`` as display text of ``kind`` (see the module docstring)."""
    if kind not in KINDS:
        raise ValueError(f"unknown number kind {kind!r}; one of {KINDS}")
    if value is None:
        return unknown
    if kind == "count":
        return f"{int(value):,}"  # type: ignore[call-overload]
    if kind == "percent":
        return _percent(value)
    if kind == "interval":
        low, high = value  # type: ignore[misc]
        return f"[{_percent(low)}, {_percent(high)}]"
    number = _decimal(value)
    text = _money(number)
    if currency == "USD":
        text = f"${text}"
    elif currency:
        text = f"{text} {currency}"
    if number < 0:
        return f"-{text}"
    return f"+{text}" if signed and number > 0 else text
