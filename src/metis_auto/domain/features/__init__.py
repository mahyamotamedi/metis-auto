"""Feature extraction (CMP-04): pure functions from a request and its
measurements to ``RequestFeatures``, and the cheap text detectors they use.
Traces: FR-FEAT-01…05."""

from .detectors import (
    CodeConfig,
    CodingIntentConfig,
    GreetingConfig,
    LanguageConfig,
    detect_code,
    detect_coding_intent,
    detect_language,
    is_greeting,
    length_bucket,
    normalise_phrase,
)
from .extractor import (
    FEATURE_SET_VERSION,
    FeatureConfig,
    extract_features,
    history_turn_features,
)

__all__ = [
    "FEATURE_SET_VERSION",
    "CodeConfig",
    "CodingIntentConfig",
    "FeatureConfig",
    "GreetingConfig",
    "LanguageConfig",
    "detect_code",
    "detect_coding_intent",
    "detect_language",
    "extract_features",
    "history_turn_features",
    "is_greeting",
    "length_bucket",
    "normalise_phrase",
]
