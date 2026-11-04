"""The browser's Back button in a real browser (UI Stage 5, owner requirement):
click forward through Journey A, press Back three times and check the step each
time. Skips, with the reason, when Python Playwright or its browser is not
installed (CI has neither). Page text only, no screenshots; fake mode; the demo
files go to a temporary folder."""

import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

sync_api = pytest.importorskip(
    "playwright.sync_api", reason="Python Playwright is not installed"
)
pytest.importorskip("streamlit", reason="extra `ui` is not installed")

REPO = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("localhost", 0))
        return sock.getsockname()[1]


@pytest.fixture
def server(tmp_path):
    port = _free_port()
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(REPO / "scripts" / "demo_ui.py"),
            "--server.headless=true",
            f"--server.port={port}",
            "--server.address=localhost",
            "--browser.gatherUsageStats=false",
            "--server.fileWatcherType=none",
        ],
        cwd=REPO,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://localhost:{port}/?lang=en&theme=dark"
    for _ in range(60):
        try:
            urllib.request.urlopen(url, timeout=1)
            break
        except OSError:
            time.sleep(0.5)
    else:
        process.kill()
        pytest.skip("the demo server did not start")
    yield url
    process.terminate()
    process.wait(timeout=10)


def test_back_button_walks_journey_a_backwards(server):
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001 - browser binaries are optional
            pytest.skip(f"no Playwright browser installed ({type(exc).__name__})")
        page = browser.new_page()
        page.goto(server)
        page.get_by_role("button", name="Choose a chatbot").click()
        page.get_by_role("heading", name="Your chatbots").wait_for()
        page.get_by_role("button", name="Continue").click()
        page.get_by_role("heading", name="Optimisation settings").wait_for()
        page.get_by_role("button", name="Start chatting").click()
        page.get_by_text("Change settings").wait_for()
        page.go_back()
        page.get_by_role("heading", name="Optimisation settings").wait_for()
        page.go_back()
        page.get_by_role("heading", name="Your chatbots").wait_for()
        page.go_back()
        page.get_by_role("button", name="Start direct chat").wait_for()
        page.go_forward()
        page.get_by_role("heading", name="Your chatbots").wait_for()
        browser.close()
