"""THX-01 in process: the default local decision backend
(ADR-XXXX (system-one-decision-router); R5).

Implements ``ports.BaseRouter`` over ``thx01.Agent.system_one`` (extra
``router-local``: thx01 1.0.0, torch, transformers). The only module that
imports ``thx01``, ``torch`` or ``transformers`` for the router (tested).

- **Offline, pinned files only.** The checkpoint is the multilingual one,
  fetched and pinned by ``scripts/fetch_router_assets.py``. ``load`` checks
  every file's sha256 against the pins, sets the Hugging Face libraries
  offline, and loads from a work directory where the small files (up to
  1 MiB) are copied and every large one is hard-linked to the pinned file, so
  that ``thx01``'s ``_fix_tokenizer_config``, which may rewrite
  ``tokenizer/tokenizer_config.json``, never touches a pinned file and the
  weights are never duplicated (a few KB of extra disk).
  ``thx01`` falls back to a Hub download when ``tokenizer/`` or ``encoder/``
  is missing; the pins require both, and the offline flags make any download
  an error.
- **CPU, measured.** ``threads`` sets torch's intra-op threads (process-wide).
  After loading, every floating-point weight must be float32 on CPU (the
  checkpoint is stored in F16; half precision on CPU is slow): ``load``
  records the dtypes it found and casts to float32 if any is not, and each
  call runs under ``torch.inference_mode()``. A call cannot be pre-empted:
  one that ran past ``timeout_ms`` is reported as a timeout with its real
  duration (the cascade keeps the grace). ``profile`` times one call's parts
  (sequence building, forward pass, decoding) with shapes only, never text.
- **Contained output.** ``thx01`` prints warnings to stdout; they are
  captured and counted, never printed (they could echo paths, never content).
  A clamped calibration bucket (``choice:11+`` and the like) marks the
  backend uncalibrated.
- Never raises for expected failures: a load or call failure is a
  ``DecisionError`` or ``available() == False`` with a reason.

Built by wiring.routers. Status: provisional (placeholder until exp-route-013).
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import os
import shutil
import time
import warnings
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from metis_auto.contracts import (
    AvailabilityReason,
    BackendAvailability,
    BackendKind,
    CostEstimate,
    DecisionError,
    DecisionLatencySource,
    DecisionQuestionSet,
    DecisionResult,
    DecisionState,
    ErrorClass,
    Fidelity,
    PolicyRef,
    TokenCount,
    TokenUsage,
)
from metis_auto.ports import Clock

from .fake import local_zero_cost
from .wire import StateFormat, WireError, parse_answers, render_questions, render_state

_OFFLINE = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
}
COPY_MAX_BYTES = 1 << 20
"""Files up to 1 MiB are copied into the work directory: ``thx01`` may rewrite
one of them (``tokenizer/tokenizer_config.json``). Larger files (the 644 MB
weights, the 34 MB ``tokenizer.json``) are hard-linked, never copied (A-107,
owner 2026-11-02: no duplicate weights)."""


class _LinkRefused(OSError):
    """A large file could be neither hard-linked nor symlinked."""


CHUNK = 1 << 20


@dataclass(frozen=True)
class PinnedFile:
    path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class LoadReport:
    ok: bool
    reason: AvailabilityReason | None
    load_ms: float
    sha_ms: float
    warnings: int
    calibrated: bool
    linked: int
    copied: int
    threads: int
    copied_bytes: int = 0
    """Extra disk used by the work directory (the copied small files)."""
    detail: str | None = None
    """Why loading was refused, when the reason alone is not enough."""
    import_ms: float | None = None
    """Importing thx01 and torch (first time in the process)."""
    agent_ms: float | None = None
    """Building the agent (model, weights, tokenizer)."""
    param_dtypes: tuple[str, ...] = ()
    """Floating-point weight dtypes found after loading, before any cast."""
    cast_to_float32: bool = False
    """True when some weights were not float32 and were cast."""


AgentFactory = Callable[[Path], Any]
"""Builds the agent from a checkpoint directory (tests inject a fake)."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(CHUNK):
            digest.update(block)
    return digest.hexdigest()


def _extra_installed() -> bool:
    return all(
        importlib.util.find_spec(m) is not None
        for m in ("thx01", "torch", "transformers")
    )


