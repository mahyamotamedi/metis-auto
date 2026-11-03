"""Fetching and pinning decision-router model files
(ADR-0047 point 7; R5), against a fake Hub laid out like
doofz/THX-01 (the model at the root, demo and training folders beside it): the plan
lists exactly the package's files and never walks the other folders; pin verifies every
file against the Hub's own tree (LFS sha256 or git blob ID), retries and resumes a
dropped download, and keeps verified files across a failed run; a Hub error names the
URL and the HTTP status. SYNTHETIC bytes only; no network."""

from __future__ import annotations

import hashlib
import io
import shutil
import subprocess
import urllib.error
from datetime import date
from pathlib import Path

import pytest

from metis_auto.adapters.routers import hub as hub_module
from metis_auto.adapters.routers.hub import HubClient, HubError, HubFile, _next_link
from metis_auto.settings import RouterAssetSpec, RouterAssetTable, load_settings
from metis_auto.settings.reference import read_router_assets
from metis_auto.wiring import router_assets as ra

REPO = "someone/SYNTHETIC-router"
REV = "a" * 40
NO_SLEEP = lambda _s: None  # noqa: E731


def blob_id(data: bytes) -> str:
    return hashlib.sha1(
        b"blob %d\0" % len(data) + data, usedforsecurity=False
    ).hexdigest()


class FakeHub:
    """Non-recursive folder listings, like the Hub's tree API; downloads
    resume an existing partial file, like an HTTP range request."""

    def __init__(self, files: dict[str, bytes], lfs: set[str]):
        self.files = files
        self.lfs = lfs
        self.tamper: set[str] = set()
        self.drop_after: dict[str, int] = {}
        """path → bytes delivered before the connection drops (once)."""
        self.downloads: list[str] = []
        self.listed: list[str | None] = []

    def revision_sha(self, repo, revision):
        assert repo == REPO
        return REV

    def tree(self, repo, revision, path, *, recursive=False):
        assert revision == REV and not recursive
        self.listed.append(path)
        out = []
        for p, data in self.files.items():
            parent = p.rsplit("/", 1)[0] if "/" in p else None
            if parent != path:
                continue
            in_lfs = p in self.lfs
            out.append(
                HubFile(
                    path=p,
                    size=len(data),
                    blob_id=blob_id(b"pointer" if in_lfs else data),
                    lfs_sha256=hashlib.sha256(data).hexdigest() if in_lfs else None,
                )
            )
        if not out and path is not None:
            raise HubError(
                f"https://hub/api/models/{repo}/tree/{revision}/{path}", 404, "HTTP 404"
            )
        return out

    def download(self, repo, revision, path, target, *, progress=None):
        self.downloads.append(path)
        data = self.files[path]
        if path in self.tamper:
            data = b"X" + data[1:]
        have = target.stat().st_size if target.exists() else 0
        target.parent.mkdir(parents=True, exist_ok=True)
        cut = self.drop_after.pop(path, None)
        with target.open("ab") as out:
            if cut is not None:
                out.write(data[have:cut])
                raise HubError(
                    f"https://hub/{repo}/resolve/{revision}/{path}",
                    None,
                    "connection dropped (ConnectionResetError)",
                )
            out.write(data[have:])


FILES = {
    "rl_agent_config.json": b'{"encoder": "synthetic", "head_layers": 2}',
    "config.json": b"{}",
    "model.safetensors": b"SYNTHETIC-WEIGHTS" * 100,
    "README.md": b"not included",
    "tokenizer/tokenizer.json": b'{"SYNTHETIC": true}',
    "tokenizer/tokenizer_config.json": b'{"tokenizer_class": null}',
    "encoder/config.json": b'{"hidden_size": 8}',
    # demo and training folders beside the model: never listed or fetched
    "doom/weights.safetensors": b"demo",
    "snake/model.safetensors": b"demo",
    "train/run.py": b"demo",
    "results/thx01/suite39.json": b"{}",
}
OTHER_FOLDERS = {"doom", "snake", "train", "results", "results/thx01"}


def spec() -> RouterAssetSpec:
    table = load_settings(environ={}, dotenv=None, runtime=None).reference.routers
    # The committed table is pinned (owner, 2026-11-03); the tests start unpinned.
    return table.get("thx01").model_copy(
        update={"model": REPO, "revision": None, "files": ()}
    )


def hub() -> FakeHub:
    return FakeHub(dict(FILES), {"model.safetensors"})


def test_the_committed_table_names_the_root_model_and_its_exact_files():
    table = load_settings(environ={}, dotenv=None, runtime=None).reference.routers
    thx = table.get("thx01")
    assert thx.model == "doofz/THX-01" and thx.subfolder is None
    # Pinned by the owner on Windows, 2026-11-03 (routers-2026-11-03).
    assert thx.pinned and thx.revision == "b323afcef149f9288a9d0daef4badd67b9b87c61"
    assert {f.path for f in thx.files} == set(thx.include)
    sizes = {f.path: f.size_bytes for f in thx.files}
    assert sizes["model.safetensors"] == 643_835_524
    assert set(thx.include) == {
        "config.json",
        "rl_agent_config.json",
        "model.safetensors",
        "encoder/config.json",
        "tokenizer/tokenizer.json",
        "tokenizer/tokenizer_config.json",
    }
    assert set(thx.required) == set(thx.include) - {"config.json"}
    assert table.get("mizan-1.5-4b-q4-k-m").optional


