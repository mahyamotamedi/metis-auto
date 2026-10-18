"""Tokenizer adapters (Stage 7): exact local backends, the asset checks, the
labelled fallback, and how far the chars/4 heuristic is from real counts.

Texts are SYNTHETIC (FR-DATA-03). Tests marked by the ``exact`` fixture need
the tokenizer files from ``scripts/fetch_tokenizer_assets.py`` (fetched once,
like installing a package) and the ``tokenizers`` extra; without them they
skip with that reason. They never use the network.
"""

import os

import pytest

from metis_auto.adapters.tokenizers import (
    ApproxCharsTokenizer,
    HuggingFaceTokenizer,
    TiktokenTokenizer,
    TokenizerUnavailable,
    sha256_of,
    verified_asset,
)
from metis_auto.contracts import Fidelity
from metis_auto.settings import load_settings
from metis_auto.wiring.tokenizers import build_tokenizers

TEXTS = {
    "persian": (
        "[SYNTHETIC] سلام، لطفاً ساعت کاری فروشگاه را در روزهای تعطیل به من "
        "بگویید. آیا ارسال رایگان برای سفارش‌های بالای پانصد هزار تومان وجود دارد؟"
    ),
    "english": (
        "[SYNTHETIC] Hello, could you tell me the store's opening hours on public "
        "holidays? Is shipping free for orders above fifty dollars?"
    ),
    "mixed": (
        "[SYNTHETIC] سلام، my order number is 48213 و هنوز tracking code برای "
        "shipment ارسال نشده. لطفاً check کنید."
    ),
    "code": (
        "[SYNTHETIC]\ndef total(items: list[dict]) -> float:\n"
        "    return sum(i['price'] * i.get('qty', 1) for i in items if i)\n"
    ),
}
# Counts with tiktoken 0.14.0 / o200k_base and tokenizers 0.23.2 / the
# DeepSeek-V4-Flash tokenizer.json at the pinned revision (2026-10-18).
EXPECTED = {
    #           o200k  deepseek  chars/4
    "persian": (42, 54, 35),
    "english": (30, 31, 33),
    "mixed": (29, 34, 27),
    "code": (40, 42, 29),
}
OPENAI, DEEPSEEK, APPROX = "openai-o200k-base", "deepseek-v4", "approx-chars-div-4"


@pytest.fixture(scope="module")
def exact():
    loaded = load_settings(environ={}, dotenv=None, runtime=None)
    built = build_tokenizers(loaded)
    missing = [s for s in built.status if s.reason and s.ref in (OPENAI, DEEPSEEK)]
    if missing:
        pytest.skip(
            "exact tokenizers unavailable (run scripts/fetch_tokenizer_assets.py; "
            f"extra `tokenizers`): {missing[0].reason}"
        )
    return built.tokenizers


@pytest.mark.parametrize("kind", sorted(TEXTS))
def test_exact_counts_are_pinned_and_labelled(exact, kind):
    o200k, deepseek, approx = EXPECTED[kind]
    text = TEXTS[kind]
    openai_count = exact[OPENAI].count(text)
    deepseek_count = exact[DEEPSEEK].count(text)
    approx_count = exact[APPROX].count(text)
    assert (openai_count.tokens, deepseek_count.tokens, approx_count.tokens) == (
        o200k,
        deepseek,
        approx,
    )
    assert openai_count.fidelity == deepseek_count.fidelity == Fidelity.EXACT_LOCAL
    assert approx_count.fidelity == Fidelity.APPROXIMATION
    assert openai_count.method == "tiktoken-o200k_base@0.14.0"
    assert deepseek_count.method.startswith("hf-deepseek-v4-8f9f37ca37fd@")


def test_counts_differ_by_tokenizer(exact):
    for kind, text in TEXTS.items():
        assert exact[OPENAI].count(text).tokens != exact[DEEPSEEK].count(text).tokens, (
            kind
        )


