"""Feature extraction (CMP-04): pure functions from a request and its
measurements to ``RequestFeatures``. Traces: FR-FEAT-01…05."""

from .extractor import FEATURE_SET_VERSION, FeatureConfig, extract_features

__all__ = ["FEATURE_SET_VERSION", "FeatureConfig", "extract_features"]
