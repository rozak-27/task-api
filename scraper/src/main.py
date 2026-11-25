"""The Polite Scraper — Complete Pipeline with Backoff Retry, Change Detection, CSV & HTML Dashboard."""

import argparse
import csv
import hashlib
import html as html_lib
import json
import random
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
MAX_RETRY_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 1.0

RATING_WORDS = {"One", "Two", "Three", "Four", "Five"}
_last_network_request_at: float | None = None


def log_structured(event: str, **fields) -> None:
    payload = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event": event,
        **fields,
    }
    print(json.dumps(payload, ensure_ascii=False))


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
    if not cleaned or cleaned.count(".") > 1:
        raise ValueError(f"Cannot parse numeric GBP price from {price_text!r}")
    value = round(float(cleaned), 2)
    if value <= 0:
        raise ValueError(f"Price must be positive, got {value}")
    return value


def resolve_book_url(page_url: str, relative_href: str) -> str:
    return urljoin(page_url, relative_href)


def compute_retry_wait(attempt: int, retry_after_header: str | None = None) -> float:
    """Obey numeric Retry-After header when present; otherwise exponential backoff + jitter."""
    if retry_after_header:
        try:
            parsed = float(retry_after_header.strip())
            if parsed >= 0:
                return min(parsed, 30.0)
        except ValueError:
            pass
    jitter = random.uniform(0.05, 0.25)
    return round((BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))) + jitter, 3)


def should_retry_status(status_code: int) -> bool:
    """Never retry 404 or 403; retry 429 Too Many Requests and 5xx server errors."""
    if status_code in (403, 404):
        return False
    return status_code == 429 or (500 <= status_code < 600)


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


def fetch_html(
    url: str,
    cache_path: Path,
    session: requests.Session | None = None,
    max_attempts: int = MAX_RETRY_ATTEMPTS,
) -> tuple[str, str, bool]:
    global _last_network_request_at
    if cache_path.exists():
        html = cache_path.read_text(encoding="utf-8")
        mtime = datetime.fromtimestamp(cache_path.stat().st_mtime, tz=timezone.utc)
        fetched_at = mtime.strftime("%Y-%m-%dT%H:%M:%SZ")
        return html, fetched_at, True

    http = session or requests
    for attempt in range(1, max_attempts + 1):
        polite_wait()
        try:
            response = http.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=TIMEOUT_SECONDS,
            )
            _last_network_request_at = time.monotonic()
        except (requests.Timeout, requests.ConnectionError) as exc:
            _last_network_request_at = time.monotonic()
            log_structured("fetch_network_error", url=url, status=None, attempt=attempt, error=str(exc))
            if attempt < max_attempts:
                time.sleep(compute_retry_wait(attempt))
                continue
            raise FetchFailure(url, f"Network timeout/error after {attempt} attempts: {exc}") from exc

        status = response.status_code
        log_structured("fetch_response", url=url, status=status, attempt=attempt, bytes=len(response.content))

        if status == 200:
            html = response.content.decode("utf-8")
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(html, encoding="utf-8")
            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            return html, now_iso, False

        if not should_retry_status(status):
            raise FetchFailure(url, f"HTTP {status} (not retried)", status_code=status)

        if attempt < max_attempts:
            wait_sec = compute_retry_wait(attempt, response.headers.get("Retry-After"))
            log_structured("fetch_retry_wait", url=url, status=status, attempt=attempt, wait_seconds=wait_sec)
            time.sleep(wait_sec)
            continue

        raise FetchFailure(url, f"HTTP {status} after {attempt} attempts", status_code=status)

    raise FetchFailure(url, "Exhausted fetch attempts")


def parse_catalogue_links(html: str, page_url: str) -> tuple[list[str], str | None]:
    soup = BeautifulSoup(html, "html.parser")
    book_urls = [
        resolve_book_url(page_url, link["href"])
        for link in soup.select("article.product_pod h3 a[href]")
    ]
    next_anchor = soup.select_one("li.next a[href]")
    next_url = resolve_book_url(page_url, next_anchor["href"]) if next_anchor else None
    return book_urls, next_url


def deduplicate_urls(url_source_pairs: list[tuple[str, str]]) -> dict[str, str]:
    unique: dict[str, str] = {}
    for product_url, source_page in url_source_pairs:
        if product_url not in unique:
            unique[product_url] = source_page
    return unique


