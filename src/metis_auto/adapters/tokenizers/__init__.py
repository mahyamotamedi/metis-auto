"""Tokenizer backends (CMP-12): the labelled chars/N approximation, tiktoken
(OpenAI encodings), and Hugging Face ``tokenizer.json`` files. The exact
backends need the optional extra ``tokenizers`` and pre-fetched, sha256-pinned
assets; their libraries are imported only inside their constructors, so this
package imports without them (token_accounting.md §2, ADR-0020)."""

from .approx import ApproxCharsTokenizer
from .assets import TokenizerUnavailable, sha256_of, verified_asset
from .hf_backend import HuggingFaceTokenizer
from .tiktoken_backend import TiktokenTokenizer

__all__ = [
    "ApproxCharsTokenizer",
    "HuggingFaceTokenizer",
    "TiktokenTokenizer",
    "TokenizerUnavailable",
    "sha256_of",
    "verified_asset",
]