def _default_factory(threads: int) -> AgentFactory:
    def build(directory: Path) -> Any:
        os.environ.update(_OFFLINE)
        t0 = time.perf_counter()
        import thx01  # noqa: PLC0415 (heavy, optional: extra router-local)
        import torch  # noqa: PLC0415

        t1 = time.perf_counter()
        torch.set_num_threads(threads)
        agent = thx01.Agent(str(directory), device="cpu")
        agent._metis_timings = ((t1 - t0) * 1000.0, (time.perf_counter() - t1) * 1000.0)
        return agent

    return build


def _float32(agent: Any) -> tuple[tuple[str, ...], bool]:
    """(floating dtypes found, cast?) for a real agent; ((), False) for a fake.
    On CPU every floating weight must be float32 (F16 matmuls on CPU are
    slow); anything else is cast."""
    model = getattr(agent, "model", None)
    if model is None or not hasattr(model, "parameters"):
        return (), False
    found = sorted(
        {str(p.dtype).removeprefix("torch.") for p in model.parameters()}
        | {str(b.dtype).removeprefix("torch.") for b in model.buffers()}
    )
    floating = [d for d in found if "float" in d]
    if all(d == "float32" for d in floating):
        return tuple(floating), False
    model.float()
    model.eval()
    with contextlib.suppress(ImportError):
        import torch  # noqa: PLC0415

        agent.dtype = torch.float32
    return tuple(floating), True


def _inference_mode() -> Any:
    """``torch.inference_mode()`` when torch is installed (a fake agent in
    tests runs without it)."""
    try:
        import torch  # noqa: PLC0415
    except ImportError:
        return contextlib.nullcontext()
    return torch.inference_mode()