def test_chars_over_four_is_only_an_approximation(exact):
    """chars/4 undercounts Persian and code and overcounts English, against
    both exact tokenizers: its error depends on the language, so it cannot be
    corrected by one factor (H-7)."""

    def error(kind: str, ref: str) -> float:
        real = exact[ref].count(TEXTS[kind]).tokens
        return (exact[APPROX].count(TEXTS[kind]).tokens - real) / real

    for ref in (OPENAI, DEEPSEEK):
        assert error("persian", ref) < -0.15
        assert error("code", ref) < -0.25
        assert error("english", ref) > 0.05
    # Persian costs DeepSeek's tokenizer far more than OpenAI's.
    persian = TEXTS["persian"]
    assert (
        exact[DEEPSEEK].count(persian).tokens
        > 1.2 * exact[OPENAI].count(persian).tokens
    )


def test_special_token_text_in_content_is_counted_as_text(exact):
    text = "[SYNTHETIC] <|endoftext|> <｜User｜>"
    assert exact[OPENAI].count(text).tokens > 1
    assert exact[DEEPSEEK].count(text).tokens > 1


def test_tiktoken_load_restores_the_environment(exact, tmp_path):
    # Building it again must leave TIKTOKEN_CACHE_DIR as it was.
    os.environ.pop("TIKTOKEN_CACHE_DIR", None)
    loaded = load_settings(environ={}, dotenv=None, runtime=None)
    build_tokenizers(loaded)
    assert "TIKTOKEN_CACHE_DIR" not in os.environ


# --- Offline checks that need no fetched asset ------------------------------------


def test_missing_asset_is_reported_not_downloaded(tmp_path):
    with pytest.raises(TokenizerUnavailable, match="missing"):
        TiktokenTokenizer("x", "o200k_base", tmp_path / "absent", "0" * 64)
    with pytest.raises(TokenizerUnavailable, match="missing"):
        HuggingFaceTokenizer("x", tmp_path / "absent.json", "0" * 64)


def test_wrong_hash_is_refused(tmp_path):
    path = tmp_path / "asset"
    path.write_bytes(b"SYNTHETIC")
    with pytest.raises(TokenizerUnavailable, match="sha256"):
        verified_asset(path, "0" * 64)
    assert verified_asset(path, sha256_of(path)) == path


def test_hf_backend_reads_a_local_tokenizer_json(tmp_path):
    tokenizers = pytest.importorskip("tokenizers")
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace

    tok = tokenizers.Tokenizer(
        WordLevel({"[UNK]": 0, "synthetic": 1, "word": 2}, unk_token="[UNK]")
    )
    tok.pre_tokenizer = Whitespace()
    path = tmp_path / "tokenizer.json"
    tok.save(str(path))
    backend = HuggingFaceTokenizer(
        "synthetic-hf", path, sha256_of(path), Fidelity.APPROXIMATION
    )
    count = backend.count("synthetic word other")
    assert count.tokens == 3 and count.fidelity == Fidelity.APPROXIMATION


def test_fallback_is_labelled_approximation(tmp_path):
    loaded = load_settings(
        environ={},
        dotenv=None,
        runtime=None,
        overrides={"paths.tokenizer_assets": str(tmp_path)},
    )
    built = build_tokenizers(loaded)
    status = {s.ref: s for s in built.status}
    for ref in (OPENAI, DEEPSEEK):
        assert status[ref].reason is not None
        count = built.tokenizers[ref].count(TEXTS["persian"])
        assert count.fidelity == Fidelity.APPROXIMATION
        assert count.method == "approx-chars-div-4@1"
    # Templates stay attached: framing is counted even with the fallback.
    assert set(built.templates) == {OPENAI, DEEPSEEK, "mimo-v2"}


def test_approx_tokenizer_rounds_up():
    assert ApproxCharsTokenizer("a", 4).count("abcde").tokens == 2
