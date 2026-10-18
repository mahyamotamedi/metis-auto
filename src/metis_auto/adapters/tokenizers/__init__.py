"""Tokenizer backends (CMP-12). Exact local backends arrive in Stage 7."""

from .approx import ApproxCharsTokenizer

__all__ = ["ApproxCharsTokenizer"]
