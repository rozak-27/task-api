"""Stage 4 — Normalize fields, validate with Pydantic schema, and store idempotently."""

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
USER_AGENT = "FlyRankInternship-A9/1.0 (+https://github.com/rozak-27/task-api)"
TIMEOUT_SECONDS = 10
POLITE_DELAY_SECONDS = 0.52
MAX_CATALOGUE_PAGES = 3

RATING_WORDS = {"One", "Two", "Three", "Four", "Five"}
_last_network_request_at: float | None = None


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
    global _last_network_request_at
    if cache_path.exists():
        html = cache_path.read_text(encoding="utf-8")
        mtime = datetime.fromtimestamp(cache_path.stat().st_mtime, tz=timezone.utc)
        fetched_at = mtime.strftime("%Y-%m-%dT%H:%M:%SZ")
        return html, fetched_at, True

    polite_wait()
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT_SECONDS,
    )
    _last_network_request_at = time.monotonic()

    if response.status_code != 200:
        raise RuntimeError(f"Failed fetch for {url}: HTTP {response.status_code}")

    html = response.content.decode("utf-8")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(html, encoding="utf-8")
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return html, now_iso, False


def discover_catalogue_books(start_url: str = START_URL, max_pages: int = MAX_CATALOGUE_PAGES):
    current_url: str | None = start_url
    pages_visited = 0
    unique_books: dict[str, str] = {}

    while current_url and pages_visited < max_pages:
        page_num = pages_visited + 1
        cache_file = CACHE_DIR / f"catalogue-page-{page_num}.html"
        html, _, _ = fetch_html(current_url, cache_file)
        pages_visited += 1

        soup = BeautifulSoup(html, "html.parser")
        for link in soup.select("article.product_pod h3 a[href]"):
            abs_book_url = urljoin(current_url, link["href"])
            if abs_book_url not in unique_books:
                unique_books[abs_book_url] = current_url

        next_anchor = soup.select_one("li.next a[href]")
        current_url = urljoin(current_url, next_anchor["href"]) if next_anchor else None

    return unique_books


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
    """Key records by canonical product_url so reruns update in place and never duplicate."""
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
    unique_books = discover_catalogue_books()
    valid_records: list[BookRecord] = []
    error_records: list[dict] = []

    for product_url, source_page in unique_books.items():
        html, fetched_at, _ = fetch_html(product_url, book_cache_path(product_url))
        raw = extract_raw_book(html, product_url, source_page, fetched_at)
        validated, err = normalize_and_validate(raw)
        if validated is not None:
            valid_records.append(validated)
        elif err is not None:
            error_records.append(err)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    merged = store_books_idempotently(valid_records, OUTPUT_DIR / "books.json")
    (OUTPUT_DIR / "errors.json").write_text(
        json.dumps(error_records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"valid_records={len(merged)}, invalid_records={len(error_records)}")


if __name__ == "__main__":
    main()