def test_plan_lists_exactly_the_package_files_and_never_walks_other_folders():
    h = hub()
    p = ra.plan(spec(), h)
    assert p.revision == REV and h.downloads == []
    assert [f.path for f in p.files] == [
        "config.json",
        "encoder/config.json",
        "model.safetensors",
        "rl_agent_config.json",
        "tokenizer/tokenizer.json",
        "tokenizer/tokenizer_config.json",
    ]
    assert set(h.listed) == {None, "encoder", "tokenizer"}
    assert not set(h.listed) & OTHER_FOLDERS
    summary = p.summary()
    assert summary["lfs_files"] == 1 and len(summary["file_list"]) == 6
    assert p.total_bytes == sum(len(FILES[f.path]) for f in p.files)


def test_a_partial_checkpoint_is_refused_with_the_url_and_status():
    h = hub()
    del h.files["encoder/config.json"]
    with pytest.raises(HubError) as raised:
        ra.plan(spec(), h)
    assert raised.value.status == 404 and raised.value.url.endswith("/encoder")
    h = hub()
    del h.files["tokenizer/tokenizer_config.json"]
    with pytest.raises(ra.AssetError, match="tokenizer_config.json"):
        ra.plan(spec(), h)


def test_pin_verifies_every_file_against_the_hub_tree(tmp_path):
    h = hub()
    pinned, report = ra.pin(spec(), h, tmp_path, ra.plan(spec(), h), sleep=NO_SLEEP)
    assert report.problems == [] and report.downloaded == 6
    assert pinned.revision == REV and len(pinned.files) == 6
    kinds = {f.path: f.verified_by for f in pinned.files}
    assert kinds["model.safetensors"] == "lfs_sha256"
    assert kinds["tokenizer/tokenizer.json"] == "git_blob_sha1"
    directory = tmp_path / "thx01" / REV
    for f in pinned.files:
        assert hashlib.sha256((directory / f.path).read_bytes()).hexdigest() == f.sha256
    assert ra.check(pinned, tmp_path).problems == []
    assert ra.disk_bytes(directory) == pinned.total_bytes
    again, report = ra.pin(spec(), h, tmp_path, ra.plan(spec(), h), sleep=NO_SLEEP)
    assert report.downloaded == 0 and report.ok == 6 and again == pinned


def test_a_dropped_download_is_retried_and_resumed(tmp_path):
    h = hub()
    h.drop_after["model.safetensors"] = 700  # of 1,700 bytes
    lines: list[str] = []
    pinned, report = ra.pin(
        spec(), h, tmp_path, ra.plan(spec(), h), log=lines.append, sleep=NO_SLEEP
    )
    assert report.problems == [] and pinned.pinned
    assert h.downloads.count("model.safetensors") == 2
    assert any("resuming at 700 of 1,700 bytes" in line for line in lines)
    assert any("connection dropped" in line for line in lines)


def test_after_a_failed_run_verified_files_are_kept_and_pin_continues(tmp_path):
    h = hub()
    h.drop_after["model.safetensors"] = 500

    def always_drop(repo, revision, path, target, *, progress=None):
        raise HubError(f"https://hub/{path}", None, "connection dropped (TimeoutError)")

    flaky = FakeHub(dict(FILES), {"model.safetensors"})
    flaky.download = always_drop  # type: ignore[method-assign]
    first, report = ra.pin(
        spec(), flaky, tmp_path, ra.plan(spec(), flaky), sleep=NO_SLEEP
    )
    assert not first.pinned and len(report.problems) == 6
    assert all("after 5 attempts" in p for p in report.problems)
    # Some files arrive, then the run stops: they stay verified on disk.
    calls = {"n": 0}

    def drop_on_weights(repo, revision, path, target, *, progress=None):
        if path == "model.safetensors":
            raise HubError(
                f"https://hub/{path}", None, "connection dropped (TimeoutError)"
            )
        calls["n"] += 1
        FakeHub.download(h, repo, revision, path, target)

    partial = FakeHub(dict(FILES), {"model.safetensors"})
    partial.download = drop_on_weights  # type: ignore[method-assign]
    _, report = ra.pin(
        spec(), partial, tmp_path, ra.plan(spec(), partial), sleep=NO_SLEEP
    )
    assert len(report.problems) == 1 and calls["n"] == 5
    # The next run downloads only the missing weights.
    h2 = hub()
    pinned, report = ra.pin(spec(), h2, tmp_path, ra.plan(spec(), h2), sleep=NO_SLEEP)
    assert pinned.pinned and report.ok == 5 and h2.downloads == ["model.safetensors"]


