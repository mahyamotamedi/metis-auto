"""Fetch the context-compressor model files in config/reference/compressors.toml, once.

    python scripts/fetch_compressor_assets.py           # download missing files
    python scripts/fetch_compressor_assets.py --check   # verify only, no network

The only step that downloads compressor weights (network, explicit; like
installing a package; about 2.2 GB for LLMLingua-2 XLM-RoBERTa-large). Each
file goes to paths.compressor_assets/<ref>/<revision>/ (default
data/compressors/, git-ignored) and must match the sha256 pinned in the
compressor table, or it is deleted and the script fails. Nothing else in the
project downloads them: the adapter loads local files with the Hugging Face
libraries set offline, and tests skip when the files are absent. Public files
only (Microsoft's LLMLingua-2 model, MIT licence). No API key, no model call,
no spend. Thin wrapper over settings and adapters.tokenizers.sha256_of.
"""

from __future__ import annotations

import argparse
import sys
import urllib.request

from metis_auto.adapters.tokenizers import sha256_of
from metis_auto.settings import load_settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="verify only")
    args = parser.parse_args()

    loaded = load_settings()
    table = loaded.reference.compressors
    if table is None:
        print("no compressor table configured")
        return 0
    root = loaded.path(loaded.settings.paths.compressor_assets)
    failed = False
    for spec in table.compressors:
        for asset in spec.files:
            target = root / spec.directory / asset.name
            label = f"{spec.ref}/{asset.name}"
            if target.is_file() and sha256_of(target) == asset.sha256:
                print(f"{label}: ok ({target})")
                continue
            if args.check:
                print(f"{label}: MISSING or wrong hash ({target})")
                failed = True
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_suffix(target.suffix + ".part")
            size = f", {asset.size_bytes:,} bytes" if asset.size_bytes else ""
            print(f"{label}: downloading {asset.url}{size}")
            urllib.request.urlretrieve(asset.url, partial)  # noqa: S310 (pinned https)
            digest = sha256_of(partial)
            if digest != asset.sha256:
                partial.unlink()
                print(f"{label}: sha256 {digest} != pinned {asset.sha256}")
                failed = True
                continue
            partial.replace(target)
            print(f"{label}: ok ({target})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
