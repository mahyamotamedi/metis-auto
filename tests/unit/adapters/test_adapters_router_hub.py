"""The Hub client against a loopback fake of the Hugging Face API (R5): one
folder's listing, a 404 named by URL and status (never the body), a download
cut short by the server kept and resumed with a range request, and a complete
file answered with 416. SYNTHETIC bytes; no external network."""

from __future__ import annotations

import hashlib
import http.server
import json
import threading

import pytest

from metis_auto.adapters.routers.hub import HubClient, HubError

DATA = b"SYNTHETIC-WEIGHTS-" * 300
REV = "c" * 40


class _Handler(http.server.BaseHTTPRequestHandler):
    drops = 1

    def log_message(self, *args):  # quiet
        pass

    def _send(self, status: int, body: bytes = b"", headers: dict | None = None):
        self.send_response(status)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 (http.server API)
        if self.path == "/api/models/o/r/revision/main":
            return self._send(200, json.dumps({"sha": REV}).encode())
        if self.path == f"/api/models/o/r/tree/{REV}":
            entries = [
                {
                    "type": "file",
                    "path": "model.safetensors",
                    "oid": "pointer",
                    "size": 134,
                    "lfs": {"oid": hashlib.sha256(DATA).hexdigest(), "size": len(DATA)},
                },
                {"type": "directory", "path": "doom", "oid": "d", "size": 0},
            ]
            return self._send(200, json.dumps(entries).encode())
        if self.path.startswith("/o/r/resolve/"):
            rng = self.headers.get("Range")
            start = int(rng.split("=")[1].rstrip("-")) if rng else 0
            if start >= len(DATA):
                return self._send(416)
            part = DATA[start:]
            self.send_response(206 if rng else 200)
            self.send_header("Content-Length", str(len(part)))
            self.end_headers()
            if _Handler.drops:
                _Handler.drops -= 1
                self.wfile.write(part[:2000])
                self.wfile.flush()
                self.connection.shutdown(2)
                return None
            self.wfile.write(part)
            return None
        return self._send(404, b"a body that must never be shown")


@pytest.fixture
def client(monkeypatch):
    for var in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY"):
        monkeypatch.delenv(var, raising=False)
    _Handler.drops = 1
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield HubClient(f"http://127.0.0.1:{server.server_address[1]}", timeout_s=5)
    server.shutdown()
    server.server_close()


def test_listing_and_revision(client):
    assert client.revision_sha("o/r", "main") == REV
    files = client.tree("o/r", REV, None)
    assert [(f.path, f.size, f.lfs_sha256 is not None) for f in files] == [
        ("model.safetensors", len(DATA), True)
    ]


def test_a_404_names_the_url_and_status_never_the_body(client):
    with pytest.raises(HubError) as raised:
        client.tree("o/r", REV, "multilingual")
    assert raised.value.status == 404
    assert raised.value.url.endswith(f"/api/models/o/r/tree/{REV}/multilingual")
    assert "never be shown" not in str(raised.value)


def test_a_cut_download_is_kept_and_resumed(client, tmp_path):
    target = tmp_path / "model.safetensors.part"
    with pytest.raises(HubError, match="got 2000 of"):
        client.download("o/r", REV, "model.safetensors", target)
    assert target.stat().st_size == 2000
    client.download("o/r", REV, "model.safetensors", target)
    assert target.read_bytes() == DATA
    client.download("o/r", REV, "model.safetensors", target)  # 416: complete
    assert target.read_bytes() == DATA
