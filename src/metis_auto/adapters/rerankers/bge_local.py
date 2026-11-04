"""The real ``bge-reranker-v2-m3`` scorer, local GPU only (cut-first item (a)).

Responsibility: turn sha256-checked local files into the injected scorer
``scorer(question, chunk_texts) -> scores`` of ``RerankerCut`` (higher = more
relevant; raw cross-encoder logits, not probabilities). The Hugging Face
libraries are set offline while loading, remote code is refused, the model runs
on a GPU (``cuda`` or ``mps``) and **never on CPU**, and no text leaves the
process. The only importer of ``torch`` and ``transformers`` for rerankers
(tested). Optional dependency: extra ``compress``; never in the runtime lock.
Traces: H-2, FR-CTX-02, ADR-0040. Status: provisional; never run in this repo.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from .assets import RerankerSpec, not_ready_reasons

_OFFLINE = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
BATCH = 16
MAX_LENGTH = 512


class RerankerUnavailable(RuntimeError):
    """The weights, the libraries or a GPU are missing; nothing was loaded."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = tuple(reasons)


def gpu_device() -> str | None:
    """``cuda`` or ``mps`` when a GPU is usable, else None (needs torch)."""
    try:
        import torch
    except ImportError:
        return None
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return None


def check_ready(
    spec: RerankerSpec,
    root: Path,
    *,
    device_probe: Callable[[], str | None] = gpu_device,
) -> list[str]:
    """Every reason the run must not start (empty = ready). Weights first, so a
    missing file is reported even on a machine without the libraries."""
    reasons = not_ready_reasons(spec, root)
    if device_probe() is None:
        reasons.append(
            "no local GPU found (cuda or mps) or the extra `compress` is not "
            "installed; the reranker runs on a local GPU only, never on CPU"
        )
    return reasons


def load_scorer(
    spec: RerankerSpec, root: Path
) -> Callable[[str, list[str]], list[float]]:
    """The scorer, named ``bge_reranker_v2_m3`` (its name is the lever label)."""
    reasons = check_ready(spec, root)
    if reasons:
        raise RerankerUnavailable(reasons)
    os.environ.update(_OFFLINE)
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    directory = root / spec.directory
    device = gpu_device()
    assert device is not None
    tokenizer = AutoTokenizer.from_pretrained(directory, trust_remote_code=False)
    model = AutoModelForSequenceClassification.from_pretrained(
        directory, trust_remote_code=False
    )
    model.to(device).eval()

    def bge_reranker_v2_m3(query: str, texts: list[str]) -> list[float]:
        scores: list[float] = []
        with torch.inference_mode():
            for start in range(0, len(texts), BATCH):
                batch = texts[start : start + BATCH]
                inputs = tokenizer(
                    [query] * len(batch),
                    batch,
                    padding=True,
                    truncation=True,
                    max_length=MAX_LENGTH,
                    return_tensors="pt",
                ).to(device)
                logits = model(**inputs).logits.view(-1)
                scores.extend(float(x) for x in logits.float().cpu())
        return scores

    return bge_reranker_v2_m3
