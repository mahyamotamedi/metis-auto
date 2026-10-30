"""Full-prompt input token counts and input cost report (Stage E3)."""

from .composition import ORDER, REFERENCE, CaseInputs, ModelInput, case_inputs
from .report import (
    InputCostReport,
    InstructionReuse,
    ModelSliceStats,
    SliceReport,
    build_report,
    compression_break_even,
    input_prices,
    slice_report,
)

__all__ = [
    "ORDER",
    "REFERENCE",
    "CaseInputs",
    "InputCostReport",
    "InstructionReuse",
    "ModelInput",
    "ModelSliceStats",
    "SliceReport",
    "build_report",
    "case_inputs",
    "compression_break_even",
    "input_prices",
    "slice_report",
]
