"""Fetch the reranker weights listed in config/reference/rerankers.toml, once.

    python scripts/fetch_reranker_assets.py           # download missing files
    python scripts/fetch_reranker_assets.py --check   # verify only, no network

The only step that downloads reranker weights (network, explicit, like
installing a package; cut-first item (a), R-A2, ADR-0040). Each file goes to
data/rerankers/<ref>/<revision>/ (git-ignored) and must match the sha256 pinned
in the table, or it is deleted and the script fails. **It refuses while the
revision or any sha256 is unpinned** (the pins are owner-set placeholders; no
value is invented). No API key, no model call, no spend, no data uploaded:
downloads only. Thin wrapper over adapters.rerankers.assets.
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

from metis_auto.adapters.rerankers.assets import load_specs, unpinned_reasons
from metis_auto.adapters.tokenizers import sha256_of

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / "config" / "reference" / "rerankers.toml"
ASSETS = ROOT / "data" / "rerankers"


def main(
    argv: list[str] | None = None, *, table: Path = TABLE, root: Path = ASSETS
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="verify only")
    args = parser.parse_args(argv)
    failed = False
    for spec in load_specs(table).values():
        reasons = unpinned_reasons(spec)
        if reasons:
            print("refused (nothing downloaded):")
            for reason in reasons:
                print(f"  - {reason}")
            failed = True
            continue
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
            print(f"{label}: downloading {spec.url(asset.name)}")
            urllib.request.urlretrieve(spec.url(asset.name), partial)  # noqa: S310
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
