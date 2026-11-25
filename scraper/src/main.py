"""Stage 5 — Fault isolation per page, selective retry (never 404/403), and run-report.json."""

import argparse
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
from pydantic import BaseModel, Field, ValidationError, field_validator

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = BASE_DIR / "cache"
BOOKS_CACHE_DIR = CACHE_DIR / "books"
OUTPUT_DIR = BASE_DIR / "output"

START_URL = "https://books.toscrape.com/catalogue/page-1.html"
DELIBERATE_BROKEN_URL = (
    "https://books.toscrape.com/catalogue/deliberately-broken-book_99999/index.html"
)
USER_AGENT = "FlyRankInternship-A9/1.0 (+https://github.com/rozak-27/task-api)"
TIMEOUT_SECONDS = 10
POLITE_DELAY_SECONDS = 0.52
MAX_CATALOGUE_PAGES = 3

RATING_WORDS = {"One", "Two", "Three", "Four", "Five"}
_last_network_request_at: float | None = None


class FetchFailure(Exception):
    def __init__(self, url: str, reason: str, status_code: int | None = None):
        super().__init__(reason)
        self.url = url
        self.reason = reason
        self.status_code = status_code


class BookRecord(BaseModel):
    title: str = Field(min_length=1)
    product_url: str
    price_text: str = Field(min_length=1)
    price_gbp: float = Field(gt=0)
    availability_text: str = Field(min_length=1)
    rating_text: Literal["One", "Two", "Three", "Four", "Five"]
    description: str | None = None
    source_page: str
    fetched_at: str = Field(min_length=10)

    @field_validator("product_url", "source_page")
    @classmethod
    def must_be_https_url(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("URL must be an absolute https:// URL")
        return value


def normalize_price_gbp(price_text: str | None) -> float:
    if not price_text:
        raise ValueError("Missing price_text")
    cleaned = re.sub(r"[^0-9.]", "", price_text)
    if not cleaned:
        raise ValueError(f"Cannot parse numeric GBP price from {price_text!r}")
    return round(float(cleaned), 2)


def polite_wait() -> None:
    global _last_network_request_at
    if _last_network_request_at is not None:
        elapsed = time.monotonic() - _last_network_request_at
        if elapsed < POLITE_DELAY_SECONDS:
            time.sleep(POLITE_DELAY_SECONDS - elapsed)


def book_cache_path(product_url: str) -> Path:
    path_parts = [p for p in urlparse(product_url).path.split("/") if p and p != "index.html"]
    slug = re.sub(r"[^a-zA-Z0-9_-]", "_", path_parts[-1] if path_parts else "book")
    return BOOKS_CACHE_DIR / f"{slug}.html"


def fetch_html(url: str, cache_path: Path) -> tuple[str, str, bool]:
    """Fetch HTML with cache, timeout, and 1 retry on timeout/5xx (never retry 404 or 403)."""
    global _last_network_request_at
    if cache_path.exists():
        html = cache_path.read_text(encoding="utf-8")
        mtime = datetime.fromtimestamp(cache_path.stat().st_mtime, tz=timezone.utc)
        fetched_at = mtime.strftime("%Y-%m-%dT%H:%M:%SZ")
        return html, fetched_at, True

    max_attempts = 2
    for attempt in range(1, max_attempts + 1):
        polite_wait()
        try:
            response = requests.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=TIMEOUT_SECONDS,
            )
            _last_network_request_at = time.monotonic()
        except (requests.Timeout, requests.ConnectionError) as exc:
            _last_network_request_at = time.monotonic()
            if attempt < max_attempts:
                time.sleep(1.0)
                continue
            raise FetchFailure(url, f"Network timeout/error after {attempt} attempts: {exc}") from exc

        status = response.status_code
        if status == 200:
            html = response.content.decode("utf-8")
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(html, encoding="utf-8")
            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            return html, now_iso, False

        # Never retry 404 (not found) or 403 (forbidden)
        if status in (403, 404):
            raise FetchFailure(url, f"HTTP {status} (not retried)", status_code=status)

        # Retry once on 5xx server error
        if 500 <= status < 600 and attempt < max_attempts:
            time.sleep(1.0)
            continue

        raise FetchFailure(url, f"HTTP {status}", status_code=status)

    raise FetchFailure(url, "Exhausted fetch attempts")


def discover_catalogue_books(
    start_url: str = START_URL, max_pages: int = MAX_CATALOGUE_PAGES
) -> tuple[int, int, dict[str, str], int, int]:
    current_url: str | None = start_url
    pages_visited = 0
    discovered_total = 0
    pages_fetched = 0
    cache_hits = 0
    unique_books: dict[str, str] = {}

    while current_url and pages_visited < max_pages:
        page_num = pages_visited + 1
        cache_file = CACHE_DIR / f"catalogue-page-{page_num}.html"
        html, _, from_cache = fetch_html(current_url, cache_file)
        if from_cache:
            cache_hits += 1
        else:
            pages_fetched += 1
        pages_visited += 1

        soup = BeautifulSoup(html, "html.parser")
        for link in soup.select("article.product_pod h3 a[href]"):
            abs_book_url = urljoin(current_url, link["href"])
            discovered_total += 1
            if abs_book_url not in unique_books:
                unique_books[abs_book_url] = current_url

        next_anchor = soup.select_one("li.next a[href]")
        current_url = urljoin(current_url, next_anchor["href"]) if next_anchor else None

    return pages_visited, discovered_total, unique_books, pages_fetched, cache_hits


