"""Fetch the tokenizer files named in config/reference/tokenizers.toml, once.

    python scripts/fetch_tokenizer_assets.py           # download missing files
    python scripts/fetch_tokenizer_assets.py --check   # verify only, no network

This is the only step that downloads tokenizer data (network, explicit; like
installing a package). Each file goes to paths.tokenizer_assets (default
data/tokenizers/, git-ignored) and must match the sha256 pinned in the
tokenizer table, or it is deleted and the script fails. Nothing else in the
project downloads tokenizers: tests and pipelines only read these files.
Public files only (OpenAI's o200k_base encoding; DeepSeek-V4-Flash's
tokenizer.json, MIT licence). No API key, no model call, no spend.
Thin wrapper over settings and adapters.tokenizers.
"""

from __future__ import annotations

import argparse
import sys
import urllib.request

from metis_auto.adapters.tokenizers import sha256_of
from metis_auto.settings import load_settings
from metis_auto.wiring.tokenizers import build_tokenizers


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="verify only")
    args = parser.parse_args()

    loaded = load_settings()
    table = loaded.reference.tokenizers
    if table is None:
        print("no tokenizer table configured")
        return 0
    root = loaded.path(loaded.settings.paths.tokenizer_assets)
    failed = False
    for spec in table.tokenizers:
        if spec.asset is None:
            print(f"{spec.ref}: {spec.backend.value}, no asset needed")
            continue
        target = root / spec.asset.path
        if target.is_file() and sha256_of(target) == spec.asset.sha256:
            print(f"{spec.ref}: ok ({target})")
            continue
        if args.check:
            print(f"{spec.ref}: MISSING or wrong hash ({target})")
            failed = True
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(target.suffix + ".part")
        print(f"{spec.ref}: downloading {spec.asset.url}")
        urllib.request.urlretrieve(spec.asset.url, partial)  # noqa: S310 (pinned https)
        digest = sha256_of(partial)
        if digest != spec.asset.sha256:
            partial.unlink()
            print(f"{spec.ref}: sha256 {digest} != pinned {spec.asset.sha256}")
            failed = True
            continue
        partial.replace(target)
        print(f"{spec.ref}: ok ({target})")

    for status in build_tokenizers(loaded).status:
        note = f" [fallback: {status.reason}]" if status.reason else ""
        print(f"  {status.ref}: {status.loaded} ({status.fidelity}){note}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
