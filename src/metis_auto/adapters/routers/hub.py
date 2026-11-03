"""Hugging Face Hub, read-only, for fetching pinned decision-router models
(ADR-0047 point 7; decision router R5). Standard library
only (``urllib``), so no extra is needed to fetch.

- ``revision_sha``: a branch or tag → its commit (40 hex).
- ``tree``: the files in a folder at a commit (not recursive by default, so a
  repository's demo and training folders are never walked), with each file's
  git blob ID, size and, for LFS files, the sha256 the Hub lists.
- ``download``: one file at a commit, streamed to disk; a partial file is
  resumed with an HTTP range request.

Every failure is a ``HubError`` naming the URL and the HTTP status (or the
transport error's type), never a response body.

Public repositories only; no token is read or sent. Used only by
``wiring.router_assets`` (the fetch script); never on the request path,
never in tests (they inject a fake). Status: provisional.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

HUB = "https://huggingface.co"
CHUNK = 1 << 20
TIMEOUT_S = 60


@dataclass(frozen=True)
class HubFile:
    path: str
    """Repository path, e.g. ``tokenizer/tokenizer.json``."""
    size: int
    blob_id: str
    """Git blob ID (sha1 of ``blob <size>\\0`` + content) of the stored object.
    For an LFS file this is the pointer's ID, not the content's."""
    lfs_sha256: str | None
    """The content's sha256 when the file is in LFS; None otherwise."""


def _quote(path: str) -> str:
    return urllib.parse.quote(path, safe="/")


class HubError(OSError):
    """A Hub request failed: the URL (a public Hub URL, never content) and the
    HTTP status, or the transport error's type, so a 404 is diagnosable."""

    def __init__(self, url: str, status: int | None, detail: str) -> None:
        self.url = url
        self.status = status
        super().__init__(f"{detail} for {url}")


class HubClient:
    def __init__(self, base: str = HUB, *, timeout_s: float = TIMEOUT_S) -> None:
        self._base = base.rstrip("/")
        self._timeout = timeout_s

    def _open(self, request: urllib.request.Request):
        try:
            return urllib.request.urlopen(request, timeout=self._timeout)  # noqa: S310
        except urllib.error.HTTPError as exc:
            exc.close()  # the error holds the response socket; never read the body
            raise HubError(request.full_url, exc.code, f"HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            reason = getattr(exc, "reason", exc)
            raise HubError(
                request.full_url, None, f"connection failed ({type(reason).__name__})"
            ) from None

    def _json(self, url: str):
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        with self._open(request) as response:
            return json.loads(response.read().decode("utf-8")), response.headers

    def revision_sha(self, repo: str, revision: str) -> str:
        info, _ = self._json(
            f"{self._base}/api/models/{_quote(repo)}/revision/{_quote(revision)}"
        )
        sha = info.get("sha")
        if not isinstance(sha, str) or len(sha) != 40:
            raise ValueError(f"the Hub returned no commit for {repo}@{revision}")
        return sha

    def tree(
        self, repo: str, revision: str, path: str | None, *, recursive: bool = False
    ) -> list[HubFile]:
        """The files directly in ``path`` (the repository root when None), or
        under it with ``recursive``, following pagination."""
        where = f"/{_quote(path)}" if path else ""
        url: str | None = (
            f"{self._base}/api/models/{_quote(repo)}/tree/{revision}{where}"
        )
        if recursive:
            url += "?recursive=true"
        files: list[HubFile] = []
        while url:
            entries, headers = self._json(url)
            url = _next_link(headers.get("Link"))
            for entry in entries:
                if entry.get("type") != "file":
                    continue
                lfs = entry.get("lfs") or {}
                files.append(
                    HubFile(
                        path=entry["path"],
                        size=int(lfs.get("size", entry.get("size", 0))),
                        blob_id=entry["oid"],
                        lfs_sha256=lfs.get("oid"),
                    )
                )
        return files

    def download(
        self,
        repo: str,
        revision: str,
        path: str,
        target: Path,
        *,
        progress: Callable[[int], None] | None = None,
    ) -> None:
        """Stream one file to ``target``, **resuming** a partial ``target`` with
        an HTTP range request (a server that ignores the range restarts it)."""
        url = f"{self._base}/{_quote(repo)}/resolve/{revision}/{_quote(path)}"
        target.parent.mkdir(parents=True, exist_ok=True)
        have = target.stat().st_size if target.exists() else 0
        headers = {"Range": f"bytes={have}-"} if have else {}
        try:
            response = self._open(urllib.request.Request(url, headers=headers))
        except HubError as exc:
            if exc.status == 416 and have:  # already complete
                return
            raise
        with response:
            resumed = have and response.status == 206
            mode = "ab" if resumed else "wb"
            done = have if resumed else 0
            expected = response.headers.get("Content-Length")
            received = 0
            with target.open(mode) as out:
                try:
                    while block := response.read(CHUNK):
                        out.write(block)
                        done += len(block)
                        received += len(block)
                        if progress is not None:
                            progress(done)
                except (TimeoutError, ConnectionError, OSError) as exc:
                    raise HubError(
                        url, None, f"connection dropped ({type(exc).__name__})"
                    ) from None
            # A server that closes early can end the body without an error:
            # a short body is a dropped connection (the partial file resumes).
            if expected is not None and expected.isdigit() and received < int(expected):
                raise HubError(
                    url,
                    None,
                    f"connection dropped (got {received} of {expected} bytes)",
                )


def _next_link(header: str | None) -> str | None:
    """The ``rel="next"`` URL of a ``Link`` header, if any."""
    if not header:
        return None
    for part in header.split(","):
        section = part.split(";")
        if len(section) > 1 and 'rel="next"' in section[1]:
            return section[0].strip().strip("<>")
    return None
