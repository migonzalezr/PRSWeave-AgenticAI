#!/usr/bin/env python3
"""Download the public PGS Catalog scoring files used in Stages 1-3, verified by checksum.

These third-party files are not redistributed in this repository. This script fetches
them from the official PGS Catalog FTP into data/raw/scoring_files/ and checks each one
against the SHA-256 recorded in results/stage1/stage1_summary.json (retrieved 2026-10-29).
A mismatch is reported, never silently accepted.

Usage:
    python3 scripts/fetch_public_data.py                 # all Stage 1 candidate files (9 small files)
    python3 scripts/fetch_public_data.py --only PGS005206
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="fetch files for one PGS ID only")
    a = ap.parse_args()
    summary = json.loads((ROOT / "results/stage1/stage1_summary.json").read_text())
    bad = 0
    for cand in summary["candidates"]:
        pgs = cand["score"]["id"]
        if a.only and pgs != a.only:
            continue
        for f in cand["files"].values():
            dest = ROOT / f["path"]
            if not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                req = urllib.request.Request(f["url"], headers={"User-Agent": "PRSWeave/0.1 (research prototype)"})
                dest.write_bytes(urllib.request.urlopen(req, timeout=60).read())
            got = hashlib.sha256(dest.read_bytes()).hexdigest()
            ok = got == f["sha256"]
            bad += not ok
            print(f"{'OK      ' if ok else 'MISMATCH'} {f['path']}" + ("" if ok else f"  expected {f['sha256'][:12]}..., got {got[:12]}..."))
    if bad:
        print(f"\n{bad} file(s) differ from the Stage 1 record. The catalog may have updated them; "
              "PRSWeave refuses to score with an unpinned file.", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
