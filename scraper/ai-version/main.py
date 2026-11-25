"""Quarantined AI Rematch Scraper (ai-version/main.py) — Rematch V2."""

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field, ValidationError

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
# Reuse existing parent cache if present so testing never re-hammers the sandbox
SHARED_CACHE = ROOT.parent / "cache"
CACHE_DIR = SHARED_CACHE if SHARED_CACHE.exists() else (ROOT / "cache")
OUT_DIR = ROOT / "output"

UA = "FlyRankInternship-A9-AIRematch/1.0 (+https://github.com/rozak-27/task-api)"
START = "https://books.toscrape.com/catalogue/page-1.html"
BROKEN_PROBE = "https://books.toscrape.com/catalogue/ai-rematch-missing-book_000/index.html"


class CleanBook(BaseModel):
    title: str = Field(min_length=1)
    product_url: str = Field(pattern=r"^https://")
    price_text: str = Field(min_length=1)
    price_gbp: float = Field(gt=0)
    availability_text: str = Field(min_length=1)
    rating_text: Literal["One", "Two", "Three", "Four", "Five"]
    description: str | None = None
    source_page: str = Field(pattern=r"^https://")
    fetched_at: str


class PoliteFetcher:
    def __init__(self, delay: float = 0.55, timeout: float = 10.0):
        self.delay = delay
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA})
        self.last_call = 0.0
        self.fetched = 0
        self.cache_hits = 0

    def get(self, url: str, cache_file: Path) -> tuple[str, str]:
        if cache_file.exists():
            self.cache_hits += 1
            ts = datetime.fromtimestamp(cache_file.stat().st_mtime, tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            return cache_file.read_text(encoding="utf-8"), ts

        for attempt in range(2):
            wait = self.delay - (time.monotonic() - self.last_call)
            if self.last_call > 0 and wait > 0:
                time.sleep(wait)
            try:
                resp = self.session.get(url, timeout=self.timeout)
                self.last_call = time.monotonic()
            except requests.RequestException as exc:
                self.last_call = time.monotonic()
                if attempt == 0:
                    time.sleep(1.0)
                    continue
                raise RuntimeError(f"Network failure: {exc}") from exc

            if resp.status_code == 200:
                self.fetched += 1
                text = resp.content.decode("utf-8")
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(text, encoding="utf-8")
                return text, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            if resp.status_code in (403, 404):
                raise RuntimeError(f"HTTP {resp.status_code}")
            if 500 <= resp.status_code < 600 and attempt == 0:
                time.sleep(1.0)
                continue
            raise RuntimeError(f"HTTP {resp.status_code}")

        raise RuntimeError("Retries exhausted")


def slug_path(url: str) -> Path:
    parts = [p for p in urlparse(url).path.split("/") if p and p != "index.html"]
    slug = re.sub(r"[^a-zA-Z0-9_-]", "_", parts[-1] if parts else "page")
    return CACHE_DIR / "books" / f"{slug}.html"


def parse_detail(html: str, url: str, source_page: str, fetched_at: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    article = soup.select_one("article.product_page")
    if not article:
        raise ValueError("Missing article.product_page")
    main_div = article.select_one("div.product_main")
    if not main_div:
        raise ValueError("Missing div.product_main")

    rating_el = main_div.select_one("p.star-rating")
    rating = next(
        (c for c in (rating_el.get("class", []) if rating_el else []) if c != "star-rating"),
        None,
    )
    desc_h = article.select_one("#product_description")
    desc_p = desc_h.find_next_sibling("p") if desc_h else None
    desc = " ".join(desc_p.get_text().split()) if desc_p else ""

    price_text = main_div.select_one("p.price_color").get_text(strip=True)
    price_num = float(re.sub(r"[^0-9.]", "", price_text))

    return {
        "title": " ".join(main_div.select_one("h1").get_text().split()),
        "product_url": url,
        "price_text": price_text,
        "price_gbp": round(price_num, 2),
        "availability_text": " ".join(main_div.select_one("p.availability").get_text().split()),
        "rating_text": rating,
        "description": desc or None,
        "source_page": source_page,
        "fetched_at": fetched_at,
    }


def run() -> None:
    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    t0 = time.perf_counter()
    fetcher = PoliteFetcher()

    page_url: str | None = START
    discovered: dict[str, str] = {}
    for idx in range(1, 4):
        if not page_url:
            break
        html, _ = fetcher.get(page_url, CACHE_DIR / f"catalogue-page-{idx}.html")
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.select("article.product_pod h3 a[href]"):
            book_url = urljoin(page_url, a["href"])
            discovered.setdefault(book_url, page_url)
        nxt = soup.select_one("li.next a[href]")
        page_url = urljoin(page_url, nxt["href"]) if nxt else None

    targets = list(discovered.items()) + [(BROKEN_PROBE, START)]
    valid_by_url: dict[str, dict] = {}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    books_file = OUT_DIR / "books.json"
    if books_file.exists():
        for existing in json.loads(books_file.read_text(encoding="utf-8")):
            valid_by_url[existing["product_url"]] = existing

    errors: list[dict] = []
    failures: list[dict] = []

    for book_url, src in targets:
        try:
            html, fetched_at = fetcher.get(book_url, slug_path(book_url))
            candidate = parse_detail(html, book_url, src, fetched_at)
            rec = CleanBook.model_validate(candidate)
            valid_by_url[rec.product_url] = rec.model_dump(mode="json")
        except ValidationError as ve:
            errors.append({"product_url": book_url, "reason": str(ve)})
        except Exception as exc:
            failures.append({"url": book_url, "reason": str(exc)})

    books_list = list(valid_by_url.values())
    books_file.write_text(json.dumps(books_list, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUT_DIR / "errors.json").write_text(json.dumps(errors, indent=2), encoding="utf-8")
    report = {
        "started_at": started,
        "duration_seconds": round(time.perf_counter() - t0, 3),
        "pages_fetched": fetcher.fetched,
        "cache_hits": fetcher.cache_hits,
        "valid_records": len(books_list),
        "invalid_records": len(errors),
        "failed_pages": len(failures),
    }
    (OUT_DIR / "run-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    run()