@pytest.mark.parametrize("bad", ["model.safetensors", "tokenizer/tokenizer.json"])
def test_a_download_that_differs_from_the_tree_is_never_kept(tmp_path, bad):
    h = hub()
    h.tamper.add(bad)
    pinned, report = ra.pin(spec(), h, tmp_path, ra.plan(spec(), h), sleep=NO_SLEEP)
    assert len(report.problems) == 1 and not pinned.pinned
    assert [p.name for p in tmp_path.rglob("*.part")] == []
    assert not (tmp_path / "thx01" / REV / bad).exists()
    assert h.downloads.count(bad) == 5


def test_fetch_and_check_use_the_pins(tmp_path):
    h = hub()
    pinned, _ = ra.pin(spec(), h, tmp_path, ra.plan(spec(), h), sleep=NO_SLEEP)
    target = tmp_path / "thx01" / REV / "model.safetensors"
    target.write_bytes(b"corrupted")
    assert ra.check(pinned, tmp_path).problems == [
        "model.safetensors: sha256 differs from the pin"
    ]
    report = ra.fetch(pinned, h, tmp_path, sleep=NO_SLEEP)
    assert report.downloaded == 1 and report.problems == []
    assert ra.check(pinned, tmp_path).problems == []
    assert ra.fetch(spec(), h, tmp_path).problems == ["thx01: not pinned (run pin)"]


def test_the_rewritten_table_keeps_its_header_and_loads_with_the_pins(tmp_path):
    h = hub()
    pinned, _ = ra.pin(spec(), h, tmp_path, ra.plan(spec(), h), sleep=NO_SLEEP)
    source = (
        Path(__file__).resolve().parents[3] / "config" / "reference" / "routers.toml"
    )
    text = source.read_text(encoding="utf-8")
    table = read_router_assets(source)
    updated = ra.with_pins(table, pinned, date(2026, 11, 3))
    assert updated.version == "routers-2026-11-03"  # Mizan is optional
    out = tmp_path / "routers.toml"
    out.write_text(ra.render_table(updated, ra.header_of(text)), encoding="utf-8")
    loaded = read_router_assets(out)
    assert isinstance(loaded, RouterAssetTable)
    assert loaded.get("thx01") == pinned
    assert loaded.get("mizan-1.5-4b-q4-k-m") == table.get("mizan-1.5-4b-q4-k-m")
    header = ra.header_of(text)
    assert 'no "multilingual"' in header or "There is no" in header
    assert out.read_text(encoding="utf-8").startswith(header)


def test_the_hub_client_reports_the_url_and_status(monkeypatch):
    def not_found(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 404, "Not Found", {}, io.BytesIO(b"body never shown")
        )

    monkeypatch.setattr(hub_module.urllib.request, "urlopen", not_found)
    with pytest.raises(HubError) as raised:
        HubClient().tree("doofz/THX-01", REV, "multilingual")
    assert raised.value.status == 404
    assert (
        raised.value.url
        == f"https://huggingface.co/api/models/doofz/THX-01/tree/{REV}/multilingual"
    )
    assert "body never shown" not in str(raised.value)

    def refused(request, timeout):
        raise urllib.error.URLError(ConnectionResetError("reset"))

    monkeypatch.setattr(hub_module.urllib.request, "urlopen", refused)
    with pytest.raises(HubError, match="ConnectionResetError") as raised:
        HubClient().revision_sha("doofz/THX-01", "main")
    assert raised.value.status is None


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_git_blob_ids_match_git(tmp_path):
    f = tmp_path / "x.json"
    f.write_bytes(b'{"SYNTHETIC": "\xd8\xb3\xd9\x84\xd8\xa7\xd9\x85"}\n')
    out = subprocess.run(["git", "hash-object", str(f)], capture_output=True, text=True)
    assert ra.git_blob_id(f) == out.stdout.strip()


def test_pins_are_validated():
    base = spec()
    with pytest.raises(ValueError, match="pinned together"):
        RouterAssetSpec.model_validate({**base.model_dump(), "revision": REV})
    file = {
        "path": "model.safetensors",
        "sha256": "0" * 64,
        "size_bytes": 1,
        "verified_by": "lfs_sha256",
    }
    with pytest.raises(ValueError, match="is not pinned"):
        RouterAssetSpec.model_validate(
            {**base.model_dump(), "revision": REV, "files": [file]}
        )
    for path in ("../escape", "/abs", "tokenizer/../x", ".hidden"):
        with pytest.raises(ValueError):
            RouterAssetSpec.model_validate(
                {
                    **base.model_dump(),
                    "revision": REV,
                    "files": [{**file, "path": path}],
                }
            )


def test_hub_pagination_link():
    assert (
        _next_link('<https://h/api?cursor=2>; rel="next"') == "https://h/api?cursor=2"
    )
    assert _next_link(None) is None
