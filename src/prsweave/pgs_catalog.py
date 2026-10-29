"""Minimal, dependency-free client for the PGS Catalog REST API.

Standard library only, so Stage 1 runs without installing anything.
Every response can be cached to disk along with its retrieval time and
SHA-256, which gives an audit trail for later stages.

API docs: https://www.pgscatalog.org/rest/
Documented rate limit: 100 queries per minute.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

BASE_URL = "https://www.pgscatalog.org/rest"
FTP_BASE = "https://ftp.ebi.ac.uk/pub/databases/spot/pgs/scores"
USER_AGENT = "PRSWeave/0.1 (research prototype)"

# 100 requests/min is documented; stay well under it.
MIN_INTERVAL_S = 0.7


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class Retrieval:
    url: str
    retrieved_at: str
    status: int
    sha256: str
    nbytes: int


class PGSCatalogClient:
    def __init__(self, cache_dir: Path | None = None, timeout: float = 60.0, retries: int = 4):
        self.cache_dir = cache_dir
        self.timeout = timeout
        self.retries = retries
        self.log: list[Retrieval] = []
        self._last = 0.0

    # -- transport -----------------------------------------------------------------
    def _fetch(self, url: str) -> tuple[int, bytes]:
        for attempt in range(self.retries + 1):
            wait = MIN_INTERVAL_S - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = resp.read()
                    self.log.append(Retrieval(url, _utcnow(), resp.status, sha256_bytes(body), len(body)))
                    return resp.status, body
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < self.retries:
                    # The API reports seconds until reset as 'availableIn'.
                    try:
                        delay = float(json.loads(e.read()).get("availableIn", 10))
                    except Exception:
                        delay = 10.0
                    time.sleep(delay + 1)
                    continue
                if e.code >= 500 and attempt < self.retries:
                    time.sleep(2 ** attempt)
                    continue
                raise
            except urllib.error.URLError:
                if attempt < self.retries:
                    time.sleep(2 ** attempt)
                    continue
                raise
        raise RuntimeError(f"unreachable: {url}")

    def get_json(self, path: str, params: dict[str, Any] | None = None, cache_name: str | None = None) -> Any:
        url = f"{BASE_URL}/{path.lstrip('/')}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        _, body = self._fetch(url)
        data = json.loads(body)
        if self.cache_dir and cache_name:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            (self.cache_dir / f"{cache_name}.json").write_bytes(body)
        return data

    def paginate(self, path: str, params: dict[str, Any] | None = None) -> Iterator[dict]:
        params = dict(params or {})
        params.setdefault("limit", 250)
        url = f"{BASE_URL}/{path.lstrip('/')}?" + urllib.parse.urlencode(params)
        while url:
            _, body = self._fetch(url)
            page = json.loads(body)
            yield from page.get("results", [])
            url = page.get("next")

    def download(self, url: str, dest: Path) -> Retrieval:
        _, body = self._fetch(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
        return self.log[-1]

    # -- endpoints -----------------------------------------------------------------
    def info(self) -> dict:
        return self.get_json("info/", cache_name="info")

    def trait_search(self, term: str) -> dict:
        safe = "".join(c if c.isalnum() else "_" for c in term)
        return self.get_json("trait/search", {"term": term, "include_children": 1}, cache_name=f"trait_search_{safe}")

    def trait(self, trait_id: str) -> dict:
        return self.get_json(f"trait/{trait_id}", {"include_children": 1}, cache_name=f"trait_{trait_id}")

    def score(self, pgs_id: str) -> dict:
        return self.get_json(f"score/{pgs_id}", cache_name=f"score_{pgs_id}")

    def performance(self, pgs_id: str) -> dict:
        return self.get_json("performance/search", {"pgs_id": pgs_id, "limit": 250}, cache_name=f"performance_{pgs_id}")

    def all_scores(self) -> list[dict]:
        return list(self.paginate("score/all"))
