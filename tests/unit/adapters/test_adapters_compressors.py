"""Context compressors (Demo milestone, ADR-0023). The LLMLingua-2 tests run
only when the optional extra ``compress`` is installed AND the pinned model
files were fetched (scripts/fetch_compressor_assets.py); otherwise they skip
with that reason. They never download. All text SYNTHETIC."""

import importlib.util
import os
from pathlib import Path

import pytest

from metis_auto.adapters.compressors import FakeCompressor
from metis_auto.adapters.compressors.llmlingua2 import (
    CompressorUnavailable,
    LLMLingua2Compressor,
)
from metis_auto.adapters.tokenizers import sha256_of
from metis_auto.settings import SettingsError, load_settings
from metis_auto.wiring.compression import build_compressor

REF = "llmlingua-2-xlm-roberta-large-meetingbank"
SYNTHETIC_EN = (
    "[SYNTHETIC] Customer: Hi, so, um, I ordered a pair of running shoes last "
    "week, you know, and I was told that the delivery would take about three "
    "days, but it has now been more than a week and I still have not received "
    "anything. Could you please check the status of my order and tell me when "
    "it will arrive? I really need them for a race next Sunday."
)
SYNTHETIC_FA = (
    "[SYNTHETIC] مشتری: سلام، راستش من هفته پیش یک جفت کفش ورزشی سفارش دادم و "
    "به من گفتند که ارسال حدود سه روز طول می‌کشد، ولی الان بیشتر از یک هفته "
    "گذشته و هنوز چیزی به دستم نرسیده است. لطفاً وضعیت سفارش من را بررسی کنید "
    "و بگویید کی می‌رسد، چون برای مسابقه یکشنبه آینده واقعاً لازمش دارم."
)


def test_fake_compressor_keeps_about_rate_of_the_words():
    out = FakeCompressor().compress("one two three four five six seven eight", 0.5)
    assert (out.tokens_before, out.tokens_after) == (8, 4)
    assert out.text == "two four six eight"
    assert FakeCompressor().compress("a b c", 1.0).text == "a b c"


def test_missing_files_are_refused_before_any_import(tmp_path):
    with pytest.raises(CompressorUnavailable, match="fetch_compressor_assets"):
        LLMLingua2Compressor(
            name=REF,
            revision="0" * 40,
            directory=tmp_path,
            files=[("model.safetensors", "0" * 64)],
            library_version="llmlingua==0.2.2",
        )


def test_wrong_hash_is_refused(tmp_path):
    (tmp_path / "config.json").write_text("{}")
    with pytest.raises(CompressorUnavailable, match="wrong sha256"):
        LLMLingua2Compressor(
            name=REF,
            revision="0" * 40,
            directory=tmp_path,
            files=[("config.json", "0" * 64)],
            library_version="llmlingua==0.2.2",
        )


def test_wiring_names_the_fix_when_files_are_missing(tmp_path):
    loaded = load_settings(
        overrides={"paths.compressor_assets": str(tmp_path)},
        runtime=None,
        dotenv=None,
        environ={},
    )
    with pytest.raises(SettingsError, match="compression unavailable"):
        build_compressor(loaded, REF)
    with pytest.raises(SettingsError, match="not in the compressor table"):
        build_compressor(loaded, "no-such-compressor")


def _real_files() -> Path | None:
    loaded = load_settings(runtime=None, dotenv=None, environ={})
    spec = loaded.reference.compressors.get(REF)
    directory = loaded.path(loaded.settings.paths.compressor_assets) / spec.directory
    for f in spec.files:
        path = directory / f.name
        if not path.is_file() or path.stat().st_size != (
            f.size_bytes or path.stat().st_size
        ):
            return None
    return directory


@pytest.fixture(scope="module")
def llmlingua2():
    if importlib.util.find_spec("llmlingua") is None:
        pytest.skip("extra `compress` not installed (requirements-compress.lock)")
    if _real_files() is None:
        pytest.skip(
            "LLMLingua-2 files not fetched (scripts/fetch_compressor_assets.py)"
        )
    loaded = load_settings(runtime=None, dotenv=None, environ={})
    before = {k: os.environ.get(k) for k in ("HF_HUB_OFFLINE", "TIKTOKEN_CACHE_DIR")}
    compressor = build_compressor(loaded, REF)
    after = {k: os.environ.get(k) for k in ("HF_HUB_OFFLINE", "TIKTOKEN_CACHE_DIR")}
    assert before == after  # the offline settings are restored after loading
    return compressor


@pytest.mark.parametrize("text", [SYNTHETIC_EN, SYNTHETIC_FA], ids=["en", "fa"])
def test_llmlingua2_shortens_english_and_persian(llmlingua2, text):
    out = llmlingua2.compress(text, 0.5)
    assert out.text.strip()
    assert out.tokens_after < out.tokens_before
    assert len(out.text) < len(text)
    assert llmlingua2.ref.version.startswith("ebaba9b0e874@llmlingua==0.2.2")


def test_pinned_cl100k_matches_tiktokens_own_pin():
    directory = _real_files()
    if directory is None:
        pytest.skip("LLMLingua-2 files not fetched")
    path = directory / "9b5ad71b2ce5302211f9c61530b329a4922fc6a4"
    assert sha256_of(path) == (
        "223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7"
    )