class Thx01LocalBackend:
    def __init__(
        self,
        clock: Clock,
        *,
        name: str,
        model_dir: Path,
        revision: str | None,
        files: Sequence[PinnedFile],
        threads: int = 4,
        runtime: Literal["torch", "onnx"] = "torch",
        state_format: StateFormat = "text",
        agent_factory: AgentFactory | None = None,
        extra_installed: Callable[[], bool] = _extra_installed,
    ) -> None:
        self._clock = clock
        self._name = name
        self._dir = model_dir
        self._revision = revision
        self._files = tuple(files)
        self._threads = threads
        self._runtime = runtime
        self._format: StateFormat = state_format
        self._factory = agent_factory or _default_factory(threads)
        self._extra_installed = extra_installed
        self._agent: Any = None
        self._inference: Callable[[], Any] = (
            _inference_mode if agent_factory is None else contextlib.nullcontext
        )
        self._failure: AvailabilityReason | None = None
        self._calibrated = True
        self.last_load: LoadReport | None = None
        self.calls = 0

    # --- BaseRouter ---------------------------------------------------------------
    @property
    def ref(self) -> PolicyRef:
        return PolicyRef(name=self._name, version=self._revision or "unpinned")

    @property
    def kind(self) -> Literal["local"]:
        return "local"

    def available(self) -> BackendAvailability:
        reason = self._unavailable()
        return (
            BackendAvailability.ok()
            if reason is None
            else BackendAvailability.unavailable(reason)
        )

    def estimate_cost(self, state_tokens: int) -> CostEstimate | None:
        return None  # local: nothing billable

    def decide(
        self,
        state: DecisionState,
        questions: DecisionQuestionSet,
        *,
        timeout_ms: float,
    ) -> DecisionResult | DecisionError:
        if self._agent is None:
            report = self.load()
            if not report.ok:
                return DecisionError(
                    backend=self.ref, error_class=ErrorClass.UNAVAILABLE, latency_ms=0.0
                )
        self.calls += 1
        rendered = render_state(state, self._format)
        asked = render_questions(questions)
        start = self._clock.monotonic_ms()
        try:
            with (
                contextlib.redirect_stdout(io.StringIO()),
                warnings.catch_warnings(),
                self._inference(),
            ):
                warnings.simplefilter("ignore")
                out = self._agent.system_one(rendered, asked)
        except Exception:  # noqa: BLE001 (an expected backend failure, typed below)
            elapsed = self._clock.monotonic_ms() - start
            return DecisionError(
                backend=self.ref, error_class=ErrorClass.UNKNOWN, latency_ms=elapsed
            )
        elapsed = self._clock.monotonic_ms() - start
        if elapsed > timeout_ms:
            return DecisionError(
                backend=self.ref, error_class=ErrorClass.TIMEOUT, latency_ms=elapsed
            )
        try:
            answers = parse_answers(out.get("answers"), questions)
        except (WireError, AttributeError):
            return DecisionError(
                backend=self.ref, invalid_response=True, latency_ms=elapsed
            )
        usage = None
        tokens = (out.get("usage") or {}).get("input_tokens")
        if isinstance(tokens, int) and tokens >= 0:
            usage = TokenUsage(
                model_id=self._name,
                input=TokenCount(
                    tokens=tokens, fidelity=Fidelity.EXACT_LOCAL, method="thx01@1.0.0"
                ),
            )
        return DecisionResult(
            answers=answers,
            backend=self.ref,
            backend_kind=BackendKind.LOCAL,
            model_revision=self._revision or "unpinned",
            question_set_version=questions.version,
            latency_ms=elapsed,
            latency_source=DecisionLatencySource.MEASURED_LOCAL,
            usage=usage,
            cost=local_zero_cost(),
            calibrated=self._calibrated,
        )

    # --- loading ------------------------------------------------------------------
    @property
    def loaded(self) -> bool:
        return self._agent is not None

    def _unavailable(self) -> AvailabilityReason | None:
        if self._failure is not None:
            return self._failure
        if self._runtime != "torch":
            return AvailabilityReason.NOT_CONFIGURED  # ONNX: built only if needed
        if not self._extra_installed():
            return AvailabilityReason.MISSING_EXTRA
        if self._revision is None or not self._files:
            return AvailabilityReason.MISSING_ASSETS
        for f in self._files:
            path = self._dir / f.path
            if not path.is_file() or path.stat().st_size != f.size_bytes:
                return AvailabilityReason.MISSING_ASSETS
        return None

    def _work_copy(self) -> tuple[Path, int, int, int]:
        """The checkpoint directory ``thx01`` loads: the small files (which it
        may rewrite) copied, every large file hard-linked to the pinned one
        (or symlinked if hard links are refused), so nothing pinned is ever
        written to and the weights are never duplicated. A large file that can
        be neither linked nor symlinked is refused, not copied."""
        work = self._dir.parent / f"{self._dir.name}.work"
        if work.exists():
            shutil.rmtree(work)
        linked = copied = copied_bytes = 0
        for f in self._files:
            source, target = self._dir / f.path, work / f.path
            target.parent.mkdir(parents=True, exist_ok=True)
            if f.size_bytes <= COPY_MAX_BYTES:
                shutil.copy2(source, target)
                copied += 1
                copied_bytes += f.size_bytes
                continue
            try:
                os.link(source, target)
            except OSError:
                try:
                    os.symlink(source.resolve(), target)
                except OSError as exc:
                    raise _LinkRefused(f.path) from exc
            linked += 1
        return work, linked, copied, copied_bytes

    def load(self) -> LoadReport:
        """Check the pins, then load. Idempotent; a failure is remembered as
        the backend's availability reason."""
        if self._agent is not None and self.last_load is not None:
            return self.last_load
        start = self._clock.monotonic_ms()
        reason = self._unavailable()
        sha_ms = 0.0
        caught = 0
        linked = copied = copied_bytes = 0
        detail = None
        timings: tuple[float | None, float | None] = (None, None)
        dtypes: tuple[str, ...] = ()
        cast = False
        if reason is None:
            sha_start = self._clock.monotonic_ms()
            for f in self._files:
                if _sha256(self._dir / f.path) != f.sha256:
                    reason = AvailabilityReason.SHA_MISMATCH
                    break
            sha_ms = self._clock.monotonic_ms() - sha_start
        if reason is None:
            try:
                work, linked, copied, copied_bytes = self._work_copy()
            except _LinkRefused as exc:
                reason = AvailabilityReason.MISSING_ASSETS
                detail = (
                    f"{exc}: could not be hard-linked or symlinked into the work "
                    "directory, and the weights are never copied; keep "
                    "paths.router_assets on one NTFS volume"
                )
        if reason is None:
            buffer = io.StringIO()
            try:
                with (
                    contextlib.redirect_stdout(buffer),
                    warnings.catch_warnings(record=True) as seen,
                ):
                    warnings.simplefilter("always")
                    self._agent = self._factory(work)
                    dtypes, cast = _float32(self._agent)
                timings = getattr(self._agent, "_metis_timings", (None, None))
                caught = len(seen) + sum(
                    1 for line in buffer.getvalue().splitlines() if line.strip()
                )
                raw = dict(getattr(self._agent, "temperature_by_options_raw", {}) or {})
                clamped = getattr(self._agent, "temperature_by_options", raw) or raw
                self._calibrated = all(
                    float(raw[k]) == float(clamped.get(k, raw[k])) for k in raw
                )
            except Exception:  # noqa: BLE001 (reported as unavailable, not raised)
                self._agent = None
                reason = AvailabilityReason.MISSING_ASSETS
        if reason is not None:
            self._failure = reason
        self.last_load = LoadReport(
            ok=reason is None,
            reason=reason,
            load_ms=self._clock.monotonic_ms() - start,
            sha_ms=sha_ms,
            warnings=caught,
            calibrated=self._calibrated,
            linked=linked,
            copied=copied,
            threads=self._threads,
            copied_bytes=copied_bytes,
            detail=detail,
            import_ms=timings[0],
            agent_ms=timings[1],
            param_dtypes=dtypes,
            cast_to_float32=cast,
        )
        return self.last_load

    # --- diagnostics --------------------------------------------------------------
    def profile(
        self, state: DecisionState, questions: DecisionQuestionSet
    ) -> dict[str, Any]:
        """One call taken apart (the R5 latency check, owner 2026-11-03):
        sequence building (tokenisation), the forward pass and decoding, in ms,
        with the batch shape, each question's real token length, the tournament
        rule and torch's thread and backend settings. Shapes and timings only:
        never text. Uses thx01 1.0.0's own helpers, as ``system_one`` does."""
        if self._agent is None and not self.load().ok:
            return {"error": "not loaded"}
        agent = self._agent
        try:
            import torch  # noqa: PLC0415
            from thx01.common import (  # noqa: PLC0415
                build_sequence,
                collate_items,
            )

            rendered = render_state(state, self._format)
            asked = render_questions(questions)
            limit = agent.cfg.get("tournament_above", 24)
            max_len = agent.cfg.get("max_len", 512)
            t0 = time.perf_counter()
            items = []
            lengths = {}
            for qid, q in asked.items():
                internal = agent._to_internal(q)
                seq, markers = build_sequence(
                    agent.tok, rendered, internal, max_len, agent._head_budget(internal)
                )
                items.append(
                    {"ids": seq, "markers": markers, "qtype": _qtype(internal)}
                )
                lengths[qid] = len(seq)
            batch = collate_items([items], agent.tok.pad_token_id)
            t1 = time.perf_counter()
            with torch.inference_mode():
                logits, act = agent.model(
                    batch["input_ids"],
                    batch["attention_mask"],
                    batch["marker_pos"],
                    batch["marker_mask"],
                    batch["qtype"],
                )
            t2 = time.perf_counter()
            agent._decode(
                asked,
                items,
                logits.float().cpu().numpy(),
                torch.softmax(act.float(), -1).cpu().numpy(),
            )
            t3 = time.perf_counter()
            return {
                "build_sequences_ms": round((t1 - t0) * 1000, 1),
                "forward_ms": round((t2 - t1) * 1000, 1),
                "decode_ms": round((t3 - t2) * 1000, 1),
                "batch_shape": list(batch["input_ids"].shape),
                "real_tokens": int(batch["attention_mask"].sum()),
                "tokens_per_question": lengths,
                "cfg_max_len": max_len,
                "tournament_above": limit,
                "tournament_used": any(
                    q.get("type") == "choice" and len(q.get("criteria") or {}) > limit
                    for q in asked.values()
                ),
                "param_dtypes": sorted(
                    {
                        str(p.dtype).removeprefix("torch.")
                        for p in agent.model.parameters()
                    }
                ),
                "model_training_mode": bool(agent.model.training),
                "torch_threads": torch.get_num_threads(),
                "torch_interop_threads": torch.get_num_interop_threads(),
                "mkldnn": bool(torch.backends.mkldnn.is_available()),
                "mkl": bool(torch.backends.mkl.is_available()),
                "torch": torch.__version__,
            }
        except Exception as exc:  # noqa: BLE001 (diagnostics never raise)
            return {"error": type(exc).__name__}


def _qtype(internal: dict[str, Any]) -> int:
    from thx01.common import QTYPES  # noqa: PLC0415

    return QTYPES[internal["t"]]