def discover_catalogue_books(
    start_url: str = START_URL, max_pages: int = MAX_CATALOGUE_PAGES
) -> tuple[int, int, dict[str, str], int, int]:
    current_url: str | None = start_url
    pages_visited = 0
    pages_fetched = 0
    cache_hits = 0
    discovered_pairs: list[tuple[str, str]] = []

    while current_url and pages_visited < max_pages:
        page_num = pages_visited + 1
        cache_file = CACHE_DIR / f"catalogue-page-{page_num}.html"
        html, _, from_cache = fetch_html(current_url, cache_file)
        if from_cache:
            cache_hits += 1
        else:
            pages_fetched += 1
        pages_visited += 1

        book_urls, next_url = parse_catalogue_links(html, current_url)
        for u in book_urls:
            discovered_pairs.append((u, current_url))
        current_url = next_url

    unique_books = deduplicate_urls(discovered_pairs)
    return pages_visited, len(discovered_pairs), unique_books, pages_fetched, cache_hits


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
    raw_desc = " ".join(desc_p.get_text().split()) if desc_p else ""
    description = raw_desc if raw_desc else None

    title_clean = " ".join(title_el.get_text().split()) if title_el else None
    price_clean = price_el.get_text(strip=True) if price_el else None
    avail_clean = " ".join(avail_el.get_text().split()) if avail_el else None

    return {
        "title": title_clean,
        "product_url": product_url,
        "price_text": price_clean,
        "availability_text": avail_clean,
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


def record_content_hash(item: dict) -> str:
    """Hash core book facts (excluding fetched_at) to detect real content changes across runs."""
    core = {
        k: item.get(k)
        for k in (
            "title",
            "product_url",
            "price_text",
            "price_gbp",
            "availability_text",
            "rating_text",
            "description",
        )
    }
    encoded = json.dumps(core, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def store_books_with_change_detection(
    records: list[BookRecord], books_path: Path
) -> tuple[list[dict], dict[str, int]]:
    previous_by_url: dict[str, dict] = {}
    if books_path.exists():
        try:
            loaded = json.loads(books_path.read_text(encoding="utf-8"))
            for item in loaded:
                if isinstance(item, dict) and "product_url" in item:
                    previous_by_url[item["product_url"]] = item
        except Exception:
            pass

    current_by_url: dict[str, dict] = {}
    for rec in records:
        current_by_url[rec.product_url] = rec.model_dump(mode="json")

    new_count = 0
    changed_count = 0
    unchanged_count = 0
    for url, curr in current_by_url.items():
        prev = previous_by_url.get(url)
        if prev is None:
            new_count += 1
        elif record_content_hash(prev) != record_content_hash(curr):
            changed_count += 1
        else:
            unchanged_count += 1

    gone_count = sum(1 for url in previous_by_url if url not in current_by_url)

    merged_by_url = {**previous_by_url, **current_by_url}
    merged = list(merged_by_url.values())
    books_path.parent.mkdir(parents=True, exist_ok=True)
    books_path.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")

    changes = {
        "new": new_count,
        "changed": changed_count,
        "unchanged": unchanged_count,
        "gone": gone_count,
    }
    return merged, changes


def export_books_csv(books: list[dict], csv_path: Path) -> None:
    """Export validated books to CSV, flattening multiline/null descriptions into single-line strings."""
    fieldnames = [
        "title",
        "product_url",
        "price_text",
        "price_gbp",
        "availability_text",
        "rating_text",
        "description",
        "source_page",
        "fetched_at",
    ]
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for b in books:
            row = dict(b)
            desc = row.get("description")
            row["description"] = " ".join(str(desc).splitlines()) if desc is not None else ""
            writer.writerow(row)


def write_dashboard_html(books: list[dict], report: dict, html_path: Path) -> None:
    prices = [b["price_gbp"] for b in books] or [0.0]
    min_p, max_p = min(prices), max(prices)
    avg_p = round(sum(prices) / len(prices), 2)
    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Polite Scraper — Run Dashboard</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 860px; margin: 2rem auto; padding: 0 1rem; background: #0f172a; color: #e2e8f0; }}
    h1 {{ color: #38bdf8; margin-bottom: 0.25rem; }}
    .sub {{ color: #94a3b8; margin-bottom: 1.5rem; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1rem; }}
    .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 1rem; }}
    .label {{ font-size: 0.8rem; color: #94a3b8; text-transform: uppercase; }}
    .val {{ font-size: 1.6rem; font-weight: 700; margin-top: 0.25rem; color: #f8fafc; }}
  </style>
</head>
<body>
  <h1>The Polite Scraper — Observability Dashboard</h1>
  <div class="sub">Last refreshed: {html_lib.escape(report["finished_at"])} · Duration: {report["duration_seconds"]}s</div>
  <div class="grid">
    <div class="card"><div class="label">Validated Records</div><div class="val">{report["valid_records"]}</div></div>
    <div class="card"><div class="label">Price Range (GBP)</div><div class="val">£{min_p:.2f} – £{max_p:.2f}</div></div>
    <div class="card"><div class="label">Average Price</div><div class="val">£{avg_p:.2f}</div></div>
    <div class="card"><div class="label">Cache Hits / Fetched</div><div class="val">{report["cache_hits"]} / {report["pages_fetched"]}</div></div>
    <div class="card"><div class="label">Failed Pages</div><div class="val">{report["failed_pages"]}</div></div>
    <div class="card"><div class="label">Invalid Records</div><div class="val">{report["invalid_records"]}</div></div>
  </div>
</body>
</html>
"""
    html_path.write_text(doc, encoding="utf-8")


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
        work_items.append((DELIBERATE_BROKEN_URL, "https://books.toscrape.com/catalogue/page-1.html"))

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
            log_structured("page_skipped_fetch_failure", url=exc.url, status=exc.status_code, reason=exc.reason)
            failed_pages.append(
                {
                    "url": exc.url,
                    "status_code": exc.status_code,
                    "reason": exc.reason,
                }
            )
        except Exception as exc:
            log_structured("page_skipped_unexpected_error", url=product_url, status=None, reason=str(exc))
            failed_pages.append(
                {"url": product_url, "status_code": None, "reason": str(exc)}
            )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    merged, changes = store_books_with_change_detection(
        valid_records, OUTPUT_DIR / "books.json"
    )
    (OUTPUT_DIR / "errors.json").write_text(
        json.dumps(error_records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    export_books_csv(merged, OUTPUT_DIR / "books.csv")

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
        "changed_since_last_run": changes,
        "failures": failed_pages,
    }
    (OUTPUT_DIR / "run-report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    write_dashboard_html(merged, report, OUTPUT_DIR / "dashboard.html")

    print(
        f"catalogue_pages={cat_pages}, discovered={discovered_total}, "
        f"unique_urls={len(unique_books)}, valid_records={len(merged)}, "
        f"failed_pages={len(failed_pages)}, cache_hits={cache_hits}, "
        f"changes={changes}"
    )


if __name__ == "__main__":
    main()
