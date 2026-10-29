"""Helpers shared by the deterministic specialists (not by the Critic)."""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from ..orchestration.event_log import sha256_file, utcnow

ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = ROOT / "results/stage3/cache"
STAGE1_SCORE_INDEX = ROOT / "data/raw/pgs_catalog_api/score_all.json"
STAGE1_SUMMARY = ROOT / "results/stage1/stage1_summary.json"
AUTHORIZED_GENOTYPES = ROOT / "data/synthetic/PGS005206_synthetic_dosages_seed20261029.tsv"
AUTHORIZED_GENOTYPES_META = AUTHORIZED_GENOTYPES.with_suffix(".json")
PINNED_SCORING_FILES = {
    "PGS005206": {"path": ROOT / "data/raw/scoring_files/PGS005206/PGS005206_hmPOS_GRCh38.txt.gz",
                  "sha256": "406045ea0a082ae6fe640d22b8e2f282cacdcdfa2536b62148fb027703b0b6d3",
                  "approval": "DR-0001"},
}
CANONICAL_COLUMNS = ["variant_id", "rsID", "chr_GRCh38", "pos_GRCh38", "effect_allele"]
ALLOWED_HOSTS = {"www.pgscatalog.org", "ftp.ebi.ac.uk", "www.ebi.ac.uk"}

# Skeletal-site vocabulary. Order matters: specific sites before the bare word "hip".
SITE_PATTERNS = [
    (re.compile(r"total[\s-]*hip", re.I), "total_hip"),
    (re.compile(r"femoral[\s-]*neck", re.I), "femoral_neck"),
    (re.compile(r"total[\s-]*body|whole[\s-]*body|\btb-?bmd\b|\btblh\b", re.I), "total_body"),
    (re.compile(r"lumbar[\s-]*spine", re.I), "lumbar_spine"),
    (re.compile(r"\bheel\b|calcane", re.I), "heel"),
    (re.compile(r"forearm|\bradius\b", re.I), "forearm"),
    (re.compile(r"\bhip\b", re.I), "hip_unspecified"),
]


def skeletal_sites(text: str | None) -> list[str]:
    if not text:
        return []
    found, rest = [], text
    for pat, site in SITE_PATTERNS:
        if pat.search(rest):
            found.append(site)
            rest = pat.sub(" ", rest)
    return found


@dataclass
class RunContext:
    """What a specialist may see: the run directory, the request and the inputs. Never the scenario."""
    run_dir: Path
    request: str
    requested_phenotype: str
    provided_scores: list[str]
    input_artifacts: dict[str, str]                  # name -> run-relative path
    evidence: dict[str, str] = field(default_factory=dict)   # pgs_id -> evidence record path (run-relative)
    assessments: dict[str, str] = field(default_factory=dict)

    def path(self, rel: str) -> Path:
        p = (self.run_dir / rel).resolve()
        if not p.is_relative_to(self.run_dir.resolve()):
            raise PermissionError(f"path outside run directory: {rel}")
        return p

    def rel(self, p: Path) -> str:
        return str(Path(p).resolve().relative_to(self.run_dir.resolve()))


def cached_get_json(url: str, cache_name: str) -> tuple[dict | list, dict]:
    """GET JSON once; later calls reuse the cached copy. Returns (data, provenance)."""
    host = urllib.parse.urlparse(url).hostname
    if host not in ALLOWED_HOSTS:
        raise PermissionError(f"host not allowed: {host}")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    body_p, prov_p = CACHE_DIR / f"{cache_name}.json", CACHE_DIR / f"{cache_name}.provenance.json"
    if body_p.exists() and prov_p.exists():
        prov = json.loads(prov_p.read_text())
        if sha256_file(body_p) == prov["sha256"]:
            return json.loads(body_p.read_text()), {**prov, "served_from": "cache"}
    t0 = time.perf_counter()
    req = urllib.request.Request(url, headers={"User-Agent": "PRSWeave/0.1 (research prototype)", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read()
    body_p.write_bytes(body)
    prov = {"url": url, "retrieved_at": utcnow(), "sha256": sha256_file(body_p), "bytes": len(body),
            "latency_s": round(time.perf_counter() - t0, 3), "host": host}
    prov_p.write_text(json.dumps(prov, indent=2))
    return json.loads(body), {**prov, "served_from": "live"}


def parse_genotype_table(path: Path) -> dict:
    """Header-name-based parse that never fails on layout; reports what it sees."""
    with open(path) as fh:
        lines = [l.rstrip("\n") for l in fh if not l.startswith("#") and l.strip()]
    header = lines[0].split("\t")
    counts = {h: header.count(h) for h in header}
    dup = sorted(h for h, n in counts.items() if n > 1)
    missing = [c for c in CANONICAL_COLUMNS if c not in counts]
    ids = [h for h in header if h not in CANONICAL_COLUMNS]
    rows, ragged = {}, []
    for n, line in enumerate(lines[1:], start=2):
        f = line.split("\t")
        if len(f) != len(header):
            ragged.append(n)
            continue
        rec = dict(zip(header, f))
        rows[rec.get("variant_id", f"line{n}")] = rec
    return {"header": header, "ids": ids, "rows": rows, "duplicate_columns": dup, "missing_columns": missing,
            "ragged_lines": ragged, "canonical_order": header[:5] == CANONICAL_COLUMNS}