def extract_raw_book(html: str, product_url: str, source_page: str, fetched_at: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    product = soup.select_one("article.product_page")
    if product is None:
        raise ValueError(f"Missing article.product_page container on {product_url}")

    main_box = product.select_one("div.product_main")
    if main_box is None:
        raise ValueError(f"Missing div.product_main container on {product_url}")

    title_el = main_box.select_one("h1")
    price_el = main_box.select_one("p.price_color")
    avail_el = main_box.select_one("p.availability")
    rating_el = main_box.select_one("p.star-rating")

    rating_text = None
    if rating_el:
        for cls in rating_el.get("class", []):
            if cls in RATING_WORDS:
                rating_text = cls
                break

    desc_header = product.select_one("#product_description")
    desc_p = desc_header.find_next_sibling("p") if desc_header else None
    raw_desc = desc_p.get_text(strip=True) if desc_p else ""
    description = raw_desc if raw_desc else None

    return {
        "title": title_el.get_text(strip=True) if title_el else None,
        "product_url": product_url,
        "price_text": price_el.get_text(strip=True) if price_el else None,
        "availability_text": " ".join(avail_el.get_text().split()) if avail_el else None,
        "rating_text": rating_text,
        "description": description,
        "source_page": source_page,
        "fetched_at": fetched_at,
    }


def normalize_and_validate(raw: dict) -> tuple[BookRecord | None, dict | None]:
    try:
        candidate = {
            **raw,
            "price_gbp": normalize_price_gbp(raw.get("price_text")),
        }
        validated = BookRecord.model_validate(candidate)
        return validated, None
    except (ValidationError, ValueError) as exc:
        return None, {
            "product_url": raw.get("product_url"),
            "reason": str(exc),
            "raw_record": raw,
        }


def store_books_idempotently(records: list[BookRecord], books_path: Path) -> list[dict]:
    existing_by_url: dict[str, dict] = {}
    if books_path.exists():
        try:
            loaded = json.loads(books_path.read_text(encoding="utf-8"))
            for item in loaded:
                if isinstance(item, dict) and "product_url" in item:
                    existing_by_url[item["product_url"]] = item
        except Exception:
            pass

    for rec in records:
        existing_by_url[rec.product_url] = rec.model_dump(mode="json")

    merged = list(existing_by_url.values())
    books_path.parent.mkdir(parents=True, exist_ok=True)
    books_path.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description="Polite Books to Scrape pipeline.")
    parser.add_argument(
        "--no-broken-url",
        action="store_true",
        help="Skip the deliberate broken URL resilience check.",
    )
    args = parser.parse_args()

    started_dt = datetime.now(timezone.utc)
    t0 = time.perf_counter()

    cat_pages, discovered_total, unique_books, pages_fetched, cache_hits = (
        discover_catalogue_books()
    )

    work_items = list(unique_books.items())
    if not args.no_broken_url:
        work_items.append((DELIBERATE_BROKEN_URL, "synthetic://fault-injection-test"))

    valid_records: list[BookRecord] = []
    error_records: list[dict] = []
    failed_pages: list[dict] = []

    for product_url, source_page in work_items:
        try:
            html, fetched_at, from_cache = fetch_html(
                product_url, book_cache_path(product_url)
            )
            if from_cache:
                cache_hits += 1
            else:
                pages_fetched += 1

            raw = extract_raw_book(html, product_url, source_page, fetched_at)
            validated, err = normalize_and_validate(raw)
            if validated is not None:
                valid_records.append(validated)
            elif err is not None:
                error_records.append(err)
        except FetchFailure as exc:
            print(f"[SKIP BROKEN PAGE] {exc.url} -> {exc.reason}")
            failed_pages.append(
                {
                    "url": exc.url,
                    "status_code": exc.status_code,
                    "reason": exc.reason,
                }
            )
        except Exception as exc:
            print(f"[SKIP UNEXPECTED ERROR] {product_url} -> {exc}")
            failed_pages.append(
                {"url": product_url, "status_code": None, "reason": str(exc)}
            )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    merged = store_books_idempotently(valid_records, OUTPUT_DIR / "books.json")
    (OUTPUT_DIR / "errors.json").write_text(
        json.dumps(error_records, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    finished_dt = datetime.now(timezone.utc)
    duration_sec = round(time.perf_counter() - t0, 3)

    report = {
        "started_at": started_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "finished_at": finished_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "duration_seconds": duration_sec,
        "catalogue_pages": cat_pages,
        "discovered_urls": discovered_total,
        "unique_urls": len(unique_books),
        "pages_fetched": pages_fetched,
        "cache_hits": cache_hits,
        "valid_records": len(merged),
        "invalid_records": len(error_records),
        "failed_pages": len(failed_pages),
        "failures": failed_pages,
    }
    (OUTPUT_DIR / "run-report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(
        f"catalogue_pages={cat_pages}, discovered={discovered_total}, "
        f"unique_urls={len(unique_books)}, valid_records={len(merged)}, "
        f"failed_pages={len(failed_pages)}, cache_hits={cache_hits}"
    )


if __name__ == "__main__":
    main()
